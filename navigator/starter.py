"""Read-only loaders for the participant pack in data/starter/."""
from __future__ import annotations

import csv
import json
from functools import lru_cache
from typing import Any

from navigator import settings


@lru_cache(maxsize=1)
def manifest() -> dict[str, dict[str, str]]:
    """doc_id -> manifest row (all 87 rows, text or not)."""
    with settings.path("manifest").open(encoding="utf-8", newline="") as fh:
        return {row["doc_id"]: row for row in csv.DictReader(fh)}


@lru_cache(maxsize=1)
def addresses() -> list[dict[str, str]]:
    with settings.path("addresses").open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def address_ids() -> list[str]:
    return [row["address_id"] for row in addresses()]


@lru_cache(maxsize=1)
def change_tests() -> list[dict[str, Any]]:
    return json.loads(settings.path("change_tests").read_text(encoding="utf-8"))


def change_test_ids() -> list[str]:
    return [t["test_id"] for t in change_tests()]


@lru_cache(maxsize=1)
def rule_schema() -> dict[str, Any]:
    return json.loads(settings.path("schema").read_text(encoding="utf-8"))


def doc_text(doc_id: str) -> str | None:
    """Full stored text of a corpus document (header included), or None if it has no text."""
    row = manifest().get(doc_id)
    if not row or not row["text_file"]:
        return None
    p = settings.path("manifest").parent / row["text_file"]
    if not p.is_file() or p.stat().st_size == 0:
        return None
    # newline="" keeps the bytes as stored so character offsets stay valid.
    with p.open(encoding="utf-8", newline="") as fh:
        return fh.read()
