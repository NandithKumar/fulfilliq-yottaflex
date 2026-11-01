"""Small deterministic helpers shared by the generator and decision engine."""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from typing import Any


def stable_int(seed: int, key: str, modulo: int = 1_000_000) -> int:
    digest = hashlib.sha256(f"{seed}|{key}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % modulo


def iso(value: date | datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=__import__("datetime").timezone.utc)
    return parsed


def add_business_days(start: date, days: int, holidays: set[date], operating_weekdays: set[int] | None = None) -> date:
    """Add business days. The start date is day zero; holidays/weekends are skipped."""
    operating_weekdays = operating_weekdays or {0, 1, 2, 3, 4, 5}
    current = start
    added = 0
    while added < days:
        current += timedelta(days=1)
        if current.weekday() in operating_weekdays and current not in holidays:
            added += 1
    return current


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
