"""eval/determinism.py: comparison, timestamp exclusion, safety guards and the eval section.

No network, no LLM, no pipeline run: the stage re-run itself (minutes) is
`python -m eval.determinism`; here only its pieces are exercised on synthetic files.
"""
from __future__ import annotations

import json

import pytest

from eval import determinism as det
from eval.run_eval import Report

pytestmark = pytest.mark.smoke


def summaries(ts, body="x", indent=1):
    return (json.dumps({"generated_at": ts, "model": "m", "summaries": {"r-1": {"generated_at": body}}},
                       indent=indent) + "\n").encode()


def test_excluded_fields_are_only_top_level_timestamps():
    assert det.EXCLUDED_FIELDS == {"changes_internal.json": ["generated_at"],
                                   "summaries.json": ["generated_at"]}
    assert set(det.EXCLUDED_FIELDS) <= set(det.COMPARED)


def test_top_level_timestamp_ignored():
    a = summaries("2030-01-01T00:00:00Z")
    b = summaries("2031-02-02T11:11:11Z")
    assert a != b
    assert det.compare_bytes("summaries.json", a, b) == "identical"
    ci_a = (json.dumps({"generated_at": "t1", "tests": {}}, indent=2) + "\n").encode()
    ci_b = (json.dumps({"generated_at": "t2", "tests": {}}, indent=2) + "\n").encode()
    assert det.compare_bytes("changes_internal.json", ci_a, ci_b) == "identical"


def test_nested_field_with_same_name_is_not_excluded():
    a = summaries("t", body="one")
    b = summaries("t", body="two")
    assert det.compare_bytes("summaries.json", a, b) == "differs"


def test_timestamp_only_excluded_in_listed_files():
    a = (json.dumps({"generated_at": "t1", "x": 1}, indent=2) + "\n").encode()
    b = (json.dumps({"generated_at": "t2", "x": 1}, indent=2) + "\n").encode()
    assert det.compare_bytes("rules.json", a, b) == "differs"


def test_any_other_byte_difference_counts():
    a = summaries("t1")
    assert det.compare_bytes("summaries.json", a, a.replace(b"\n", b"\r\n")) == "differs"
    assert det.compare_bytes("summaries.json", a, a + b" ") == "differs"
    assert det.compare_bytes("summaries.json", a, None) == "missing"


def test_compare_dirs_and_diagnosis(tmp_path):
    dirs = {k: tmp_path / k for k in ("r1", "r2", "c")}
    for d in dirs.values():
        d.mkdir()
    for name in det.COMPARED:
        for d in dirs.values():
            (d / name).write_bytes(b'{\n  "a": 1\n}\n')
    (dirs["r2"] / "lookups.json").write_bytes(b'{\n  "a": 2\n}\n')
    (dirs["c"] / "rules.json").unlink()
    res = det.compare_dirs(dirs["r1"], dirs["r2"], dirs["c"])
    assert res["files"]["lookups.json"] == "differs"
    assert res["detail"]["lookups.json"]["run1_vs_run2"] == "differs"
    assert "line 2" in res["detail"]["lookups.json"]["run_diff"]
    assert res["files"]["rules.json"] == "differs"
    assert res["detail"]["rules.json"]["run_vs_committed"] == "missing"
    assert res["files"]["timeline.json"] == "identical"


def test_fingerprint_detects_writes(tmp_path, monkeypatch):
    monkeypatch.setattr(det.settings, "REPO_ROOT", tmp_path)
    (tmp_path / "outputs").mkdir()
    (tmp_path / "outputs" / "a.json").write_text("1")
    before = det.fingerprint(["outputs", "config/none.yaml"])
    assert det.fingerprint_changes(before, det.fingerprint(["outputs"])) == []
    (tmp_path / "outputs" / "a.json").write_text("2")
    (tmp_path / "outputs" / "b.json").write_text("3")
    assert det.fingerprint_changes(before, det.fingerprint(["outputs"])) == ["outputs/a.json", "outputs/b.json"]


def test_api_is_blocked_and_miss_recorded(monkeypatch):
    from navigator.extract import llm

    monkeypatch.setattr(llm, "_get_client", llm._get_client)   # restored after the test
    misses: list[str] = []
    det._block_api(misses)
    with pytest.raises(det.CacheMiss):
        llm._get_client()
    assert len(misses) == 1


def test_path_redirect_keeps_other_keys(monkeypatch, tmp_path):
    monkeypatch.setattr(det.settings, "path", det.settings.path)   # restored after the test
    cache = det.settings.path("cache")
    det._redirect_paths(tmp_path / "o", tmp_path / "s")
    assert det.settings.path("outputs") == tmp_path / "o"
    assert det.settings.path("scores") == tmp_path / "s"
    assert det.settings.path("cache") == cache


# ------------------------------------------------------------------ section


def _doc(files, commit, errors=()):
    return {"ts": "2030-01-01T00:00:00Z", "commit": commit, "seconds": 1.0,
            "excluded_fields": det.EXCLUDED_FIELDS, "files": files, "errors": list(errors),
            "detail": {n: {"run1_vs_run2": s, "run_vs_committed": s} for n, s in files.items()}}


def _section(tmp_path, monkeypatch, doc, head="abc1234"):
    monkeypatch.setattr(det, "_git", lambda *a: head)
    if doc is not None:
        (tmp_path / "determinism.json").write_text(json.dumps(doc), encoding="utf-8")
    rep = Report()
    det.section(rep, tmp_path, scores_dir=tmp_path)
    return rep


def test_section_not_run(tmp_path, monkeypatch):
    rep = _section(tmp_path, monkeypatch, None)
    assert not rep.hard_fail and rep.metrics["determinism"]["state"] == "not run"
    assert "not run" in rep.lines[1]


def test_section_current_identical_passes(tmp_path, monkeypatch):
    rep = _section(tmp_path, monkeypatch, _doc({"rules.json": "identical"}, "abc1234"))
    assert not rep.hard_fail
    assert rep.metrics["determinism"]["state"] == "current" and rep.metrics["determinism"]["ok"]
    assert "determinism_identical" not in rep.metrics


def test_section_current_mismatch_is_hard(tmp_path, monkeypatch):
    rep = _section(tmp_path, monkeypatch, _doc({"rules.json": "identical", "lookups.json": "differs"}, "abc1234"))
    assert rep.hard_fail
    assert any("lookups.json" in line for line in rep.lines)


def test_section_errors_are_hard(tmp_path, monkeypatch):
    rep = _section(tmp_path, monkeypatch, _doc({"rules.json": "identical"}, "abc1234", ["cache miss"]))
    assert rep.hard_fail


def test_section_stale(tmp_path, monkeypatch):
    rep = _section(tmp_path, monkeypatch, _doc({"rules.json": "differs"}, "0000000"))
    assert rep.metrics["determinism"]["state"] == "stale"
    assert any("stale" in line for line in rep.lines)
    assert not rep.hard_fail          # describes another commit; re-run before trusting it
