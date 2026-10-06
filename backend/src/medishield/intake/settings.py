"""Email intake settings, read from the environment on every call (on AWS the values come from SSM Parameter Store:
``/medishield/intake_senders`` becomes ``INTAKE_SENDERS`` at cold start, like every other secret).

``INTAKE_SENDERS``                  JSON object ``{"sender address": "username"}``: the only senders whose mail is processed.
                                    Empty, missing or malformed = every sender is rejected (fail closed).
``INTAKE_MAX_EMAIL_BYTES``          largest raw message accepted (default 40 MB, the SES receiving limit)
``INTAKE_MIN_INLINE_IMAGE_BYTES``   inline PNG/JPEG parts smaller than this are logos or signature images (default 20 KB)
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field

from medishield.config import get_settings

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class IntakeSettings:
    senders: dict[str, str] = field(default_factory=dict)
    max_email_bytes: int = 40 * 1024 * 1024
    min_inline_image_bytes: int = 20 * 1024


def _senders(raw: str) -> dict[str, str]:
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        data = None
    if not isinstance(data, dict):
        log.error("INTAKE_SENDERS must be a JSON object {\"address\": \"username\"}; every email sender will be rejected")
        return {}
    return {str(k).strip().lower(): str(v).strip() for k, v in data.items() if str(k).strip() and str(v).strip()}


def intake_settings() -> IntakeSettings:
    get_settings()                                       # loads .env into the environment on first use
    return IntakeSettings(
        senders=_senders(os.environ.get("INTAKE_SENDERS", "")),
        max_email_bytes=int(os.environ.get("INTAKE_MAX_EMAIL_BYTES", str(40 * 1024 * 1024))),
        min_inline_image_bytes=int(os.environ.get("INTAKE_MIN_INLINE_IMAGE_BYTES", str(20 * 1024))),
    )
