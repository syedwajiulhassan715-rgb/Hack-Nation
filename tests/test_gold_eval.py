"""Gold-set evaluation (eval/gold_eval.py): matching and scoring on synthetic data, plus a
schema check of the real draft gold files."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from eval import gold_eval as ge
from eval.run_eval import Report

pytestmark = pytest.mark.smoke

BODY = ge.norm(
    "Section 1. A landlord shall not   charge more than one month’s rent as a security deposit. "
    + "x " * 200 + "Unrelated filler text in the middle. " + "x " * 200 +
    "Section 2. It shall be unlawful to use a pricing algorithm to set rents. "
    "Section 2. It shall be unlawful to use a pricing algorithm to set rents."
)


def body_of(did: str) -> str | None:
    return {"D1": BODY, "D2": ge.norm("An Act prohibiting algorithmic rent setting, title only.")}.get(did)


def gold(gid: str, anchor: str, doc: str = "D1", **kw) -> dict:
    g = {"id": gid, "source_doc_id": doc, "jurisdiction": "CA", "level": "state",
         "category": "security_deposits", "status": "in_force", "effective_date": None,
         "anchor_quote": anchor, "basis": "test"}
    g.update(kw)
    return g


def ours(rid: str, span: str, doc: str = "D1", **kw) -> dict:
    r = {"team_rule_id": rid, "source_doc_id": doc, "jurisdiction": "CA", "level": "state",
         "category": "security_deposits", "status": "in_force", "effective_date": None,
         "quoted_span": span, "key_value": None, "requirement": ""}
    r.update(kw)
    return r


# ------------------------------------------------------------------ text helpers
def test_norm_folds_quotes_dashes_and_whitespace():
    assert ge.norm("one  month’s\n rent – “x”") == "one month's rent - \"x\""


def test_locate_is_whitespace_insensitive_and_finds_all_occurrences():
    assert ge.locate("shall not\ncharge more", BODY) is not None
    assert len(ge.locate_all("It shall be unlawful to use a pricing algorithm", BODY)) == 2
    assert ge.locate("text that is not there at all", BODY) is None


def test_doc_body_strips_header():
    raw = "SOURCE: u\nRETRIEVED: t\n\nBody  text here"
    assert ge.doc_body(raw) == "Body text here"


# ------------------------------------------------------------------ rule matching
def test_match_by_overlap_ignores_team_rule_id():
    g = [gold("g1", "charge more than one month's rent")]
    o = [ours("r-0999", "A landlord shall not charge more than one month’s rent as a security deposit.")]
    m, problems = ge.match_rules(g, o, body_of)
    assert m["g1"]["team_rule_id"] == "r-0999" and problems == []


def test_neighbouring_sentence_within_gap_matches_far_one_does_not():
    g = [gold("near", "Section 1. A landlord shall not"),
         gold("far", "It shall be unlawful to use a pricing algorithm", category="algorithmic_rent_setting")]
    o = [ours("r-1", "as a security deposit.")]  # right after the anchor, no overlap
    m, _ = ge.match_rules(g, o, body_of)
    assert m["near"] is not None
    assert m["far"] is None  # > MATCH_GAP away


def test_other_document_never_matches():
    g = [gold("g1", "charge more than one month's rent")]
    o = [ours("r-1", "charge more than one month's rent", doc="D9")]
    m, _ = ge.match_rules(g, o, body_of)
    assert m["g1"] is None


def test_best_overlap_wins_then_category_breaks_ties():
    g = [gold("g1", "It shall be unlawful to use a pricing algorithm to set rents.",
              category="algorithmic_rent_setting")]
    o = [ours("r-a", "It shall be unlawful to use", category="security_deposits"),
         ours("r-b", "It shall be unlawful to use a pricing algorithm to set rents.", category="security_deposits"),
         ours("r-c", "It shall be unlawful to use a pricing algorithm to set rents.", category="algorithmic_rent_setting")]
    m, _ = ge.match_rules(g, o, body_of)
    assert m["g1"]["team_rule_id"] == "r-c"


def test_also_match_and_missing_anchor_reported():
    g = [gold("g1", "this anchor is not in the document", doc="D1",
              also_match=[{"source_doc_id": "D2", "anchor_quote": "An Act prohibiting algorithmic rent setting"}])]
    o = [ours("r-1", "An Act prohibiting algorithmic rent setting", doc="D2")]
    m, problems = ge.match_rules(g, o, body_of)
    assert m["g1"]["team_rule_id"] == "r-1"
    assert problems == ["g1: anchor not found in D1"]


def test_field_ok_uses_also_ok():
    g = gold("g1", "x" * 20, status="pending", effective_date="2026-01-01",
             also_ok={"status": ["in_force"], "effective_date": [None]})
    assert ge.field_ok("status", g, {"status": "in_force"})
    assert not ge.field_ok("status", g, {"status": "failed"})
    assert ge.field_ok("effective_date", g, {"effective_date": None})
    assert ge.field_ok("effective_date", g, {"effective_date": "2026-01-01"})
    assert not ge.field_ok("effective_date", g, {"effective_date": "2026-01-02"})


# ------------------------------------------------------------------ scoring
@pytest.mark.parametrize("expected,got,also,cls", [
    ("applies", "applies", None, "correct"),
    ("absent", "pending", ["pending"], "correct"),
    ("applies", "unknown", None, "over_cautious"),
    ("superseded", "absent", None, "missed"),
    ("unknown", "absent", None, "missed"),
    ("absent", "applies", None, "wrong"),
    ("unknown", "applies", None, "wrong"),
])
def test_classify_result(expected, got, also, cls):
    assert ge.classify_result(expected, got, also) == cls


def test_classify_city():
    assert ge.classify_city("Boston, MA", "Boston, MA") == "correct"
    assert ge.classify_city("Boston, MA", None) == "unresolved"
    assert ge.classify_city("Boston, MA", "Cambridge, MA") == "wrong"
    assert ge.classify_city("uncertain", "Cambridge, MA") == "skipped"
    assert ge.classify_city("none", None) == "correct"


# ------------------------------------------------------------------ section end to end
def _write(tmp: Path, reviewed_by=None) -> tuple[Path, Path]:
    gold_dir, out_dir = tmp / "gold", tmp / "out"
    gold_dir.mkdir()
    out_dir.mkdir()
    rules = {"status": "draft", "reviewed_by": reviewed_by, "rules": [
        gold("g-dep", "charge more than one month's rent", key_value="1 month"),
        gold("g-alg", "It shall be unlawful to use a pricing algorithm", category="algorithmic_rent_setting",
             effective_date="2026-01-01"),
        gold("g-none", "Unrelated filler text", category="screening_restrictions"),
    ]}
    addrs = {"status": "draft", "reviewed_by": reviewed_by, "addresses": [
        {"address_id": "A1", "state": "CA", "legal_city": "Los Angeles, CA", "results": [
            {"rule": "g-dep", "expected": "applies", "reason": "r"},
            {"rule": "g-alg", "expected": "applies", "reason": "r"},
            {"rule": "g-none", "expected": "applies", "reason": "r"}]},
        {"address_id": "A2", "state": "CA", "legal_city": "uncertain", "results": [
            {"rule": "g-dep", "expected": "unknown", "reason": "r"}]},
    ]}
    (gold_dir / "rules.yaml").write_text(yaml.safe_dump(rules), encoding="utf-8")
    (gold_dir / "addresses.yaml").write_text(yaml.safe_dump(addrs), encoding="utf-8")
    our_rules = [ours("r-1", "A landlord shall not charge more than one month’s rent", requirement="1 month"),
                 ours("r-2", "It shall be unlawful to use a pricing algorithm to set rents.",
                      category="algorithmic_rent_setting", effective_date="2025-01-01")]
    (out_dir / "rules_internal.json").write_text(json.dumps({"rules": our_rules}), encoding="utf-8")
    (out_dir / "parcels.json").write_text(json.dumps({"parcels": [
        {"address_id": "A1", "state": "CA", "city": None},
        {"address_id": "A2", "state": "CA", "city": "Berkeley, CA"}]}), encoding="utf-8")
    (out_dir / "lookups.json").write_text(json.dumps({"as_of": "2026-10-01", "lookups": {
        "A1": [{"team_rule_id": "r-1", "result": "applies", "explanation": "", "conflict_flag": False}],
        "A2": [{"team_rule_id": "r-1", "result": "applies", "explanation": "", "conflict_flag": False}]}}),
        encoding="utf-8")
    return gold_dir, out_dir


def test_section_scores_and_never_hard_fails(tmp_path):
    gold_dir, out_dir = _write(tmp_path)
    rep = Report()
    ge.section(rep, out_dir, gold_dir=gold_dir, body_of=body_of)
    g = rep.metrics["gold"]
    assert rep.hard_fail is False
    assert g["reviewed"] is False
    assert g["rule_recall"] == {"num": 2, "den": 3}
    assert g["fields"]["effective_date"] == {"num": 1, "den": 2}
    assert g["fields"]["category"] == {"num": 2, "den": 2}
    assert g["address_city"]["unresolved"] == 1 and g["address_city"]["skipped"] == 1
    ar = g["address_results"]
    assert (ar["correct"], ar["missed"], ar["missed_applies"], ar["wrong"], ar["not_checkable"]) == (1, 1, 1, 1, 1)
    text = "\n".join(rep.lines)
    assert "draft gold, unreviewed" in text
    assert "g-none" in text and "A2 x g-dep" in text  # mismatches are listed
    assert not any(k != "gold" for k in rep.metrics)  # only rep.metrics["gold"] is written


def test_reviewed_gold_drops_draft_label(tmp_path):
    gold_dir, out_dir = _write(tmp_path, reviewed_by="someone")
    rep = Report()
    ge.section(rep, out_dir, gold_dir=gold_dir, body_of=body_of)
    assert rep.metrics["gold"]["reviewed"] is True
    assert "unreviewed" not in "\n".join(rep.lines).lower()


def test_missing_gold_files(tmp_path):
    rep = Report()
    ge.section(rep, tmp_path, gold_dir=tmp_path / "nope")
    assert rep.lines == ["[4] Gold set (rules + addresses): not measured (no gold files)"]
    assert rep.hard_fail is False


# ------------------------------------------------------------------ the real gold files
def test_real_gold_files_are_valid_drafts():
    rules_doc, addr_doc = ge.load_gold()
    assert ge.validate_gold(rules_doc, addr_doc) == []
    for doc in (rules_doc, addr_doc):
        assert "status" in doc and "reviewed_by" in doc
    if not rules_doc["reviewed_by"]:
        assert rules_doc["status"] == "draft"


def test_real_gold_anchors_are_verbatim_in_corpus():
    from navigator import starter

    rules_doc, _ = ge.load_gold()
    for g in rules_doc["rules"]:
        for did, anchor in ge._anchors(g):
            body = ge.doc_body(starter.doc_text(did))
            assert body is not None, f"{g['id']}: {did} has no text"
            assert ge.norm(anchor) in body, f"{g['id']}: anchor not in {did}"
