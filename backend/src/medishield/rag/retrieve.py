"""Hybrid policy retrieval: BM25 + dense (fastembed) in Qdrant, RRF-fused, plan-filtered, bge-reranked.

The vector store is an in-memory Qdrant collection built from the cached Docling chunks at start-up (two
short policies -> ~100 chunks, a few seconds). ``QDRANT_URL`` support (Qdrant Cloud) arrives with deploy.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from functools import lru_cache

from qdrant_client import QdrantClient, models

from medishield.config import get_settings
from medishield.rag.exclusions import CptRange
from medishield.rag.ingest import Chunk, PolicyIndex, load_or_ingest, policy_pdfs

DENSE_MODEL = "BAAI/bge-small-en-v1.5"
SPARSE_MODEL = "Qdrant/bm25"
RERANK_MODEL = "jinaai/jina-reranker-v1-turbo-en"   # 0.15 GB; beat bge-reranker-base (1.04 GB) on the gold set, see docs/eval_results/reranker.json
COLLECTION = "policies"
_CODE_RE = re.compile(r"[A-Za-z0-9]+(?:[.\-][A-Za-z0-9]+)+")
_lock = threading.Lock()


def sparse_text(text: str) -> str:
    """Keep codes and ranges (``97010-97799``, ``S4(a)``) as whole BM25 terms as well as their parts."""
    codes = {m.group(0).replace(".", "_").replace("-", "_") for m in _CODE_RE.finditer(text)
             if any(c.isdigit() for c in m.group(0))}
    return f"{text} {' '.join(sorted(codes))}" if codes else text


def _embed_sorted(model, texts: list[str], batch_size: int = 8) -> list:
    """Embed in small batches of similar length. A transformer pads every text in a batch to the longest one, so one large
    unsorted batch wastes most of its work on padding (measured: 92 policy passages 3.7 s -> 1.1 s). Output keeps input order."""
    order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
    vecs = list(model.embed([texts[i] for i in order], batch_size=batch_size))
    out: list = [None] * len(texts)
    for pos, i in enumerate(order):
        out[i] = vecs[pos]
    return out


def _rerank_sorted(reranker, query: str, docs: list[str], batch_size: int = 4) -> list[float]:
    """Cross-encoder scores in small length-sorted batches (same padding reason; 20 candidates 0.40 s -> ~0.1 s)."""
    order = sorted(range(len(docs)), key=lambda i: len(docs[i]))
    scores = list(reranker.rerank(query, [docs[i] for i in order], batch_size=batch_size))
    out = [0.0] * len(docs)
    for pos, i in enumerate(order):
        out[i] = float(scores[pos])
    return out


@dataclass
class Hit:
    chunk: Chunk
    score: float
    fused_rank: int


class PolicyStore:
    def __init__(self, indexes: list[PolicyIndex], rerank_model: str | None = None):
        from fastembed import SparseTextEmbedding, TextEmbedding
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        cache = str(get_settings().cache_dir / "fastembed")
        self.indexes = {i.plan: i for i in indexes}
        self.chunks = {c.chunk_id: c for i in indexes for c in i.chunks}
        self.dense = TextEmbedding(DENSE_MODEL, cache_dir=cache)
        self.sparse = SparseTextEmbedding(SPARSE_MODEL, cache_dir=cache)
        self.reranker = TextCrossEncoder(rerank_model or RERANK_MODEL, cache_dir=cache)
        self.client = QdrantClient(":memory:")
        dim = len(next(iter(self.dense.embed(["dim"]))))
        self.client.create_collection(
            COLLECTION,
            vectors_config={"dense": models.VectorParams(size=dim, distance=models.Distance.COSINE)},
            sparse_vectors_config={"bm25": models.SparseVectorParams(modifier=models.Modifier.IDF)},
        )
        chunks = list(self.chunks.values())
        texts = [c.embed_text for c in chunks]
        dense = _embed_sorted(self.dense, texts)
        sparse = _embed_sorted(self.sparse, [sparse_text(t) for t in texts])
        self.client.upsert(COLLECTION, [
            models.PointStruct(
                id=i, payload={"chunk_id": c.chunk_id, "plan": c.plan, "section_no": c.section_no},
                vector={"dense": d.tolist(),
                        "bm25": models.SparseVector(indices=s.indices.tolist(), values=s.values.tolist())})
            for i, (c, d, s) in enumerate(zip(chunks, dense, sparse))])

    def ranges(self, plan: str) -> list[CptRange]:
        return self.indexes[plan].ranges if plan in self.indexes else []

    def search(self, query: str, plan: str | None, k: int = 5, candidates: int = 20) -> list[Hit]:
        flt = (models.Filter(must=[models.FieldCondition(key="plan", match=models.MatchValue(value=plan))])
               if plan else None)
        with _lock:
            dq = next(iter(self.dense.query_embed(query))).tolist()
            sq = next(iter(self.sparse.query_embed(sparse_text(query))))
            prefetch = [models.Prefetch(query=dq, using="dense", filter=flt, limit=candidates)]
            if len(sq.indices):
                prefetch.append(models.Prefetch(
                    query=models.SparseVector(indices=sq.indices.tolist(), values=sq.values.tolist()),
                    using="bm25", filter=flt, limit=candidates))
            pts = self.client.query_points(COLLECTION, prefetch=prefetch, query=models.FusionQuery(
                fusion=models.Fusion.RRF), query_filter=flt, limit=candidates, with_payload=True).points
            fused = [self.chunks[p.payload["chunk_id"]] for p in pts]
            if not fused:
                return []
            scores = _rerank_sorted(self.reranker, query, [c.embed_text for c in fused])
        ranked = sorted(zip(fused, scores, range(1, len(fused) + 1)), key=lambda t: t[1], reverse=True)
        return [Hit(c, float(s), r) for c, s, r in ranked[:k]]


_store_lock = threading.Lock()


@lru_cache
def _build_store() -> PolicyStore:
    from medishield.services.policies import uploaded_policy_paths

    indexes = {i.plan: i for i in (load_or_ingest(p) for p in policy_pdfs())}
    for p in uploaded_policy_paths():
        idx = load_or_ingest(p)
        plan = p.stem.split("-")[0]
        idx.plan = plan
        for c in idx.chunks:
            c.plan = plan
        indexes[plan] = idx
    return PolicyStore(list(indexes.values()))


def get_store() -> PolicyStore:
    """The policy store, built once; concurrent first callers wait for the same build."""
    with _store_lock:
        return _build_store()


get_store.cache_clear = _build_store.cache_clear          # type: ignore[attr-defined]
