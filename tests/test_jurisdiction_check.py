"""eval/jurisdiction_check.py on synthetic parcels, rules and lookups (made-up places, no law)."""
from __future__ import annotations

import json

import pytest

from eval import jurisdiction_check as jc
from eval.run_eval import Report

pytestmark = pytest.mark.smoke

MANIFEST = {"ZZ", "YY", "Alpha, ZZ", "Beta, ZZ", "Gamma, YY"}
COUSUB = {"9900001": {"jurisdiction": "Alpha, ZZ"}, "9900002": {"jurisdiction": "Beta, ZZ"}}


def parcel(aid, state, city, postal, cousub=None, review=True, reasons=None):
    return {"address_id": aid, "state": state, "city": city, "postal_city": postal,
            "geoids": {"county_subdivision": cousub}, "jurisdiction_confidence": "high" if city else "low",
            "jurisdiction_source": "synthetic", "needs_review": review,
            "review_reasons": reasons or []}


PARCELS = [
    parcel("X1", "ZZ", "Alpha, ZZ", "Alpha", "9900001", review=False),
    parcel("X2", "ZZ", "Alpha, ZZ", "Northside", "9900001", review=False),   # neighborhood postal
    parcel("X3", "ZZ", None, "Nowhere", None, reasons=["not geocoded"]),
    parcel("X4", "YY", "Gamma, YY", "gamma", None, review=False),
]
CSV = [{"address_id": p["address_id"], "state": p["state"]} for p in PARCELS]
RULES = [{"team_rule_id": "r-1", "jurisdiction": "ZZ", "level": "state"},
         {"team_rule_id": "r-2", "jurisdiction": "Alpha, ZZ", "level": "city"},
         {"team_rule_id": "r-3", "jurisdiction": "YY", "level": "state"},
         {"team_rule_id": "r-4", "jurisdiction": "Beta, ZZ", "level": "city"}]
LOOKUPS = {"X1": [{"team_rule_id": "r-1"}, {"team_rule_id": "r-2"}], "X2": [{"team_rule_id": "r-2"}],
           "X3": [{"team_rule_id": "r-1"}], "X4": [{"team_rule_id": "r-3"}]}


def run(parcels=PARCELS, csv_rows=CSV, lookups=LOOKUPS, rules=RULES, cousub=COUSUB):
    return jc.analyze(parcels, csv_rows, MANIFEST, cousub, {"ZZ"}, lookups, rules)


def test_clean_synthetic_data_passes():
    res = run()
    assert res["by_state"] == {"YY": 1, "ZZ": 3}
    assert res["by_city"]["(no legal city)"] == 1
    assert res["state_match"] == {"num": 4, "den": 4, "mismatched": [], "extra_parcels": []}
    assert res["legal_ne_postal"]["num"] == 1 and res["legal_ne_postal"]["den"] == 3
    assert res["legal_ne_postal"]["groups"] == {"Northside -> Alpha, ZZ": ["X2"]}   # "gamma" matches case-insensitively
    assert [n["address_id"] for n in res["no_city"]] == ["X3"]
    assert res["no_city"][0]["reasons"] == ["not geocoded"]
    assert res["cousub"]["num"] == 2 and res["cousub"]["den"] == 2 and res["cousub"]["no_geoid"] == 1
    assert res["lookup_sanity"]["violations"] == []
    assert res["city_outside_manifest"] == [] and res["unflagged_without_city"] == []


def test_state_mismatch_and_missing_parcel_are_counted():
    csv_rows = CSV + [{"address_id": "X5", "state": "ZZ"}]
    csv_rows[0] = {"address_id": "X1", "state": "YY"}
    res = run(csv_rows=csv_rows)
    assert res["state_match"]["num"] == 3 and res["state_match"]["den"] == 5
    assert any("X5" in m for m in res["state_match"]["mismatched"])


def test_lookup_rows_from_other_jurisdictions_are_violations():
    lookups = {**LOOKUPS, "X1": [{"team_rule_id": "r-4"}],          # other city
               "X4": [{"team_rule_id": "r-1"}],                       # other state
               "X3": [{"team_rule_id": "r-2"}, {"team_rule_id": "r-9"}]}  # no legal city; unknown rule
    v = run(lookups=lookups)["lookup_sanity"]["violations"]
    assert len(v) == 4
    assert any("r-4" in x for x in v) and any("r-9" in x for x in v)


def test_cousub_disagreement_and_city_outside_manifest():
    parcels = [parcel("X1", "ZZ", "Alpha, ZZ", "Alpha", "9900002", review=False),
               parcel("X2", "ZZ", "Delta, ZZ", "Delta", None, review=False),
               parcel("X3", "ZZ", None, "Nowhere", None, review=False)]
    res = run(parcels=parcels, csv_rows=[{"address_id": p["address_id"], "state": "ZZ"} for p in parcels])
    assert res["cousub"]["num"] == 0 and res["cousub"]["den"] == 1
    assert res["city_outside_manifest"] == ["X2"]
    assert res["unflagged_without_city"] == ["X3"]


def _write(out, parcels=PARCELS, lookups=LOOKUPS):
    (out / "parcels.json").write_text(json.dumps({"parcels": parcels}), encoding="utf-8")
    (out / "lookups_internal.json").write_text(json.dumps({"as_of": "2030-01-01", "lookups": lookups}),
                                               encoding="utf-8")
    (out / "rules_internal.json").write_text(json.dumps({"rules": RULES}), encoding="utf-8")


def _section(monkeypatch, tmp_path):
    monkeypatch.setattr(jc, "load", lambda out_dir: jc.analyze(
        json.loads((out_dir / "parcels.json").read_text())["parcels"], CSV, MANIFEST, COUSUB, {"ZZ"},
        json.loads((out_dir / "lookups_internal.json").read_text())["lookups"], RULES))
    rep = Report()
    jc.section(rep, tmp_path)
    return rep


def test_section_reports_and_stores_metrics(monkeypatch, tmp_path):
    _write(tmp_path)
    rep = _section(monkeypatch, tmp_path)
    assert not rep.hard_fail
    assert rep.lines[0].startswith("[7] Jurisdiction check")
    m = rep.metrics["jurisdiction"]
    assert set(rep.metrics) == {"jurisdiction"}            # everything under one key
    assert m["checks"]["jur_state_match"] == {"num": 4, "den": 4}
    assert m["checks"]["jur_lookup_sanity"] is True
    assert m["no_city"] == ["X3"]


def test_section_lookup_violation_is_hard(monkeypatch, tmp_path):
    _write(tmp_path, lookups={**LOOKUPS, "X1": [{"team_rule_id": "r-4"}]})
    rep = _section(monkeypatch, tmp_path)
    assert rep.hard_fail
    assert rep.metrics["jurisdiction"]["lookup_violations"] == 1


def test_section_without_parcels_is_not_measured(tmp_path):
    rep = Report()
    jc.section(rep, tmp_path)
    assert not rep.hard_fail and rep.metrics["jurisdiction"] is None
    assert "parcels.json missing" in rep.lines[1]
