"""Submission formats: our models vs the official schema/templates, and writer refusals.

No law text is typed here: test rules carry a placeholder citation and a quoted span
read from a real corpus file at test time.
"""
import json

import jsonschema
import pytest
from pydantic import ValidationError

from eval import run_eval
from navigator import settings, starter
from navigator.schema.models import (
    ChangeResult,
    LookupRow,
    LookupRowInternal,
    LookupsFile,
    RuleInternal,
    RuleRecord,
    RulesFile,
)
from navigator.schema.writers import OutputError, write_changes, write_lookups, write_rules

STARTER = settings.path("starter")
DOC = "D024"  # any document with text works; this one is short and official


def _span(doc_id=DOC, length=80):
    body = starter.doc_text(doc_id).split("\n", 3)[3]
    line = next(l for l in body.splitlines() if len(l.strip()) >= length)
    return line.strip()[:length]


def _rule(rid="r-0001", **kw):
    row = starter.manifest()[DOC]
    base = dict(
        team_rule_id=rid, jurisdiction="CA", level="state", category="rent_increase_limits",
        status="in_force", title="test rule", requirement="test requirement.",
        citation="TEST-CITATION", source_doc_id=DOC, source_url=row["url"], quoted_span=_span(),
    )
    base.update(kw)
    return RuleInternal(**base)


# ------------------------------------------------------------ schema parity


def test_rule_record_fields_match_official_schema():
    schema = starter.rule_schema()
    assert set(RuleRecord.model_fields) == set(schema["properties"])
    required = {n for n, f in RuleRecord.model_fields.items() if f.is_required()}
    assert required == set(schema["required"])


@pytest.mark.parametrize("field", ["level", "category", "status"])
def test_enums_match_official_schema(field):
    official = set(starter.rule_schema()["properties"][field]["enum"])
    ours = set(RuleRecord.model_fields[field].annotation.__args__)
    assert ours == official


def test_sample_record_and_templates_validate():
    sample = json.loads((STARTER / "schema/sample_rule_record.json").read_text(encoding="utf-8"))
    jsonschema.validate(sample, starter.rule_schema())
    RuleRecord.model_validate(sample)
    RulesFile.model_validate(json.loads((STARTER / "submission_templates/rules.json").read_text(encoding="utf-8")))
    LookupsFile.model_validate(json.loads((STARTER / "submission_templates/lookups.json").read_text(encoding="utf-8")))
    changes = json.loads((STARTER / "submission_templates/changes.json").read_text(encoding="utf-8"))
    ChangeResult.model_validate(changes["T3"])
    # Intentionally stricter than the template: CONTRACT.md 4 requires conflict ids on every test.
    with pytest.raises(ValidationError):
        ChangeResult.model_validate(changes["T1"])


def test_short_span_and_bad_enum_rejected():
    with pytest.raises(ValidationError):
        _rule(quoted_span="too short")
    with pytest.raises(ValidationError):
        _rule(level="county")
    with pytest.raises(ValidationError):
        _rule(effective_date="10/01/2026")


def test_internal_fields_are_stripped():
    rec = _rule(span_start=1, span_end=2, needs_review=True, review_reasons=["x"], penalty="p").to_record()
    assert set(rec.model_dump()) == set(starter.rule_schema()["properties"])
    row = LookupRowInternal(team_rule_id="r-1", result="unknown", explanation="e",
                            missing_facts=["year_built"]).to_row()
    assert set(row.model_dump()) == {"team_rule_id", "result", "explanation", "conflict_flag"}


# ------------------------------------------------------------ rules writer


def test_write_rules_ok(tmp_path):
    path = write_rules([_rule("r-0002"), _rule("r-0001", overrides=["r-0002"])], out_dir=tmp_path)
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert list(doc) == ["rules"]
    assert [r["team_rule_id"] for r in doc["rules"]] == ["r-0001", "r-0002"]
    for r in doc["rules"]:
        jsonschema.validate(r, starter.rule_schema())
        assert "span_start" not in r


@pytest.mark.smoke
@pytest.mark.parametrize("rules, needle", [
    (lambda: [_rule(), _rule()], "duplicate"),
    (lambda: [_rule(source_url="https://example.org")], "source_url differs"),
    (lambda: [_rule(overrides=["r-9999"])], "unknown rule"),
    (lambda: [_rule(source_doc_id="D999")], "not in manifest"),
])
def test_write_rules_refuses(tmp_path, rules, needle):
    with pytest.raises(OutputError, match=needle):
        write_rules(rules(), out_dir=tmp_path)
    assert not (tmp_path / "rules.json").exists()


# ---------------------------------------------------------- lookups writer


def _all_empty():
    return {aid: [] for aid in starter.address_ids()}


def test_write_lookups_ok(tmp_path):
    rules = [_rule()]
    lk = _all_empty()
    lk["A0001"] = [LookupRowInternal(team_rule_id="r-0001", result="unknown", explanation="needs year built",
                                     missing_facts=["year_built"])]
    doc = json.loads(write_lookups("2026-10-01", lk, rules, out_dir=tmp_path).read_text(encoding="utf-8"))
    assert doc["as_of"] == "2026-10-01"
    assert list(doc["lookups"]) == starter.address_ids()
    assert doc["lookups"]["A0001"] == [{"team_rule_id": "r-0001", "result": "unknown",
                                        "explanation": "needs year built", "conflict_flag": False}]


@pytest.mark.smoke
def test_write_lookups_refuses_missing_address(tmp_path):
    lk = _all_empty()
    del lk["A0500"]
    with pytest.raises(OutputError, match="missing"):
        write_lookups("2026-10-01", lk, [], out_dir=tmp_path)


@pytest.mark.smoke
@pytest.mark.parametrize("status, result, needle", [
    ("failed", "applies", "failed rule"),
    ("pending", "applies", "pending rule"),
])
def test_write_lookups_refuses_status_mixing(tmp_path, status, result, needle):
    lk = _all_empty()
    lk["A0001"] = [LookupRow(team_rule_id="r-0001", result=result, explanation="x")]
    with pytest.raises(OutputError, match=needle):
        write_lookups("2026-10-01", lk, [_rule(status=status)], out_dir=tmp_path)


@pytest.mark.smoke
def test_write_lookups_refuses_unknown_rule(tmp_path):
    lk = _all_empty()
    lk["A0001"] = [LookupRow(team_rule_id="r-0404", result="applies", explanation="x")]
    with pytest.raises(OutputError, match="not in rules.json"):
        write_lookups("2026-10-01", lk, [], out_dir=tmp_path)


# ---------------------------------------------------------- changes writer


def _changes(**over):
    base = {t: ChangeResult(affected_address_ids=[], conflict_flag_address_ids=[], notes="n")
            for t in starter.change_test_ids()}
    base.update(over)
    return base


def test_write_changes_ok(tmp_path):
    ch = _changes(T3=ChangeResult(affected_address_ids=["A0300", "A0251", "A0251"],
                                  conflict_flag_address_ids=["A0251"], notes="n"))
    with pytest.raises(OutputError, match="duplicate"):
        write_changes(ch, out_dir=tmp_path)
    ch["T3"].affected_address_ids = ["A0300", "A0251"]
    doc = json.loads(write_changes(ch, out_dir=tmp_path).read_text(encoding="utf-8"))
    assert list(doc) == starter.change_test_ids()
    assert doc["T3"]["affected_address_ids"] == ["A0251", "A0300"]
    assert all(set(v) == {"affected_address_ids", "conflict_flag_address_ids", "notes"} for v in doc.values())


@pytest.mark.smoke
def test_write_changes_refuses(tmp_path):
    ch = _changes()
    del ch["T5"]
    with pytest.raises(OutputError, match="missing tests"):
        write_changes(ch, out_dir=tmp_path)
    with pytest.raises(OutputError, match="unknown ids"):
        write_changes(_changes(T1=ChangeResult(affected_address_ids=["Z9"], conflict_flag_address_ids=[], notes="n")),
                      out_dir=tmp_path)


# ------------------------------------------------------------- eval harness


def _write_valid_set(out, rules):
    write_rules(rules, out_dir=out)
    write_lookups("2026-10-01", _all_empty(), rules, out_dir=out)
    write_changes(_changes(), out_dir=out)


def test_eval_passes_on_valid_outputs_and_flags_stub(tmp_path, capsys):
    out, scores = tmp_path / "out", tmp_path / "scores"
    _write_valid_set(out, [_rule()])
    (out / "STUB").write_text("stub", encoding="utf-8")
    rep = run_eval.run(out_dir=out, scores_dir=scores)
    assert not rep.hard_fail
    text = (scores / "eval_latest.txt").read_text(encoding="utf-8")
    assert text.startswith("*** STUB OUTPUTS")
    assert rep.metrics["grounding_span_found"] == {"num": 1, "den": 1}
    assert len((scores / "history.jsonl").read_text(encoding="utf-8").splitlines()) == 1


@pytest.mark.smoke
def test_eval_fails_on_ungrounded_span(tmp_path):
    out = tmp_path / "out"
    fake = _rule(quoted_span="this sentence does not appear in any corpus document at all")
    _write_valid_set(out, [fake])
    rep = run_eval.evaluate(out)
    assert rep.hard_fail
    assert rep.metrics["grounding_span_found"] == {"num": 0, "den": 1}


@pytest.mark.smoke
def test_eval_fails_when_files_missing(tmp_path):
    assert run_eval.evaluate(tmp_path).hard_fail
