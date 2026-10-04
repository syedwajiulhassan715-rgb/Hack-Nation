"""Rule status on any query date: a thin wrapper over navigator.extract.dates.status_on.

The `status` stored on a rule is for the default as-of date only. The extraction's
status hint (`enacted` | `bill_or_proposal` | `failed`) lives in `provenance[*]`;
provenance is sorted best source first by verify, so the first entry is the one the
rule's fields came from.
"""
from __future__ import annotations

from navigator.extract import dates
from navigator.schema.models import RuleInternal

_HINT_FROM_STATUS = {"in_force": "enacted", "not_yet_effective": "enacted",
                     "pending": "bill_or_proposal", "failed": "failed"}


def status_hint(rule: RuleInternal) -> str:
    for p in rule.provenance:
        hint = p.get("status_hint")
        if hint:
            return str(hint)
    return _HINT_FROM_STATUS[rule.status]


def status_on(rule: RuleInternal, as_of: str) -> str:
    """in_force | not_yet_effective | pending | failed on `as_of` (YYYY-MM-DD)."""
    return dates.status_on(status_hint(rule), rule.effective_date, as_of)
