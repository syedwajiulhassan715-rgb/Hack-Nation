"""Change tracking (navigator/changes): matcher and per-type trackers.

Synthetic tests use made-up places, rules and dates; none is real law. The last test checks
the expected behaviors in dev/change_tests.json against the real outputs when they exist.
"""
from __future__ import annotations

import json

import pytest

from navigator import settings, starter
from navigator.changes import matcher, tracker
from navigator.schema.models import RuleInternal

SPAN = "A landlord shall comply with the synthetic test requirement in all cases."
JURS = ["ZZ", "Alpha City, ZZ", "Beta Town, ZZ", "Gamma, ZZ"]
IDS = starter.address_ids()[:4]       # real ids (output order), synthetic everything else


def rule(rid, *, jur="ZZ", cat="algorithmic_rent_setting", eff="2030-01-01", hint="enacted",
         status="in_force", pred=None):
    return RuleInternal(
        team_rule_id=rid, jurisdiction=jur, level="city" if ", " in jur else "state", category=cat,
        status=status, title="t", requirement="r", effective_date=eff, citation=f"Test Code {rid}",
        source_doc_id="SYN-1", source_url="https://example.invalid/doc", quoted_span=SPAN,
        confidence=0.9, predicates=pred, provenance=[{"status_hint": hint, "source_doc_id": "SYN-1"}])


def parcel(aid, city, postal=None, units=10):
    return {"address_id": aid, "street_address": "1 Test St",
            "postal_city": postal or (city or "X").split(",")[0],
            "state": "ZZ", "city": city, "lat": None, "lng": None, "geoids": {},
            "jurisdiction_confidence": "high" if city else "low", "jurisdiction_source": "synthetic",
            "year_built": 1990, "units": units, "units_min": units, "units_max": units,
            "units_source": "units", "use_code": None, "use_description": "Apartments",
            "missing_facts": [], "needs_review": False, "review_reasons": []}


PARCELS = [parcel(IDS[0], "Alpha City, ZZ"), parcel(IDS[1], "Beta Town, ZZ"),
           parcel(IDS[2], "Gamma, ZZ"), parcel(IDS[3], None, postal="Alpha City")]


def entry(**keys):
    """Mapping entry as written to config/test_rule_map.yaml: org id -> (place, our ids)."""
    return {key: {org: {"jurisdiction": j, "level": "city" if ", " in j else "state",
                        "category": matcher.KIND_CATEGORY[org.split("-")[1]],
                        "team_rule_ids": rids} for org, (j, rids) in v.items()} for key, v in keys.items()}


# ------------------------------------------------------------------ matcher


@pytest.mark.smoke
def test_matcher_state_kind_and_status_class():
    rules = [rule("r-1"), rule("r-2", hint="bill_or_proposal", status="pending"),
             rule("r-3", cat="rent_increase_limits")]
    assert matcher.match_id("ZZ-ALG-01", rules, ["ZZ"], JURS).team_rule_ids == ["r-1"]
    assert matcher.match_id("ZZ-ALG-P1", rules, ["ZZ"], JURS).team_rule_ids == ["r-2"]
    assert matcher.match_id("ZZ-RENT-01", rules, ["ZZ"], JURS).team_rule_ids == ["r-3"]
    m = matcher.match_id("ZZ-RENT-P1", rules, ["ZZ"], JURS)
    assert m.team_rule_ids == [] and "no pending or failed" in m.problem


@pytest.mark.smoke
def test_matcher_city_prefixes_initials_and_name_start():
    rules = [rule("r-a", jur="Alpha City, ZZ"), rule("r-b", jur="Beta Town, ZZ")]
    assert matcher.match_id("AC-ALG-01", rules, None, JURS).team_rule_ids == ["r-a"]
    assert matcher.match_id("BET-ALG-01", rules, None, JURS).team_rule_ids == ["r-b"]
    m = matcher.match_id("GAM-ALG-01", rules, None, JURS)       # place resolves, no rule text
    assert (m.jurisdiction, m.level, m.team_rule_ids) == ("Gamma, ZZ", "city", [])


@pytest.mark.smoke
def test_matcher_fails_closed_on_unknown_or_bad_ids():
    assert matcher.match_id("QQ-ALG-01", [], None, JURS).problem
    assert matcher.match_id("ZZ-FOO-01", [], None, JURS).problem == "unknown kind FOO"
    assert matcher.match_id("nonsense", [], None, JURS).problem


# ------------------------------------------------------------------ trackers


@pytest.mark.smoke
def test_as_of_affected_and_conflict_for_textless_city():
    ctx = tracker.Context([rule("r-1", eff="2030-01-01")], PARCELS)
    test = {"type": "as_of", "as_of_before": "2029-12-31", "as_of_after": "2030-01-02", "states": ["ZZ"]}
    o = tracker.track(ctx, test, entry(rule_ids={"ZZ-ALG-01": ("ZZ", ["r-1"])},
                                       conflict_with={"AC-ALG-01": ("Alpha City, ZZ", [])}))
    assert o.affected == IDS
    assert all(c.passed for c in o.checks)
    # the legal-city address, plus the unresolved one whose postal city names it
    assert o.conflicts == sorted([IDS[0], IDS[3]])


@pytest.mark.smoke
def test_as_of_without_mapped_rule_computes_nothing():
    ctx = tracker.Context([], PARCELS)
    test = {"type": "as_of", "as_of_before": "2029-12-31", "as_of_after": "2030-01-02", "states": ["ZZ"]}
    o = tracker.track(ctx, test, entry(rule_ids={"ZZ-ALG-01": ("ZZ", [])}))
    assert o.affected == [] and o.checks[0].passed is None


@pytest.mark.smoke
def test_boundary_with_rule_and_textless_city():
    ctx = tracker.Context([rule("r-b", jur="Beta Town, ZZ", eff="2020-01-01")], PARCELS)
    o = tracker.track(ctx, {"type": "boundary", "as_of": "2030-06-01"},
                      entry(rule_ids={"BT-ALG-01": ("Beta Town, ZZ", ["r-b"]),
                                      "AC-ALG-01": ("Alpha City, ZZ", [])}))
    assert o.affected == sorted([IDS[0], IDS[1]])
    assert [c.passed for c in o.checks] == [True, None, True]


@pytest.mark.smoke
def test_pending_reports_pending_and_hypothetical_affected():
    rules = [rule("r-p", hint="bill_or_proposal", status="pending", eff=None),
             rule("r-q", hint="bill_or_proposal", status="pending", eff=None,
                  pred={"fact": "units", "op": ">=", "value": 50})]
    ctx = tracker.Context(rules, PARCELS)
    o = tracker.track(ctx, {"type": "pending", "as_of": "2030-06-01", "states": ["ZZ"]},
                      entry(rule_ids={"ZZ-ALG-P1": ("ZZ", ["r-p", "r-q"])}))
    assert o.affected == IDS                  # r-p covers all; r-q covers none (10 units)
    assert o.checks[0].passed                 # not in force
    assert o.checks[1].passed is False        # r-q is left out of lookups, so not "pending" everywhere


@pytest.mark.smoke
def test_negative_flags_city_rent_limit_and_never_affects():
    rules = [rule("r-c", jur="Gamma, ZZ", cat="rent_increase_limits", eff="2020-01-01"),
             rule("r-f", cat="rent_increase_limits", hint="failed", status="failed", eff=None)]
    ctx = tracker.Context(rules, PARCELS)
    o = tracker.track(ctx, {"type": "negative", "as_of": "2030-06-01", "states": ["ZZ"]},
                      entry(rule_ids={"ZZ-RENT-P1": ("ZZ", ["r-f"])}))
    assert o.affected == []
    assert [c.passed for c in o.checks] == [True, True, False]   # failed recorded; absent; city cap reported


@pytest.mark.smoke
def test_unknown_test_type_fails_closed():
    o = tracker.track(tracker.Context([], PARCELS), {"type": "mystery"}, {})
    assert o.affected == [] and o.checks[0].passed is False


# ------------------------------------------------------------------ real outputs


def test_real_outputs_meet_expected_behavior():
    out = settings.path("outputs")
    path = out / "changes_internal.json"
    if not path.is_file() or (out / "STUB").exists():
        pytest.skip("pipeline outputs not built")
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert set(doc["tests"]) == set(starter.change_test_ids())
    failed = [(tid, c["name"]) for tid, t in doc["tests"].items() for c in t["checks"] if c["passed"] is False]
    assert not failed
    changes = json.loads((out / "changes.json").read_text(encoding="utf-8"))
    assert changes["T5"]["affected_address_ids"] == []
