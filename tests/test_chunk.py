import pytest

from navigator.extract.chunk import (
    HEADING_RE,
    JUNK_MAX_LEN,
    MAX_CHARS,
    chunk_doc,
    junk_lines,
    prompt_text,
)
from navigator.ingest.corpus import Doc, load_all

HEADER = "SOURCE: https://example.gov/x\nRETRIEVED: 2026-10-01 22:35 UTC\n\n"


@pytest.fixture(scope="module")
def corpus():
    docs = [d for d in load_all() if d.text_available]
    return [(d, chunk_doc(d)) for d in docs]


def _doc(body: str) -> Doc:
    text = HEADER + body
    return Doc(doc_id="T001", jurisdiction="CA", level="state", url="https://example.gov/x",
               source_type="official", capture="yes", manifest_status="ok", retrieved_at="x",
               source_sha256=None, origin="starter", text_file=None, text_available=True,
               body_offset=len(HEADER), n_chars=len(text), text=text)


# ------------------------------------------------------- invariants on all 54 real docs


def test_chunks_tile_every_body(corpus):
    for doc, chunks in corpus:
        assert chunks, doc.doc_id
        assert chunks[0].char_start == doc.body_offset
        assert chunks[-1].char_end == len(doc.text)
        for prev, nxt in zip(chunks, chunks[1:]):
            assert prev.char_start < nxt.char_start <= prev.char_end, nxt.chunk_id  # no gaps
            assert nxt.overlap_chars == prev.char_end - nxt.char_start
            if prev.split == "heading":
                assert nxt.overlap_chars == 0
        for c in chunks:
            assert c.char_end - c.char_start <= MAX_CHARS
            if c.split == "heading":
                line = doc.text[c.char_end: doc.text.find("\n", c.char_end)]
                assert HEADING_RE.match(line), c.chunk_id


def test_chunk_ids_unique_and_deterministic(corpus):
    ids = [c.chunk_id for _, chunks in corpus for c in chunks]
    assert len(ids) == len(set(ids))
    doc, chunks = next((d, c) for d, c in corpus if d.doc_id == "D067")
    assert len(chunks) > 1
    assert chunk_doc(doc) == chunks


def test_prompt_text_keeps_every_substantive_line(corpus):
    """Only short digit-free menu lines may be dropped; everything else reaches the model."""
    for doc, chunks in corpus:
        for c in chunks:
            prompt = prompt_text(doc, c)
            for a, b in c.dropped:
                assert c.char_start <= a < b <= c.char_end
                s = doc.text[a:b].strip()
                assert len(s) <= JUNK_MAX_LEN and not any(ch.isdigit() for ch in s), (c.chunk_id, s)
            kept = set(prompt.splitlines())
            for line in doc.text[c.char_start:c.char_end].splitlines():
                if len(line.strip()) > JUNK_MAX_LEN or any(ch.isdigit() for ch in line):
                    assert line in kept, (c.chunk_id, line)


def test_known_date_phrase_reaches_a_prompt(corpus):
    # D069's relative effective-date sentence must be visible to extraction (NOTES.md).
    doc, chunks = next((d, c) for d, c in corpus if d.doc_id == "D069")
    assert any("twelfth month next following" in prompt_text(doc, c) for c in chunks)


# ----------------------------------------------------------------- synthetic cases


def test_small_doc_is_one_chunk():
    chunks = chunk_doc(_doc("One short paragraph.\n"))
    assert len(chunks) == 1 and chunks[0].split == "end" and chunks[0].chunk_id == "T001-c001"


def test_long_doc_cuts_at_heading_without_overlap():
    para = ("This sentence is filler text for the chunker test. " * 20 + "\n")
    body = "Article 1: General\n" + para * 30 + "Article 2: More\n" + para * 30
    chunks = chunk_doc(_doc(body), max_chars=40_000)
    assert [c.split for c in chunks] == ["heading", "end"]
    assert chunks[1].overlap_chars == 0
    assert chunks[1].heading == "Article 2: More"


def test_no_boundary_falls_back_to_hard_cut_with_progress():
    chunks = chunk_doc(_doc("x" * 10_000), max_chars=3_000, overlap=500)
    assert chunks[0].split == "hard"
    assert chunks[-1].char_end == len(HEADER) + 10_000
    assert all(b.char_start > a.char_start for a, b in zip(chunks, chunks[1:]))


def test_junk_rule_menu_vs_table():
    menu = "Home\nSign in\nSearch\nClose\n" * 3        # repeated menu block -> dropped
    table = "Effective Period\nAmount of Increase\n3.1 percent\n" * 2   # table headers -> kept
    lone = "Read more\nA sentence that is long enough to be real content here.\n" * 3
    doc = _doc(menu + table + lone)
    dropped = {doc.text[a:b].strip() for a, b in junk_lines(doc.text, doc.body_offset)}
    assert dropped == {"Home", "Sign in", "Search", "Close"}
