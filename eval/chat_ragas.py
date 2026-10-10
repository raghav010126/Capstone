"""RAGAS metrics for the assistant's answerable questions: faithfulness, answer relevancy, context precision, context recall.

Each sample is the question, the assistant's answer, the passages it was given (``contexts``, returned only to the evaluation)
and a reference answer built from the item's expected facts (data-derived, never typed by hand). Blocked and out-of-scope
questions have no passages to grade and are left to the rule checks and the judge.

The metric LLM is Claude Sonnet 5.5 through ``langchain-anthropic``; embeddings use the same local bge-small model as the policy
search, so they cost nothing. RAGAS is not a project dependency (its pins would change the API image's packages), so it runs in
an overlay environment:

    uv run --no-sync --with "ragas==0.4.3" --with langchain-anthropic --with "langchain-community<0.4" \\
        python eval/chat_eval.py --ragas

These calls bypass the project's spend ledger; their token usage is measured with RAGAS's Anthropic usage parser and recorded
in the artifact.
"""

from __future__ import annotations

import math

METRIC_LLM = "claude-sonnet-5-5"
METRICS = ("faithfulness", "answer_relevancy", "llm_context_precision_with_reference", "context_recall")
OVERLAY = ('uv run --no-sync --with "ragas==0.4.3" --with langchain-anthropic --with "langchain-community<0.4" '
           "python eval/chat_eval.py --ragas")


def reference(row: dict) -> str:
    """A short reference answer from the expected facts: the first alternative of each group."""
    facts = [group[0] for group in row["facts"] if group]
    return f"A correct answer to \"{row['question']}\" states: " + "; ".join(facts) + "."


def run(samples: list[dict]) -> dict:
    """``samples``: dicts with question, answer, contexts, reference and an id. Returns per-sample and mean scores."""
    import os

    os.environ.setdefault("RAGAS_DO_NOT_TRACK", "true")   # no usage telemetry to a third party (it also mis-reads local embedders)
    try:
        from langchain_anthropic import ChatAnthropic
        from langchain_core.embeddings import Embeddings
        from ragas import EvaluationDataset, evaluate
        from ragas.embeddings import LangchainEmbeddingsWrapper
        from ragas.llms import LangchainLLMWrapper
        from ragas.metrics import (
            Faithfulness,
            LLMContextPrecisionWithReference,
            LLMContextRecall,
            ResponseRelevancy,
        )
        from ragas.run_config import RunConfig
    except ImportError as e:
        raise SystemExit(f"RAGAS is not installed in this environment ({e}). Run:\n  {OVERLAY}") from e

    from medishield.config import get_settings
    from medishield.llm.cost import PRICES
    from medishield.rag.retrieve import DENSE_MODEL

    s = get_settings()                                   # loads .env, so ChatAnthropic finds ANTHROPIC_API_KEY
    # Sonnet 5.5 rejects non-default temperature, and Anthropic has no n>1 sampling: let RAGAS skip both
    llm = LangchainLLMWrapper(ChatAnthropic(model=METRIC_LLM, max_tokens=4000, timeout=180, max_retries=3),
                              bypass_temperature=True, bypass_n=True)
    from fastembed import TextEmbedding

    class LocalEmbeddings(Embeddings):
        """The policy search's own bge-small, as a LangChain embedder whose ``model`` is its name (RAGAS logs it)."""

        def __init__(self) -> None:
            self.model = DENSE_MODEL
            self._m = TextEmbedding(DENSE_MODEL, cache_dir=str(s.cache_dir / "fastembed"))

        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            return [v.tolist() for v in self._m.embed(texts)]

        def embed_query(self, text: str) -> list[float]:
            return self.embed_documents([text])[0]

    emb = LangchainEmbeddingsWrapper(LocalEmbeddings())
    data = EvaluationDataset.from_list([{"user_input": x["question"], "response": x["answer"],
                                         "retrieved_contexts": x["contexts"] or ["(nothing retrieved)"],
                                         "reference": x["reference"]} for x in samples])
    kwargs = {}
    try:
        from ragas.cost import get_token_usage_for_anthropic
        kwargs["token_usage_parser"] = get_token_usage_for_anthropic
    except ImportError:
        pass
    result = evaluate(data, metrics=[Faithfulness(), ResponseRelevancy(), LLMContextPrecisionWithReference(), LLMContextRecall()],
                      llm=llm, embeddings=emb, run_config=RunConfig(max_workers=4, timeout=300), show_progress=False, **kwargs)
    df = result.to_pandas()
    per = []
    for x, (_, rec) in zip(samples, df.iterrows(), strict=True):
        per.append({"id": x["id"], "question": x["question"],
                    **{m: (None if rec.get(m) is None or (isinstance(rec.get(m), float) and math.isnan(rec.get(m)))
                           else round(float(rec.get(m)), 4)) for m in METRICS}})
    mean = {m: (round(sum(v[m] for v in per if v[m] is not None) / n, 4) if (n := sum(v[m] is not None for v in per)) else None)
            for m in METRICS}
    spend = None
    if "token_usage_parser" in kwargs:
        pin, pout, _ = PRICES[METRIC_LLM]
        try:
            spend = round(result.total_cost(cost_per_input_token=pin / 1e6, cost_per_output_token=pout / 1e6), 4)
        except Exception:          # noqa: BLE001 - usage is informational; never fail the evaluation over it
            spend = None
    return {"metric_llm": METRIC_LLM, "embeddings": DENSE_MODEL, "samples": len(per), "mean": mean, "rows": per,
            "spend_usd": spend, "missing_scores": sum(v[m] is None for v in per for m in METRICS)}
