"""Incremental document path (navigator/ingest/incremental.py): no network, no LLM.

Every test redirects outputs/, data/supplement/, the LLM cache and the change-test map to
a temporary directory, so the real outputs are never written. The synthetic document is
a test fixture, not law: it is never stored outside tmp_path.
"""
from __future__ import annotations

import csv
import functools
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from navigator import settings
from navigator.ingest import incremental
from navigator.ingest.incremental import IngestError

REAL_ROOT = settings.REPO_ROOT


def REAL_PATH(key: str) -> Path:  # noqa: N802 - the unpatched settings.path
    return REAL_ROOT / settings.load()["paths"][key]

SYNTH_URL = "https://example.org/synthetic-test-ordinance"
SYNTH_SPAN = "No landlord shall use the synthetic test fixture device to set any rent for a dwelling unit."
SYNTH_TEXT = (
    f"SOURCE: {SYNTH_URL}\n"
    "RETRIEVED: 2026-10-03 12:00 UTC\n"
    "\n"
    "SYNTHETIC TEST DOCUMENT (pytest fixture; not a law)\n\n"
    f"Section 1. {SYNTH_SPAN}\n"
)


def _write(tmp_path: Path, name: str, text: str | bytes) -> Path:
    p = tmp_path / name
    if isinstance(text, bytes):
        p.write_bytes(text)
    else:
        p.write_bytes(text.encode("utf-8"))
    return p


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """Redirect every writable path into tmp_path; forbid LLM calls."""
    out = tmp_path / "outputs"
    out.mkdir()
    redirect = {"outputs": out, "supplement": tmp_path / "supplement", "cache": tmp_path / "cache",
                "scores": tmp_path / "scores"}
    monkeypatch.setattr(settings, "path", lambda key: redirect.get(key) or REAL_PATH(key))
    # Stage summaries print paths relative to the repo root; make tmp_path the root for them.
    # REAL_PATH uses REAL_ROOT, so starter paths still point at the real (read-only) pack.
    monkeypatch.setattr(settings, "REPO_ROOT", tmp_path)
    from navigator.changes import matcher
    monkeypatch.setattr(matcher, "map_path", lambda: tmp_path / "test_rule_map.yaml")
    from navigator.extract import llm

    def no_llm(**_):
        raise AssertionError("LLM must not be called in tests")
    monkeypatch.setattr(llm, "call_json", no_llm)
    return tmp_path


def _starter_hashes() -> dict[str, str]:
    root = REAL_PATH("starter")
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


# ---------------------------------------------------------------- validation


BAD_FILES = {
    "no_header": "Section 1. Some text without the corpus header lines at all.\n",
    "no_blank_line": f"SOURCE: {SYNTH_URL}\nRETRIEVED: 2026-10-03 12:00 UTC\nSection 1. text text text text\n",
    "bad_url": "SOURCE: example.org/page\nRETRIEVED: 2026-10-03 12:00 UTC\n\nSection 1. long enough body text here.\n",
    "bad_retrieved": f"SOURCE: {SYNTH_URL}\nRETRIEVED: yesterday\n\nSection 1. long enough body text here.\n",
    "impossible_date": f"SOURCE: {SYNTH_URL}\nRETRIEVED: 2026-13-45 12:00 UTC\n\nSection 1. long enough body text.\n",
    "empty_body": f"SOURCE: {SYNTH_URL}\nRETRIEVED: 2026-10-03 12:00 UTC\n\n   \n",
    "crlf": SYNTH_TEXT.replace("\n", "\r\n"),
    "empty": "",
}


@pytest.mark.smoke
@pytest.mark.parametrize("name", sorted(BAD_FILES))
def test_validate_rejects_bad_files(tmp_path, name):
    with pytest.raises(IngestError) as exc:
        incremental.validate_file(_write(tmp_path, f"{name}.txt", BAD_FILES[name]))
    assert exc.value.step == "validate"


@pytest.mark.smoke
def test_validate_rejects_bom_non_utf8_and_missing(tmp_path):
    for name, raw in (("bom", b"\xef\xbb\xbf" + SYNTH_TEXT.encode()), ("latin1", SYNTH_TEXT.encode() + b"\xe9\xff")):
        with pytest.raises(IngestError):
            incremental.validate_file(_write(tmp_path, f"{name}.txt", raw))
    with pytest.raises(IngestError, match="not found"):
        incremental.validate_file(tmp_path / "missing.txt")


@pytest.mark.smoke
def test_validate_accepts_corpus_format(tmp_path):
    checked = incremental.validate_file(_write(tmp_path, "ok.txt", SYNTH_TEXT))
    assert checked["url"] == SYNTH_URL
    assert checked["retrieved_at"] == "2026-10-03T12:00Z"     # manifest format
    assert checked["text"][checked["body_offset"]:].startswith("SYNTHETIC")


@pytest.mark.smoke
def test_starter_texts_pass_validation():
    # The format check must accept every real corpus file.
    text_dir = REAL_PATH("manifest").parent / "text"
    for p in sorted(text_dir.glob("*.txt")):
        if p.stat().st_size:
            incremental.validate_file(p)


@pytest.mark.smoke
def test_bad_file_stops_before_writing_anything(sandbox):
    events = []
    with pytest.raises(IngestError) as exc:
        incremental.run(_write(sandbox, "bad.txt", BAD_FILES["no_header"]), progress=events.append,
                        jurisdiction="Hoboken, NJ")
    assert exc.value.step == "validate"
    assert [(e["step"], e["status"]) for e in events] == [("validate", "start"), ("validate", "error")]
    assert not (sandbox / "supplement").exists()
    audit_lines = [json.loads(x) for x in (sandbox / "outputs" / "audit.jsonl").read_text().splitlines()]
    assert audit_lines[-1]["stage"] == "incremental" and audit_lines[-1]["decision"] == "validate_failed"


# ---------------------------------------------------------------- registration


def _checked(tmp_path, text=SYNTH_TEXT, name="doc.txt"):
    return incremental.validate_file(_write(tmp_path, name, text))


@pytest.mark.smoke
def test_register_writes_supplement_only(sandbox):
    before = _starter_hashes()
    row = incremental.register(_checked(sandbox), jurisdiction="Hoboken, NJ")
    assert row["new"] and row["doc_id"] == "S001"
    sup = sandbox / "supplement"
    assert (sup / "text" / "S001.txt").read_bytes() == SYNTH_TEXT.encode()
    with (sup / "manifest.csv").open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert list(rows[0]) == incremental.MANIFEST_COLUMNS
    assert rows[0] | {} == {"doc_id": "S001", "jurisdictions": "Hoboken, NJ", "url": SYNTH_URL,
                            "source_type": "official", "capture": "manual", "retrieved_at": "2026-10-03T12:00Z",
                            "sha256": hashlib.sha256(SYNTH_TEXT.encode()).hexdigest(),
                            "text_file": "text/S001.txt", "status": "ok"}
    # The ingest stage reads it as a supplement document with text.
    from navigator.ingest.corpus import load_all, manifest_rows
    doc = next(d for d in load_all() if d.doc_id == "S001")
    assert doc.origin == "supplement" and doc.text_available and doc.text == SYNTH_TEXT
    assert manifest_rows()["S001"]["url"] == SYNTH_URL
    assert _starter_hashes() == before

    # Idempotent for identical bytes; append-only for a changed text under the same url.
    again = incremental.register(_checked(sandbox), jurisdiction="Hoboken, NJ")
    assert not again["new"] and again["doc_id"] == "S001"
    with pytest.raises(IngestError, match="append-only"):
        incremental.register(_checked(sandbox, SYNTH_TEXT + "More text.\n", "v2.txt"))
    other = SYNTH_TEXT.replace(SYNTH_URL, SYNTH_URL + "-2")
    assert incremental.register(_checked(sandbox, other, "o.txt"), jurisdiction="NJ")["doc_id"] == "S002"


@pytest.mark.smoke
def test_register_fails_closed_on_jurisdiction(sandbox):
    checked = _checked(sandbox)
    with pytest.raises(IngestError, match="jurisdiction unknown"):
        incremental.register(checked)
    with pytest.raises(IngestError, match="not in the corpus"):
        incremental.register(checked, jurisdiction="Austin, TX")
    with pytest.raises(IngestError, match="neither"):
        incremental.register(checked, jurisdiction="Hudson County")
    with pytest.raises(IngestError, match="already used"):
        incremental.register(checked, jurisdiction="NJ", doc_id="D001")
    assert not (sandbox / "supplement" / "manifest.csv").exists()


@pytest.mark.smoke
def test_register_uses_starter_row_for_released_text(sandbox):
    from navigator import starter
    rows = starter.manifest()
    with_text = next(r for r in rows.values() if r["text_file"])
    no_text = next(r for r in rows.values() if not r["text_file"] and r["capture"] == "check-terms")
    as_text = lambda url: SYNTH_TEXT.replace(SYNTH_URL, url)  # noqa: E731
    with pytest.raises(IngestError, match="already has text"):
        incremental.register(_checked(sandbox, as_text(with_text["url"]), "a.txt"))
    row = incremental.register(_checked(sandbox, as_text(no_text["url"]), "b.txt"))
    assert row["jurisdictions"] == no_text["jurisdictions"].strip()
    assert no_text["doc_id"] in row["note"]


@pytest.mark.smoke
def test_stable_ids():
    def r(rid, *cands):
        return {"team_rule_id": rid, "provenance": [{"candidate_id": c} for c in cands]}
    prior = [r("r-0001", "a"), r("r-0002", "b"), r("r-0003", "c")]
    # verify renumbered: a new rule sorted first, b merged with a new candidate, c unchanged
    current = [r("r-0001", "new"), r("r-0002", "a"), r("r-0003", "b", "x"), r("r-0004", "c")]
    assert incremental.stable_ids(prior, current) == {
        "r-0001": "r-0004", "r-0002": "r-0001", "r-0003": "r-0002", "r-0004": "r-0003"}
    # nothing changed: identity
    assert incremental.stable_ids(prior, prior) == {x["team_rule_id"]: x["team_rule_id"] for x in prior}
    # ambiguous merge target: no id reused, new ids instead
    amb = [r("r-0001", "a", "z"), r("r-0002", "a", "y"), r("r-0003", "b"), r("r-0004", "c")]
    m = incremental.stable_ids(prior, amb)
    assert m["r-0003"] == "r-0002" and m["r-0004"] == "r-0003"
    assert {m["r-0001"], m["r-0002"]} == {"r-0004", "r-0005"}


# ---------------------------------------------------------------- full run (fake extraction)


def _fake_extract_chunk(calls):
    from navigator.extract import extract as ex

    def fake(doc, chunk, n_chunks, use_cache=True):
        calls.append((doc.doc_id, use_cache))
        rule = {k: None for k in ex.RULE_FIELDS}
        rule.update(jurisdiction=doc.jurisdiction, level=doc.level, category="algorithmic_rent_setting",
                    status_hint="enacted", title="Synthetic test fixture rule",
                    requirement="Landlords may not use the synthetic test fixture device to set rent.",
                    citation="Synthetic Test Document, Section 1", quoted_span=SYNTH_SPAN)
        return [{"candidate_id": f"{chunk.chunk_id}-r01", "source_doc_id": doc.doc_id, "source_url": doc.url,
                 "retrieved_at": doc.retrieved_at, "doc_jurisdiction": doc.jurisdiction, "doc_level": doc.level,
                 "source_type": doc.source_type, **rule,
                 "provenance": {"chunk_id": chunk.chunk_id, "char_start": chunk.char_start,
                                "char_end": chunk.char_end, "cache_key": "fake", "cached": use_cache,
                                "model": "fake", "served_model": "fake", "prompt_version": "fake"}}]
    return fake


def test_full_incremental_run(sandbox, monkeypatch):
    real_out = REAL_PATH("outputs")
    for f in ("candidates.jsonl", "parcels.json"):
        if not (real_out / f).is_file():
            pytest.skip(f"outputs/{f} not built")
        shutil.copy(real_out / f, sandbox / "outputs" / f)
    from navigator.changes import tracker
    from navigator.engine import lookup
    from navigator.extract import chunk
    from navigator.extract import extract as ex
    from navigator.ingest import corpus
    from navigator.verify import gates

    # The per-date timeline is not what this test checks; skipping it saves most of the time.
    monkeypatch.setattr(lookup, "run", functools.partial(lookup.run, timeline=False))
    # Baseline: the committed candidates through the deterministic stages.
    for stage in (corpus.run, chunk.run, gates.run, lookup.run, tracker.run):
        stage()
    out = sandbox / "outputs"
    base_rules = {r["team_rule_id"]: r for r in json.loads((out / "rules.json").read_text("utf-8"))["rules"]}
    base_lookups = json.loads((out / "lookups.json").read_text("utf-8"))["lookups"]
    base_cands = (out / "candidates.jsonl").read_text("utf-8")
    starter_before = _starter_hashes()

    calls: list[tuple[str, bool]] = []
    monkeypatch.setattr(ex, "extract_chunk", _fake_extract_chunk(calls))
    events: list[dict] = []
    summary = incremental.run(_write(sandbox, "synthetic.txt", SYNTH_TEXT), live=True,
                              progress=events.append, jurisdiction="Hoboken, NJ")

    # progress: start/done for every step, in order
    assert [(e["step"], e["status"]) for e in events] == [
        (s, st) for s in incremental.STEPS for st in ("start", "done")]
    assert [e["index"] for e in events][::2] == list(range(1, len(incremental.STEPS) + 1))
    # live: only the new document was extracted, with the cache off
    assert calls and all(c == ("S001", False) for c in calls)
    assert summary["doc_id"] == "S001" and summary["live"] and summary["n_candidates"] == len(calls)

    rules = {r["team_rule_id"]: r for r in json.loads((out / "rules.json").read_text("utf-8"))["rules"]}
    new_ids = set(summary["rules_from_doc"])
    assert new_ids and new_ids == set(summary["rules_new"]) == set(rules) - set(base_rules)
    top = max(int(k[2:]) for k in base_rules)
    assert all(int(k[2:]) > top for k in new_ids)               # appended, nothing renumbered
    for rid in new_ids:
        assert rules[rid]["source_doc_id"] == "S001" and rules[rid]["source_url"] == SYNTH_URL
        assert rules[rid]["quoted_span"] == SYNTH_SPAN
    # existing rules: byte-identical unless precedence now links them to the new rule
    assert not summary["rules_removed"]
    for rid, rec in base_rules.items():
        if json.dumps(rec, sort_keys=True) != json.dumps(rules[rid], sort_keys=True):
            assert rid in summary["rules_changed"] and new_ids & set(rules[rid]["overrides"]), rid
    assert summary["rules_unchanged"] == len(base_rules) - len(summary["rules_changed"])

    # other documents' candidates untouched
    after = (out / "candidates.jsonl").read_text("utf-8").splitlines()
    assert [x for x in after if json.loads(x)["source_doc_id"] != "S001"] == base_cands.splitlines()
    # lookups outside the new rule's city are unchanged
    parcels = {p["address_id"]: p for p in json.loads((out / "parcels.json").read_text("utf-8"))["parcels"]}
    lookups = json.loads((out / "lookups.json").read_text("utf-8"))["lookups"]
    assert set(lookups) == set(base_lookups)
    for aid, rows in base_lookups.items():
        if parcels[aid].get("state") != "NJ":
            assert lookups[aid] == rows, aid
    assert any(row["team_rule_id"] in new_ids for aid in lookups for row in lookups[aid])
    assert json.loads((out / "changes.json").read_text("utf-8"))

    # one audit line per step, data/starter untouched
    audit_lines = [json.loads(x) for x in (out / "audit.jsonl").read_text("utf-8").splitlines()]
    done = [a["step"] for a in audit_lines if a["stage"] == "incremental" and a["decision"].endswith("_done")]
    assert done == list(incremental.STEPS)
    assert _starter_hashes() == starter_before

    # running the same document again (cached) changes nothing
    first = (out / "rules.json").read_bytes()
    again = incremental.run(sandbox / "synthetic.txt", progress=lambda e: None)
    assert not again["registered"] and (out / "rules.json").read_bytes() == first
    assert not again["rules_new"] and not again["rules_changed"]
