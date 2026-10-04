"""API (navigator/api): synthetic outputs in a temp dir, plus read-only checks on the real
outputs/ when present. No network, no LLM.

Rule ids, citations, places and dates in the synthetic set are made up; none is real law.
"""
from __future__ import annotations

import json
import warnings

import pytest

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    from fastapi.testclient import TestClient

from navigator import settings
from navigator.api.main import create_app
from navigator.api.service import numbers_grounded
from navigator.api.store import Store
from navigator.engine import lookup as engine
from navigator.schema.models import RuleInternal

pytestmark = pytest.mark.smoke

DEFAULT = settings.load()["default_as_of"]
DISCLAIMER = settings.load()["disclaimer"]
STATE, CITY = "ZZ", "Testville, ZZ"
HEADER = "SOURCE: https://example.test/doc\nRETRIEVED: 2026-10-01 22:00 UTC\n\n"
SPAN_A = "A landlord shall comply with the synthetic cap of 7 percent per year."
SPAN_B = "The synthetic deposit rule \U0001F600 limits deposits to 2 months of rent."
SPAN_F = "The synthetic ballot measure was struck from the ballot and did not pass."


def _doc(span: str) -> tuple[str, int, int]:
    text = HEADER + "Preamble line.\n" + "x" * 50 + "\U0001F600\n" + span + "\nTrailing line.\n"
    s = text.index(span)
    return text, s, s + len(span)


def _rule(rid, *, cat, span, doc, status="in_force", jur=STATE, level="state", eff="2020-01-01", hint="enacted"):
    text, s, e = _doc(span)
    return RuleInternal(
        team_rule_id=rid, jurisdiction=jur, level=level, category=cat, status=status,
        title=f"title {rid}", requirement="requirement text", effective_date=eff,
        citation=f"Synthetic Code {rid}", source_doc_id=doc, source_url=f"https://example.test/{doc}",
        quoted_span=span, confidence=0.9, span_start=s, span_end=e, span_match="exact",
        retrieved_at="2026-10-01T22:00Z",
        provenance=[{"candidate_id": f"{doc}-c001-r01", "chunk_id": f"{doc}-c001", "source_doc_id": doc,
                     "status_hint": hint}],
    )


RULES = [
    _rule("r-0001", cat="rent_increase_limits", span=SPAN_A, doc="SYN1"),
    _rule("r-0002", cat="security_deposits", span=SPAN_B, doc="SYN2", jur=CITY, level="city"),
    _rule("r-0003", cat="algorithmic_rent_setting", span=SPAN_A, doc="SYN1", eff="2027-01-01"),
    _rule("r-0004", cat="rent_increase_limits", span=SPAN_F, doc="SYN3", status="failed", eff=None,
          hint="failed"),
]
PARCELS = [
    {"address_id": "A0001", "street_address": "1 MAIN ST", "postal_city": "Testville", "state": STATE,
     "city": CITY, "lat": 40.0, "lng": -70.0, "jurisdiction_confidence": "high",
     "jurisdiction_source": "census_batch", "year_built": None, "units": None, "units_min": None,
     "units_max": None, "units_source": None, "use_description": "apartments",
     "missing_facts": ["year_built", "units"]},
    {"address_id": "A0002", "street_address": "2 OAK AVE", "postal_city": "Elsewhere", "state": STATE,
     "city": None, "lat": 41.0, "lng": -71.0, "jurisdiction_confidence": "high",
     "jurisdiction_source": "census_batch", "year_built": 1950, "units": 4, "units_min": 4, "units_max": 4,
     "units_source": "units", "use_description": "apartments", "missing_facts": []},
]


@pytest.fixture(autouse=True)
def _isolate_engine_cache():
    # engine.lookup caches precedence relations by id() of rule objects; ids of objects freed
    # here can be reused by later tests' rules, so never leave entries behind.
    engine._REL_CACHE.clear()
    yield
    engine._REL_CACHE.clear()


def _write(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture()
def synthetic(tmp_path):
    out, scores = tmp_path / "outputs", tmp_path / "scores"
    out.mkdir()
    scores.mkdir()
    _write(out / "rules_internal.json", {"as_of": DEFAULT, "rules": [r.model_dump(mode="json") for r in RULES]})
    _write(out / "parcels.json", {"parcels": PARCELS})
    rows = {p["address_id"]: [r.model_dump(mode="json") for r in engine.evaluate_address(p, RULES, DEFAULT)]
            for p in PARCELS}
    _write(out / "lookups_internal.json", {"as_of": DEFAULT, "lookups": rows})
    days = [DEFAULT, "2027-01-01"]
    tl, snaps = engine.build_timeline(PARCELS, RULES, days)
    _write(out / "timeline.json", {"dates": days, "timeline": tl})
    _write(out / "snapshots.json", {"dates": days, "snapshots": snaps})
    with (out / "docs.jsonl").open("w", encoding="utf-8") as fh:
        for doc, span in (("SYN1", SPAN_A), ("SYN2", SPAN_B), ("SYN3", SPAN_F)):
            fh.write(json.dumps({"doc_id": doc, "text": _doc(span)[0], "body_offset": len(HEADER)}) + "\n")
    with (out / "audit.jsonl").open("w", encoding="utf-8") as fh:
        for e in ({"stage": "ingest", "decision": "text", "doc_id": "SYN1"},
                  {"stage": "extract", "decision": "llm_call", "chunk_id": "SYN1-c001", "model": "m"},
                  {"stage": "verify", "decision": "accept", "team_rule_id": "r-0001",
                   "candidates": ["SYN1-c001-r01"]},
                  {"stage": "verify", "decision": "accept", "team_rule_id": "r-0001",
                   "candidates": ["OLD-c001-r01"]},     # stale id from an earlier verify run
                  {"stage": "ingest", "decision": "text", "doc_id": "SYN9"}):
            fh.write(json.dumps(e) + "\n")
    _write(out / "changes.json", {"T1": {"affected_address_ids": ["A0001"], "conflict_flag_address_ids": [],
                                         "notes": "n1"},
                                  "T2": {"affected_address_ids": [], "conflict_flag_address_ids": [],
                                         "notes": "n2"}})
    _write(out / "changes_internal.json", {"generated_at": "2026-10-04T00:00:00Z", "mapping_reviewed": False,
                                           "tests": {"T1": {"title": "t1", "type": "as_of",
                                                            "expected_behavior": "e1",
                                                            "checks": [{"name": "c", "passed": True,
                                                                        "detail": "1/1"}],
                                                            "notes": ["a", "b"]}}})
    (scores / "eval_latest.txt").write_text("Self-evaluation report\n", encoding="utf-8")
    store = Store(outputs_dir=out, scores_dir=scores)
    return TestClient(create_app(store)), out


def _envelope_ok(body):
    assert body["disclaimer"] == DISCLAIMER
    assert "as_of" in body and "generated_at" in body


# ------------------------------------------------------------------ synthetic


def test_health(synthetic):
    client, _ = synthetic
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    _envelope_ok(body)
    assert body["status"] == "ok" and body["rules"] == 4 and body["addresses"] == 2


def test_lookup_precomputed_shape(synthetic):
    client, _ = synthetic
    r = client.get("/lookup", params={"address_id": "A0001"})
    assert r.status_code == 200
    body = r.json()
    _envelope_ok(body)
    assert body["computed"] == "precomputed" and body["as_of"] == DEFAULT
    assert [c["category"] for c in body["categories"]] == [
        "rent_increase_limits", "just_cause_eviction", "security_deposits",
        "application_screening_fees", "screening_restrictions", "algorithmic_rent_setting"]
    rows = {row["team_rule_id"]: row for c in body["categories"] for row in c["rows"]}
    assert "r-0004" not in rows                           # failed rule never in lookups
    assert rows["r-0001"]["result"] == "applies"
    assert rows["r-0002"]["level"] == "city"
    assert rows["r-0003"]["result"] == "not_yet_effective"
    for row in rows.values():
        assert row["citation"] and row["source_url"] and row["retrieved_at"] and row["quoted_span"]
        assert row["answer"] is None                      # no summaries.json -> UI shows the quote
    empty = [c for c in body["categories"] if not c["rows"]]
    assert empty and all(c["no_rule_note"] for c in empty)
    assert [s["jurisdiction"] for s in body["jurisdiction_stack"]] == [STATE, CITY]
    assert [n["team_rule_id"] for n in body["notes"]] == ["r-0004"]   # failed rule as a note
    assert body["address"].startswith("1 MAIN ST, Testville, ZZ")


def test_lookup_owner_question(synthetic):
    client, _ = synthetic
    body = client.get("/lookup", params={"address_id": "A0001", "role": "owner"}).json()
    c = body["categories"][0]
    assert c["question"] == c["question_owner"] != c["question_tenant"]


def test_lookup_other_date_runs_engine(synthetic):
    client, _ = synthetic
    body = client.get("/lookup", params={"address_id": "A0001", "as_of": "2027-02-01"}).json()
    assert body["computed"] == "live" and body["as_of"] == "2027-02-01"
    rows = {row["team_rule_id"]: row for c in body["categories"] for row in c["rows"]}
    assert rows["r-0003"]["result"] == "applies" and rows["r-0003"]["status"] == "in_force"


@pytest.mark.parametrize("bad", ["2026-02-30", "2026-1-1", "tomorrow"])
def test_lookup_bad_date(synthetic, bad):
    client, _ = synthetic
    r = client.get("/lookup", params={"address_id": "A0001", "as_of": bad})
    assert r.status_code == 422 and r.json()["disclaimer"] == DISCLAIMER


def test_lookup_unknown_address(synthetic):
    client, _ = synthetic
    assert client.get("/lookup", params={"address_id": "A9999"}).status_code == 404


def test_summaries_used_and_number_guarded(synthetic):
    client, out = synthetic
    _write(out / "summaries.json", {"summaries": {
        "r-0001": {"answer_tenant": "Your rent can rise at most 7 percent a year.",
                   "answer_owner": "You must keep increases within 9 percent."}}})   # 9 not in span
    body = client.get("/lookup", params={"address_id": "A0001"}).json()
    row = next(r for c in body["categories"] for r in c["rows"] if r["team_rule_id"] == "r-0001")
    assert row["answer"] == "Your rent can rise at most 7 percent a year."
    body = client.get("/lookup", params={"address_id": "A0001", "role": "owner"}).json()
    row = next(r for c in body["categories"] for r in c["rows"] if r["team_rule_id"] == "r-0001")
    assert row["answer"] is None
    body = client.get("/lookup", params={"address_id": "A0001", "lang": "es"}).json()
    row = next(r for c in body["categories"] for r in c["rows"] if r["team_rule_id"] == "r-0001")
    assert row["answer"] is None                          # no Spanish text supplied


def test_numbers_grounded():
    assert numbers_grounded("up to 1.5 months", "no more than 1.5 months' rent")
    assert numbers_grounded("$1,000 cap", "a cap of $1000")
    assert not numbers_grounded("10 percent", "5 percent plus CPI")


def test_post_lookup_with_facts(synthetic):
    client, _ = synthetic
    r = client.post("/lookup", json={"address_id": "A0001", "facts": {"year_built": 1960, "units": 12}})
    assert r.status_code == 200
    body = r.json()
    assert body["computed"] == "live"
    assert body["user_facts"] == {"year_built": 1960, "units": 12}
    assert body["facts"]["year_built"] == 1960 and body["facts"]["units_source"] == "user_input"
    assert body["missing_facts"] == []
    assert body["jurisdiction_stack"][-1]["jurisdiction"] == CITY      # jurisdiction never changes


def test_post_lookup_by_coordinates(synthetic):
    client, _ = synthetic
    assert client.post("/lookup", json={"lat": 40.0, "lng": -70.0}).json()["address_id"] == "A0001"
    r = client.post("/lookup", json={"lat": 40.01, "lng": -70.0})       # ~1.1 km away
    assert r.status_code == 404
    assert client.post("/lookup", json={}).status_code == 422


@pytest.mark.parametrize("facts", [{"year_built": 1700}, {"units": 0}, {"units": 5000},
                                   {"units_min": 9, "units_max": 3}, {"year_built": 3000}])
def test_post_lookup_invalid_facts(synthetic, facts):
    client, _ = synthetic
    assert client.post("/lookup", json={"address_id": "A0001", "facts": facts}).status_code == 422


def test_resolve(synthetic):
    client, _ = synthetic
    body = client.get("/resolve", params={"lat": 40.0001, "lng": -70.0}).json()   # ~11 m
    assert body["nearest_address_id"] == "A0001" and body["city"] == CITY and body["state"] == STATE
    body = client.get("/resolve", params={"lat": 40.001, "lng": -70.0}).json()    # ~111 m
    assert body["nearest_address_id"] is None and body["state"] is None and body["city"] is None
    _envelope_ok(body)


def test_search(synthetic):
    client, _ = synthetic
    body = client.get("/search", params={"q": "main st"}).json()
    assert [h["address_id"] for h in body["results"]] == ["A0001"] and body["match"] == "text"
    assert client.get("/search", params={"q": "nowhere road"}).json()["results"] == []
    assert client.get("/search", params={"q": ""}).status_code == 422


def test_rule_detail_offsets(synthetic):
    client, _ = synthetic
    body = client.get("/rule/r-0002").json()
    _envelope_ok(body)
    tw = body["text_window"]
    assert body["highlight"] == "offsets" and tw["span_text_equals_quote"]
    o, u = tw["offsets"], tw["offsets_utf16"]
    assert tw["text"][o["span_start_in_window"]:o["span_end_in_window"]] == SPAN_B
    # an astral character before and inside the span: UTF-16 offsets drift by one each
    assert u["span_start"] == o["span_start"] + 1
    assert u["span_end"] == o["span_end"] + 2
    w16 = tw["text"].encode("utf-16-le")
    assert w16[2 * u["span_start_in_window"]:2 * u["span_end_in_window"]].decode("utf-16-le") == SPAN_B
    assert not tw["text"].startswith("SOURCE:")          # header is not part of the window
    assert body["retrieved_at"] and body["source_url"]
    assert client.get("/rule/r-9999").status_code == 404


def test_rule_without_offsets_falls_back_to_substring(synthetic):
    client, out = synthetic
    data = json.loads((out / "rules_internal.json").read_text(encoding="utf-8"))
    data["rules"][0]["span_start"] = data["rules"][0]["span_end"] = None
    _write(out / "rules_internal.json", data)
    body = client.get("/rule/r-0001").json()
    assert body["text_window"] is None and body["highlight"] == "substring" and body["note"]


def test_timeline_snapshots(synthetic):
    client, _ = synthetic
    body = client.get("/timeline", params={"address_id": "A0001"}).json()
    assert body["dates"] == [DEFAULT, "2027-01-01"]
    assert any(ch["team_rule_id"] == "r-0003" and ch["from"] == "not_yet_effective"
               for e in body["timeline"] for ch in e["changes"])
    snaps = client.get("/snapshots").json()
    _envelope_ok(snaps)
    assert snaps["snapshots"]["2027-01-01"]["A0001"]["algorithmic_rent_setting"]["result"] == "applies"
    one = client.get(f"/snapshots/{DEFAULT}").json()
    assert one["snapshot"]["A0001"]["algorithmic_rent_setting"]["result"] == "not_yet_effective"
    assert client.get("/snapshots/1999-01-01").status_code == 404


def test_changes(synthetic):
    client, _ = synthetic
    body = client.get("/changes").json()
    _envelope_ok(body)
    assert [t["test_id"] for t in body["tests"]] == ["T1", "T2"]
    t1 = client.get("/changes/T1").json()["test"]
    assert t1["affected_count"] == 1 and t1["checks"][0]["passed"] is True and t1["notes_list"] == ["a", "b"]
    assert client.get("/changes/T2").json()["test"]["conflict_flag_address_ids"] == []
    assert client.get("/changes/T9").status_code == 404


def test_audit_filters_stale_ids(synthetic):
    client, _ = synthetic
    body = client.get("/audit", params={"team_rule_id": "r-0001"}).json()
    stages = [(e["stage"], e.get("candidates"), e.get("doc_id")) for e in body["entries"]]
    assert ("verify", ["SYN1-c001-r01"], None) in stages
    assert all(c != ["OLD-c001-r01"] for _, c, _ in stages)
    assert all(d != "SYN9" for _, _, d in stages)
    assert len(body["entries"]) == 3


def test_eval(synthetic):
    client, _ = synthetic
    assert client.get("/eval").json()["report"].startswith("Self-evaluation")


GOOD_DOC = "SOURCE: https://example.invalid/law\nRETRIEVED: 2030-01-01 00:00 UTC\n\nA synthetic test body long enough.\n"


def test_ingest_rejects_bad_header_before_writing(synthetic, monkeypatch):
    client, _ = synthetic
    from navigator.ingest import incremental

    monkeypatch.setattr(incremental, "run", lambda *a, **k: pytest.fail("run must not start"))
    r = client.post("/ingest", json={"text": "no header here at all, just text"})
    assert r.status_code == 400 and "validate" in r.json()["detail"]
    assert client.post("/ingest", json={}).status_code == 422


def test_ingest_streams_progress_and_summary(synthetic, monkeypatch):
    client, _ = synthetic
    from navigator.ingest import incremental

    def fake_run(path, live=False, progress=None, jurisdiction=None, doc_id=None):
        assert live is True and jurisdiction == "ZZ"
        for step in ("validate", "register"):
            progress({"step": step, "status": "done"})
        return {"doc_id": "S001", "rules_new": ["r-9"]}

    monkeypatch.setattr(incremental, "run", fake_run)
    r = client.post("/ingest", json={"text": GOOD_DOC, "jurisdiction": "ZZ", "live": True})
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/x-ndjson")
    lines = [json.loads(x) for x in r.text.splitlines()]
    assert [x.get("step") for x in lines[:2]] == ["validate", "register"]
    assert lines[-1]["status"] == "finished" and lines[-1]["summary"]["doc_id"] == "S001"
    assert all(x["disclaimer"] == "Not legal advice." for x in lines)


def test_ingest_reports_step_failure(synthetic, monkeypatch):
    client, _ = synthetic
    from navigator.ingest import incremental

    def failing(*a, **k):
        raise incremental.IngestError("register", "jurisdiction required")

    monkeypatch.setattr(incremental, "run", failing)
    last = json.loads(client.post("/ingest", json={"text": GOOD_DOC}).text.splitlines()[-1])
    assert (last["status"], last["step"], last["http_status"]) == ("failed", "register", 400)


def test_ingest_one_at_a_time_and_can_be_disabled(synthetic, monkeypatch):
    client, _ = synthetic
    from navigator.api import main

    assert main._INGEST_LOCK.acquire(blocking=False)
    try:
        assert client.post("/ingest", json={"text": GOOD_DOC}).status_code == 409
    finally:
        main._INGEST_LOCK.release()
    monkeypatch.setenv("NAVIGATOR_DISABLE_INGEST", "1")
    assert client.post("/ingest", json={"text": GOOD_DOC}).status_code == 403


def test_missing_files_fail_closed(synthetic):
    client, out = synthetic
    (out / "lookups_internal.json").unlink()
    r = client.get("/lookup", params={"address_id": "A0001"})
    assert r.status_code == 503 and "lookups_internal.json" in r.json()["detail"]
    assert client.get("/health").json()["status"] == "degraded"
    (out / "rules_internal.json").unlink()
    assert client.get("/rule/r-0001").status_code == 503
    (out / "changes.json").unlink()
    assert client.get("/changes").status_code == 503


def test_stub_outputs_fail_closed(synthetic):
    client, out = synthetic
    (out / "STUB").write_text("", encoding="utf-8")
    assert client.get("/lookup", params={"address_id": "A0001"}).status_code == 503
    assert client.post("/lookup", json={"address_id": "A0001"}).status_code == 503
    assert client.get("/health").json()["stub_outputs"] is True


def test_out_of_sync_rule_fails_closed(synthetic):
    client, out = synthetic
    data = json.loads((out / "rules_internal.json").read_text(encoding="utf-8"))
    data["rules"] = [r for r in data["rules"] if r["team_rule_id"] != "r-0001"]
    _write(out / "rules_internal.json", data)
    assert client.get("/lookup", params={"address_id": "A0001"}).status_code == 503


def test_cors_localhost(synthetic):
    client, _ = synthetic
    r = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"
    r = client.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers


def test_openapi_has_lookup_model(synthetic):
    client, _ = synthetic
    spec = client.get("/openapi.json").json()
    assert "LookupResult" in spec["components"]["schemas"]
    assert "LookupRowOut" in spec["components"]["schemas"]


# ------------------------------------------------------------------ real outputs (read-only)

_REAL = all((settings.path("outputs") / n).is_file()
            for n in ("rules_internal.json", "parcels.json", "lookups_internal.json")) \
    and not (settings.path("outputs") / "STUB").is_file()


@pytest.fixture(scope="module")
def real():
    if not _REAL:
        pytest.skip("real outputs not built")
    return TestClient(create_app(Store()))


def test_real_lookup_all_rows_cited(real):
    body = real.get("/lookup", params={"address_id": "A0001"}).json()
    assert body["computed"] == "precomputed"
    rows = [r for c in body["categories"] for r in c["rows"]]
    assert rows
    for r in rows:
        assert len(r["quoted_span"]) >= 20 and r["citation"] and r["source_url"] and r["retrieved_at"]


def test_real_live_matches_precomputed(real):
    store = Store()
    pre = store.lookups()["lookups"]
    rules = store.rules()
    parcels = store.parcels()
    if store.lookups()["as_of"] != DEFAULT:
        pytest.skip("precomputed lookups are for another date")
    for aid in list(parcels)[::50]:
        live = [r.model_dump(mode="json") for r in engine.evaluate_address(parcels[aid], rules, DEFAULT)]
        assert live == pre[aid], aid


def test_real_rule_highlight(real):
    store = Store()
    for rule in store.rules()[:40]:
        body = real.get(f"/rule/{rule.team_rule_id}").json()
        if body["text_window"] is None:
            continue
        tw = body["text_window"]
        o = tw["offsets"]
        assert tw["text"][o["span_start_in_window"]:o["span_end_in_window"]] == tw["span_text"]
