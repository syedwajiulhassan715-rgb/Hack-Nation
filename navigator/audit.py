"""Append-only audit log (outputs/audit.jsonl): one JSON line per decision.

Fields follow BACKEND_PLAN.md 2.11; unused ones are omitted rather than nulled.
"""
from __future__ import annotations

import datetime as dt
import json
import threading
from pathlib import Path
from typing import Any

from navigator import settings

_lock = threading.Lock()  # extract calls the model from worker threads


def log_path() -> Path:
    return settings.path("outputs") / "audit.jsonl"


def log(stage: str, decision: str, reason: str | None = None, **fields: Any) -> None:
    entry = {"ts": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "stage": stage, "decision": decision}
    if reason:
        entry["reason"] = reason
    entry.update({k: v for k, v in fields.items() if v is not None})
    path = log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    with _lock, path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(line)
