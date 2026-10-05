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
RERANK_MODEL = "BAAI/bge-reranker-base"
COLLECTION = "policies"
_CODE_RE = re.compile(r"[A-Za-z0-9]+(?:[.\-][A-Za-z0-9]+)+")
_lock = threading.Lock()


def sparse_text(text: str) -> str:
    """Keep codes and ranges (``97010-97799``, ``S4(a)``) as whole BM25 terms as well as their parts."""
    codes = {m.group(0).replace(".", "_").replace("-", "_") for m in _CODE_RE.finditer(text)
             if any(c.isdigit() for c in m.group(0))}
    return f"{text} {' '.join(sorted(codes))}" if codes else text


@dataclass
class Hit:
    chunk: Chunk
    score: float
    fused_rank: int


class PolicyStore:
    def __init__(self, indexes: list[PolicyIndex]):
        from fastembed import SparseTextEmbedding, TextEmbedding
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        cache = str(get_settings().cache_dir / "fastembed")
        self.indexes = {i.plan: i for i in indexes}
        self.chunks = {c.chunk_id: c for i in indexes for c in i.chunks}
        self.dense = TextEmbedding(DENSE_MODEL, cache_dir=cache)
        self.sparse = SparseTextEmbedding(SPARSE_MODEL, cache_dir=cache)
        self.reranker = TextCrossEncoder(RERANK_MODEL, cache_dir=cache)
        self.client = QdrantClient(":memory:")
        dim = len(next(iter(self.dense.embed(["dim"]))))
        self.client.create_collection(
            COLLECTION,
            vectors_config={"dense": models.VectorParams(size=dim, distance=models.Distance.COSINE)},
            sparse_vectors_config={"bm25": models.SparseVectorParams(modifier=models.Modifier.IDF)},
        )
        chunks = list(self.chunks.values())
        texts = [c.embed_text for c in chunks]
        dense = list(self.dense.embed(texts))
        sparse = list(self.sparse.embed([sparse_text(t) for t in texts]))
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
            scores = list(self.reranker.rerank(query, [c.embed_text for c in fused]))
        ranked = sorted(zip(fused, scores, range(1, len(fused) + 1)), key=lambda t: t[1], reverse=True)
        return [Hit(c, float(s), r) for c, s, r in ranked[:k]]


@lru_cache
def get_store() -> PolicyStore:
    return PolicyStore([load_or_ingest(p) for p in policy_pdfs()])
