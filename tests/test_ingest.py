import csv
import hashlib

import pytest

from navigator import settings, starter
from navigator.ingest import corpus
from navigator.ingest.corpus import load_all, load_doc, parse_header, read_docs, write_docs

HEADER = "SOURCE: https://example.gov/page\nRETRIEVED: 2026-10-01 22:35 UTC\n\n"


@pytest.fixture(scope="module")
def docs():
    return {d.doc_id: d for d in load_all()}


def test_counts_match_contract(docs):
    assert len(docs) == 87
    assert sum(d.text_available for d in docs.values()) == 54
    assert not docs["D056"].text_available           # empty capture (403)
    assert not docs["D032"].text_available           # check-terms publisher page
    assert all(d.unavailable_reason for d in docs.values() if not d.text_available)


def test_text_is_byte_exact_and_offsets_valid(docs):
    for d in docs.values():
        if not d.text_available:
            continue
        path = settings.REPO_ROOT / d.text_file
        assert d.text == starter.doc_text(d.doc_id)
        assert d.text_sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
        assert d.n_chars == len(d.text)
        assert d.text.startswith("SOURCE: ")
        assert d.text[d.body_offset - 2: d.body_offset] == "\n\n"
        assert not d.text[d.body_offset:].startswith(("SOURCE:", "RETRIEVED:"))
        assert d.retrieved_at and d.url == starter.manifest()[d.doc_id]["url"]


def test_levels(docs):
    assert docs["D024"].level == "state" and docs["D024"].jurisdiction == "CA"
    assert docs["D001"].level == "city" and docs["D001"].jurisdiction == "Berkeley, CA"
    assert {d.level for d in docs.values()} == {"state", "city"}


def test_parse_header():
    assert parse_header(HEADER + "body") == ("https://example.gov/page", "2026-10-01 22:35 UTC", len(HEADER))
    assert parse_header("SOURCE: x\nRETRIEVED: y\nnot blank\nbody") is None
    assert parse_header("RETRIEVED: y\nSOURCE: x\n\nbody") is None
    assert parse_header("no header at all") is None


def _row(tmp_path, body, name="S001.txt", **over):
    (tmp_path / name).write_text(body, encoding="utf-8", newline="\n")
    row = {"doc_id": "S001", "jurisdictions": "Cambridge, MA", "url": "https://example.gov/page",
           "source_type": "official", "capture": "manual", "retrieved_at": "2026-10-01T22:35Z",
           "sha256": "", "text_file": name, "status": "ok"}
    row.update(over)
    return row


def test_supplement_doc_loads(tmp_path):
    d = load_doc(_row(tmp_path, HEADER + "Some ordinance text."), tmp_path, "supplement")
    assert d.text_available and d.level == "city" and d.body_offset == len(HEADER)
    assert d.text[d.body_offset:] == "Some ordinance text."


@pytest.mark.smoke
@pytest.mark.parametrize("body, over, reason", [
    ("no header here", {}, "header"),
    (HEADER.replace("example.gov", "other.gov") + "x", {}, "differs from manifest url"),
    (HEADER + "x", {"source_type": "secondary (law firm / news / mirror)"}, "official"),
    (HEADER + "x", {"jurisdictions": "Middlesex County"}, "jurisdiction"),
    ("", {}, "empty"),
])
def test_unusable_docs_fail_closed(tmp_path, body, over, reason):
    d = load_doc(_row(tmp_path, body, **over), tmp_path, "supplement")
    assert not d.text_available and d.text is None
    assert reason in d.unavailable_reason


def test_retrieved_mismatch_warns_and_keeps_manifest(tmp_path):
    d = load_doc(_row(tmp_path, HEADER + "x", retrieved_at="2026-09-30T10:00Z"), tmp_path, "supplement")
    assert d.text_available and d.retrieved_at == "2026-09-30T10:00Z"
    assert any("differs from manifest" in w for w in d.warnings)


@pytest.mark.smoke
def test_duplicate_doc_id_across_manifests_rejected(tmp_path, monkeypatch):
    row = _row(tmp_path, HEADER + "x", doc_id="D001")
    with (tmp_path / "manifest.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(row))
        w.writeheader()
        w.writerow(row)
    real = settings.path
    monkeypatch.setattr(corpus.settings, "path", lambda k: tmp_path if k == "supplement" else real(k))
    with pytest.raises(ValueError, match="duplicate doc_id D001"):
        load_all()


def test_docs_jsonl_roundtrip(tmp_path, docs):
    p = write_docs(list(docs.values()), tmp_path / "docs.jsonl")
    assert {d.doc_id: d for d in read_docs(p)} == docs
