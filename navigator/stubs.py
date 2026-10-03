"""Phase-1 stub outputs: contract-valid but empty, so the eval harness runs end to end.

Stubs are NOT answers. An empty lookup list reads as "no rule applies", so every stub
run writes outputs/STUB and the eval report says STUB OUTPUTS on its first line.
Real pipeline stages call `clear_marker()` when they write genuine results.
"""
from __future__ import annotations

from navigator import settings, starter
from navigator.schema.models import ChangeResult
from navigator.schema.writers import write_changes, write_lookups, write_rules

STUB_NOTE = "STUB: pipeline not run yet; this is not a result."


def marker_path():
    return settings.path("outputs") / "STUB"


def clear_marker() -> None:
    marker_path().unlink(missing_ok=True)


def run() -> None:
    as_of = settings.load()["default_as_of"]
    write_rules([])
    write_lookups(as_of, {aid: [] for aid in starter.address_ids()}, [])
    write_changes({
        tid: ChangeResult(affected_address_ids=[], conflict_flag_address_ids=[], notes=STUB_NOTE)
        for tid in starter.change_test_ids()
    })
    marker_path().write_text(STUB_NOTE + "\n", encoding="utf-8")
    print("wrote stub rules.json, lookups.json, changes.json (outputs/STUB marker set)")
