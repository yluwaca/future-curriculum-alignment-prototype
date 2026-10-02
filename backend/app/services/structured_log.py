"""
Structured JSON logging for labour-market operational events.

Emits one single-line JSON envelope per event at INFO level so that log
aggregators can index structured fields without parsing free text.

Redaction contract: callers MUST NOT pass credentials, tokens, auth
payloads, or full source documents (e.g. complete job adverts). This module
only serialises the fields it is given and does not scrub values, so the
policy lives at the call site: field names below encode opaque identifiers
and derived counts, never secret material or document text.
"""

import json
import logging
from datetime import date, datetime
from typing import Any
from uuid import UUID

_SERIALISABLE = (str, int, float, bool)


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if value is None:
        return None
    return str(value)


def log_structured(logger: logging.Logger, event: str, **fields: Any) -> None:
    """Emit ``event`` plus scalar/serialisable fields as one JSON line."""
    record: dict[str, Any] = {"event": event}
    record.update(fields)
    logger.info(json.dumps(record, default=_json_default, sort_keys=True, ensure_ascii=False))