"""Model access: schema-constrained calls with routing, retries, caching and a spend ledger.

Names are loaded on first use (PEP 562), so importing ``medishield.llm.cost`` - as the API does for the budget check - does
not load the model SDK. The API Lambda starts faster for it."""

from __future__ import annotations

import importlib

_WHERE = {
    **dict.fromkeys(("CacheMiss", "ImagePart", "LLMError", "LLMRefusal", "LLMResult", "LLMSchemaError", "image_part",
                     "structured", "structured_with_retry"), "medishield.llm.client"),
    **dict.fromkeys(("BudgetExceeded", "ledger"), "medishield.llm.cost"),
    **dict.fromkeys(("OPUS", "SONNET", "route"), "medishield.llm.routing"),
}
__all__ = ["OPUS", "SONNET", "BudgetExceeded", "CacheMiss", "ImagePart", "LLMError", "LLMRefusal", "LLMResult",
           "LLMSchemaError", "image_part", "ledger", "route", "structured", "structured_with_retry"]


def __getattr__(name: str):
    if name in _WHERE:
        return getattr(importlib.import_module(_WHERE[name]), name)
    raise AttributeError(f"module 'medishield.llm' has no attribute {name!r}")
