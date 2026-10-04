"""Coverage engine (navigator/engine): synthetic rules and parcels only, no network, no LLM.

Rule ids, citations, places, dates and thresholds here are made up; none is real law.
"""
from __future__ import annotations

import json

import pytest

from navigator.engine import coverage, explain_lookup, lookup, precedence
from navigator.engine.coverage import FALSE, TRUE, UNKNOWN
from navigator.engine.facts import parcel_facts
from navigator.schema.models import RuleInternal

pytestmark = pytest.mark.smoke

AS_OF = "2030-06-01"
STATE = "ZZ"
CITY = "Testville, ZZ"
SPAN = "A landlord shall comply with the synthetic test requirement in all cases."


def rule(rid, *, level="state", jur=STATE, cat="rent_increase_limits", pred=None, eff="2020-01-01",
         hint="enacted", exemptions=None, interaction=None, cite=None, key_value=None):
    return RuleInternal(
        team_rule_id=rid, jurisdiction=jur, level=level, category=cat,
        status="in_force", title="t", requirement="r", key_value=key_value,
        exemptions=exemptions, interaction=interaction, effective_date=eff,
        citation=cite or f"Test Code Part {rid[-1]}", source_doc_id="SYN-1",
        source_url="https://example.invalid/doc", quoted_span=SPAN, confidence=0.9,
        predicates=pred, provenance=[{"status_hint": hint, "source_doc_id": "SYN-1"}])


def parcel(aid="A1", *, city=CITY, conf="high", year=None, units=None, lo=None, hi=None,
           use="Apartments"):
    return {"address_id": aid, "street_address": "1 Test St", "postal_city": "Testville",
            "state": STATE, "city": city, "lat": None, "lng": None, "geoids": {},
            "jurisdiction_confidence": conf, "jurisdiction_source": "synthetic",
            "year_built": year, "units": units, "units_min": lo, "units_max": hi,
            "units_source": "units" if units is not None else None, "use_code": None,
            "use_description": use, "missing_facts": [], "needs_review": False, "review_reasons": []}


def cov(pred, **kw):
    return coverage.evaluate(pred, parcel_facts(parcel(**kw)))


def by_id(rows):
    return {r.team_rule_id: r for r in rows}


# ------------------------------------------------------------------ coverage


def test_no_predicates_covers_jurisdiction():
    c = cov(None)
    assert c.value == TRUE and not c.has_predicates


@pytest.mark.parametrize("kw,expected", [
    ({"units": 7}, TRUE), ({"units": 2}, FALSE), ({}, UNKNOWN),
    ({"lo": 5, "hi": 9}, TRUE), ({"lo": 1, "hi": 2}, FALSE), ({"lo": 2, "hi": 9}, UNKNOWN),
    ({"lo": 5}, TRUE), ({"hi": 2}, FALSE), ({"hi": 9}, UNKNOWN),
])
def test_units_interval_logic(kw, expected):
    c = cov({"fact": "units", "op": ">=", "value": 3}, **kw)
    assert c.value == expected
    if expected == UNKNOWN:
        assert "units" in c.missing


@pytest.mark.parametrize("year,expected", [(1950, TRUE), (1990, FALSE), (1970, UNKNOWN), (None, UNKNOWN)])
def test_certificate_of_occupancy_from_year_built(year, expected):
    c = cov({"fact": "certificate_of_occupancy_date", "op": "<", "value": "1970-03-04"}, year=year)
    assert c.value == expected
    if expected == TRUE:
        assert coverage.DERIVED_CO in c.derived
    if expected == UNKNOWN:
        assert "certificate_of_occupancy_date" in c.missing


def test_kleene_and_or():
    known_false = {"fact": "units", "op": ">=", "value": 100}
    missing = {"fact": "year_built", "op": "<", "value": 1900}
    assert cov({"all": [known_false, missing]}, units=4).value == FALSE
    assert cov({"any": [known_false, missing]}, units=4).value == UNKNOWN
    assert cov({"not": known_false}, units=4).value == TRUE


def test_unavailable_exemption_presumed_absent_but_positive_condition_stays_unknown():
    exempt = {"all": [{"fact": "units", "op": ">=", "value": 2},
                      {"not": {"fact": "owner_occupied", "op": "==", "value": True}}]}
    c = cov(exempt, units=4)
    assert c.value == TRUE and c.presumed == ["owner_occupied"]
    positive = {"fact": "owner_type", "op": "==", "value": "natural_person"}
    c = cov(positive, units=4)
    assert c.value == UNKNOWN and c.missing == ["owner_type"]


ROLLING_EXEMPT = {"not": {"fact": "certificate_of_occupancy_date", "op": ">",
                          "value": {"years_before_query_date": 7}}}


@pytest.mark.parametrize("year,as_of,expected", [
    # query 2030-06-01 minus 7 years = 2023-06-01: built 2022 or earlier covered, 2024+ exempt
    (2022, "2030-06-01", TRUE), (2023, "2030-06-01", UNKNOWN), (2024, "2030-06-01", FALSE),
    (None, "2030-06-01", UNKNOWN),
    # rolling: the same building becomes covered on a later query date
    (2024, "2032-06-01", TRUE), (2024, None, UNKNOWN),
])
def test_rolling_certificate_of_occupancy_exemption(year, as_of, expected):
    c = coverage.evaluate(ROLLING_EXEMPT, parcel_facts(parcel(year=year)), as_of)
    assert c.value == expected
    if expected == TRUE:
        assert coverage.DERIVED_CO in c.derived
        assert any("rolling cutoff" in d for d in c.derived)
    if expected == UNKNOWN:
        assert "certificate_of_occupancy_date" in c.missing


def test_rolling_year_built_condition():
    newer = {"fact": "year_built", "op": ">", "value": {"years_before_query_date": 7}}
    ev = lambda y: coverage.evaluate(newer, parcel_facts(parcel(year=y)), "2030-06-01").value  # noqa: E731
    assert (ev(2024), ev(2023), ev(2020), ev(None)) == (TRUE, UNKNOWN, FALSE, UNKNOWN)


def test_years_before_handles_leap_day():
    assert coverage.years_before("2032-02-29", 3) == "2029-02-28"


def test_local_rent_control_status_is_never_presumed():
    only_controlled = {"fact": "subject_to_local_rent_control", "op": "==", "value": True}
    not_controlled = {"not": only_controlled}
    for pred in (only_controlled, not_controlled):
        c = cov(pred, units=4, year=1950)
        assert c.value == UNKNOWN and c.missing == ["subject_to_local_rent_control"]
    # stated building facts still decide when they are enough on their own
    either = {"any": [{"fact": "certificate_of_occupancy_date", "op": ">", "value": "1960-01-01"},
                      not_controlled]}
    assert cov(either, year=1990).value == TRUE
    assert cov(either, year=1950).value == UNKNOWN


def test_local_rent_control_derived_from_city_rent_rules():
    only_controlled = {"fact": "subject_to_local_rent_control", "op": "==", "value": True}
    outside = {"not": only_controlled}
    defining = rule("r-0001", level="city", jur=CITY,
                    pred={"fact": "certificate_of_occupancy_date", "op": "<=", "value": "1960-05-05"})
    annual = rule("r-0002", level="city", jur=CITY, pred=only_controlled)
    other_cat = rule("r-0003", level="city", jur=CITY, cat="just_cause_eviction", pred=outside)
    rules = [defining, annual, other_cat]
    res = lambda **kw: {r.team_rule_id: r.result for r in lookup.evaluate_address(parcel(**kw), rules, AS_OF)}  # noqa: E731
    assert res(year=1950, units=9) == {"r-0001": "applies", "r-0002": "applies"}
    assert res(year=1990, units=9) == {"r-0003": "applies"}
    assert res(year=1960, units=9) == {"r-0001": "unknown", "r-0002": "unknown", "r-0003": "unknown"}
    assert res(year=None, units=9) == {"r-0001": "unknown", "r-0002": "unknown", "r-0003": "unknown"}
    # no city rule states building conditions -> the status stays unknown
    assert {r.result for r in lookup.evaluate_address(parcel(year=1950), [annual], AS_OF)} == {"unknown"}
    # a rule conditioned only on facts the data lacks does not define rent control
    vague = rule("r-0004", level="city", jur=CITY, pred={"not": {"fact": "owner_occupied", "op": "==", "value": True}})
    assert {r.result for r in lookup.evaluate_address(parcel(year=1950), [vague, annual], AS_OF)
            if r.team_rule_id == "r-0002"} == {"unknown"}
    # unconfirmed legal city: never derived
    assert res(year=1990, units=9, conf="low")["r-0003"] == "unknown"


def test_lookup_passes_query_date_to_coverage():
    r = rule("r-0001", pred=ROLLING_EXEMPT)
    p = parcel(year=2024, units=10)
    assert lookup.evaluate_address(p, [r], "2030-06-01") == []
    assert [x.result for x in lookup.evaluate_address(p, [r], "2032-06-01")] == ["applies"]


def test_malformed_predicate_never_decides():
    assert cov({"fact": "zip", "op": "==", "value": "1"}).value == UNKNOWN


# ------------------------------------------------------------------ evaluate_address


def test_status_selection_and_omission():
    rules = [
        rule("r-0001"),
        rule("r-0002", hint="failed"),
        rule("r-0003", hint="bill_or_proposal", eff=None),
        rule("r-0004", eff="2031-01-01"),
        rule("r-0005", pred={"fact": "units", "op": ">=", "value": 50}),
        rule("r-0006", jur="YY"),
        rule("r-0007", level="city", jur="Elsewhere, ZZ"),
    ]
    rows = by_id(lookup.evaluate_address(parcel(units=4), rules, AS_OF))
    assert sorted(rows) == ["r-0001", "r-0003", "r-0004"]
    assert rows["r-0001"].result == "applies"
    assert rows["r-0003"].result == "pending"
    assert rows["r-0004"].result == "not_yet_effective"


def test_unknown_names_missing_fact():
    rules = [rule("r-0001", pred={"fact": "units", "op": ">=", "value": 3})]
    (row,) = lookup.evaluate_address(parcel(), rules, AS_OF)
    assert row.result == "unknown" and row.missing_facts == ["units"]
    assert "unit count" in row.explanation


def test_low_jurisdiction_confidence_makes_city_rules_unknown():
    rules = [rule("r-0001", level="city", jur=CITY)]
    (row,) = lookup.evaluate_address(parcel(conf="low"), rules, AS_OF)
    assert row.result == "unknown" and "legal city is not confirmed" in row.explanation
    (row,) = lookup.evaluate_address(parcel(conf="high"), rules, AS_OF)
    assert row.result == "applies"


def test_medium_jurisdiction_confidence_confirms_city_with_penalty():
    rules = [rule("r-0001", level="city", jur=CITY)]
    (high,) = lookup.evaluate_address(parcel(conf="high"), rules, AS_OF)
    (med,) = lookup.evaluate_address(parcel(conf="medium"), rules, AS_OF)
    assert med.result == "applies"
    assert med.confidence < high.confidence
    assert any("non-exact geocoder match" in r for r in med.confidence_reasons)


def test_no_predicate_rule_with_exemptions_lowers_confidence():
    plain = lookup.evaluate_address(parcel(), [rule("r-0001")], AS_OF)[0]
    ex = lookup.evaluate_address(parcel(), [rule("r-0001", exemptions="Some units are exempt.")], AS_OF)[0]
    assert plain.result == ex.result == "applies"
    assert ex.confidence < plain.confidence
    assert "exemptions" in ex.explanation


def test_superseded_when_state_text_defers_to_local():
    defer = "If the unit is subject to a local ordinance, the local ordinance shall apply instead."
    rules = [rule("r-0001", interaction=defer),
             rule("r-0002", level="city", jur=CITY, pred={"fact": "units", "op": ">=", "value": 2})]
    rows = by_id(lookup.evaluate_address(parcel(units=4), rules, AS_OF))
    assert rows["r-0001"].result == "superseded"
    assert rows["r-0001"].superseded_by == "r-0002"
    assert rows["r-0002"].result == "applies"
    # local rule does not cover the unit -> state rule applies
    rows = by_id(lookup.evaluate_address(parcel(units=1), rules, AS_OF))
    assert rows["r-0001"].result == "applies" and "r-0002" not in rows
    # local coverage unknown -> state rule unknown (may be superseded)
    rows = by_id(lookup.evaluate_address(parcel(), rules, AS_OF))
    assert rows["r-0001"].result == "unknown"


def test_unresolved_interaction_flags_conflict_on_both_rows():
    text = "No municipality may enact or enforce any ordinance on this subject."
    rules = [rule("r-0001", interaction=text), rule("r-0002", level="city", jur=CITY)]
    rows = by_id(lookup.evaluate_address(parcel(), rules, AS_OF))
    assert rows["r-0001"].conflict_flag and rows["r-0002"].conflict_flag
    assert rows["r-0001"].result == rows["r-0002"].result == "applies"
    assert any("unresolved interaction" in n for n in rows["r-0001"].not_checked)


def test_link_is_text_driven():
    defer = "If the unit is subject to a local ordinance, the local ordinance shall apply instead."
    rules = [rule("r-0001", interaction=defer), rule("r-0002", level="city", jur=CITY),
             rule("r-0003"), rule("r-0004", level="city", jur=CITY, cat="security_deposits")]
    out = precedence.link(rules, doc_jurisdictions={})
    assert out["r-0001"]["overrides"] == ["r-0002"] and "Yields to r-0002" in out["r-0001"]["interaction"]
    assert out["r-0002"]["overrides"] == ["r-0001"]
    assert out["r-0003"] == {"overrides": [], "interaction": None}
    assert out["r-0004"] == {"overrides": [], "interaction": None}


def test_explanations_cite_and_contain_only_allowed_numbers():
    rules = [rule("r-0001", pred={"all": [{"fact": "units", "op": ">=", "value": 3},
                                          {"fact": "year_built", "op": "<", "value": 1980}]},
                  cite="Test Code Part 9")]
    (row,) = lookup.evaluate_address(parcel(units=17, year=1955), rules, AS_OF)
    assert row.result == "applies" and "Test Code Part 9" in row.explanation
    assert "17" not in row.explanation and "1955" not in row.explanation
    assert explain_lookup.NUMBER.findall(row.explanation) == ["9"]


def test_outside_cities_lists_city_rules_not_checked():
    (row,) = lookup.evaluate_address(parcel(city=None, conf="low"), [rule("r-0001")], AS_OF)
    assert any("city rules" in n for n in row.not_checked)


def test_rows_sorted_and_deterministic():
    rules = [rule(f"r-000{i}") for i in (3, 1, 2)]
    a = lookup.evaluate_address(parcel(), rules, AS_OF)
    b = lookup.evaluate_address(parcel(), list(reversed(rules)), AS_OF)
    assert [r.team_rule_id for r in a] == ["r-0001", "r-0002", "r-0003"]
    assert [r.model_dump() for r in a] == [r.model_dump() for r in b]


# ------------------------------------------------------------------ loading


def test_missing_parcels_stops_with_message(tmp_path):
    with pytest.raises(lookup.EngineInputError) as e:
        lookup.load_parcels(tmp_path / "parcels.json")
    assert "geocode" in str(e.value)


def test_load_parcels_reads_contract_shape(tmp_path):
    p = tmp_path / "parcels.json"
    p.write_text(json.dumps({"parcels": [parcel()]}), encoding="utf-8")
    assert lookup.load_parcels(p)[0]["address_id"] == "A1"


def test_contradictory_unit_range_is_unknown():
    f = parcel_facts(parcel(lo=9, hi=2))
    assert f.units_min is None and f.units_max is None


def test_units_column_does_not_narrow_a_widened_range():
    # units column says 2, description says more: the range stays 2-93, so a ">= 3 units"
    # rule is unknown, never silently left out
    f = parcel_facts(parcel(units=2, lo=2, hi=93))
    assert (f.units_min, f.units_max) == (2, 93)
    assert cov({"fact": "units", "op": ">=", "value": 3}, units=2, lo=2, hi=93).value == UNKNOWN
