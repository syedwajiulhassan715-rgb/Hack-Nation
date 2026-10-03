"""Chunk document bodies for extraction (BACKEND_PLAN.md 2.2). Deterministic, no LLM.

A chunk is a character range [char_start, char_end) of the full stored file, so offsets
always refer to the file on disk. Documents that fit in MAX_CHARS are one chunk. Larger
ones are cut at the strongest boundary available in the back half of the window:

    heading (section-sign/Section/Article markers)  >  blank line  >  numbered item  >  any line break

Cuts at a heading need no overlap; any weaker cut starts the next chunk OVERLAP_CHARS
earlier (snapped to a line start) so a rule split across the cut is seen whole once.

Navigation junk (short repeated menu lines such as "Skip to Content") is not cut out of
the range; its line ranges are recorded in `dropped` and left out of `prompt_text()`.
Quote verification searches the whole document, so dropping junk never affects it.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from navigator import settings
from navigator.ingest.corpus import Doc

CHUNKER_VERSION = "chunk_v1"   # part of the LLM cache key: bump when cutting rules change
MAX_CHARS = 24_000             # ~6k tokens at ~4 chars/token
MIN_CHARS = MAX_CHARS // 2     # never cut in the front half of a window
OVERLAP_CHARS = 2_000          # ~500 tokens

HEADING_RE = re.compile(
    r"""^[ \t]*(
        \xa7+\s*\d                                  # section sign + number
      | (?:SECTION|Section|SEC\.|Sec\.)\s+\d+[\w.\-]*[.:]?\s+[A-Z]  # Section 4. Title ...
      | (?:ARTICLE|Article|CHAPTER|Chapter|DIVISION|Division|PART|Part)\s+[\dIVXLC]+[.:]
      | \d+(?:\.\d+)+[A-Z]?\.?\s+[A-Z][a-z]              # 1.2.010 Title
    )""",
    re.VERBOSE,
)
ITEM_RE = re.compile(r"^[ \t]*(?:\d{1,3}|[a-z]|\([a-z0-9]{1,4}\))\.?[ \t]+\S")
JUNK_MAX_LEN = 30

Split = Literal["end", "heading", "paragraph", "item", "line", "hard"]
STRENGTH: list[Split] = ["heading", "paragraph", "item", "line"]


class Chunk(BaseModel):
    doc_id: str
    chunk_id: str
    chunker_version: str = CHUNKER_VERSION
    char_start: int
    char_end: int
    split: Split                    # how this chunk's end was chosen
    overlap_chars: int = 0          # chars shared with the previous chunk
    heading: str | None = None      # nearest heading line at or before char_start
    dropped: list[tuple[int, int]] = []  # junk line ranges inside the chunk (file offsets)


def _lines(text: str, start: int, end: int):
    """Yield (line_start, line_end_excl_newline) for lines in text[start:end]."""
    pos = start
    while pos < end:
        nl = text.find("\n", pos, end)
        stop = end if nl == -1 else nl
        yield pos, stop
        pos = stop + 1


JUNK_MIN_REPEATS = 3
JUNK_MIN_RUN = 4


def junk_lines(text: str, body_offset: int) -> list[tuple[int, int]]:
    """Website menu lines: short, repeated, and inside a block of other short lines.

    A line is dropped only if all hold: it is at most JUNK_MAX_LEN chars, has no digit,
    does not end in sentence punctuation, appears at least JUNK_MIN_REPEATS times in the
    document, and sits in a run of at least JUNK_MIN_RUN consecutive such short lines.
    Phase-2 review showed a looser rule (any line repeated twice) dropped table headers
    and wrapped sentence fragments, so this errs toward keeping text.
    """
    spans = [(a, b) for a, b in _lines(text, body_offset, len(text))]

    def short(s: str) -> bool:
        return 0 < len(s) <= JUNK_MAX_LEN and not any(c.isdigit() for c in s) and s[-1] not in ".:;,)\"”"

    stripped = [text[a:b].strip() for a, b in spans]
    counts = Counter(stripped)
    is_short = [short(s) for s in stripped]
    out: list[tuple[int, int]] = []
    i = 0
    while i < len(spans):
        if not is_short[i]:
            i += 1
            continue
        j = i
        while j < len(spans) and (is_short[j] or not stripped[j]):  # blank lines don't break a menu
            j += 1
        if sum(is_short[i:j]) >= JUNK_MIN_RUN:
            for k in range(i, j):
                if is_short[k] and counts[stripped[k]] >= JUNK_MIN_REPEATS:
                    a, b = spans[k]
                    out.append((a, b + 1 if b < len(text) else b))  # include the newline
        i = j
    return out


def _boundaries(text: str, start: int, end: int) -> dict[Split, list[int]]:
    """Candidate cut positions (line starts) by kind, within (start, end)."""
    found: dict[Split, list[int]] = {k: [] for k in STRENGTH}
    prev_blank = False
    for a, b in _lines(text, start, end):
        line = text[a:b]
        if a > start:
            found["line"].append(a)
            if prev_blank:
                found["paragraph"].append(a)
            if HEADING_RE.match(line):
                found["heading"].append(a)
            elif ITEM_RE.match(line):
                found["item"].append(a)
        prev_blank = not line.strip()
    return found


def _line_start_at_or_after(text: str, pos: int, limit: int) -> int:
    if pos <= 0 or text[pos - 1] == "\n":
        return pos
    nl = text.find("\n", pos, limit)
    return limit if nl == -1 else nl + 1


def chunk_doc(doc: Doc, max_chars: int = MAX_CHARS, overlap: int = OVERLAP_CHARS) -> list[Chunk]:
    if not doc.text_available or doc.text is None or doc.body_offset is None:
        return []
    text, end = doc.text, len(doc.text)
    min_chars = max_chars // 2
    headings = [a for a, b in _lines(text, doc.body_offset, end) if HEADING_RE.match(text[a:b])]
    junk = junk_lines(text, doc.body_offset)

    chunks: list[Chunk] = []
    start, overlap_used = doc.body_offset, 0
    while start < end:
        if end - start <= max_chars:
            cut, kind = end, "end"
        else:
            window = _boundaries(text, start, start + max_chars)
            cut, kind = start + max_chars, "hard"
            for k in STRENGTH:
                ok = [p for p in window[k] if p - start >= min_chars]
                if ok:
                    cut, kind = ok[-1], k
                    break
        prior = [h for h in headings if h <= start]
        heading = None
        if prior:
            h = prior[-1]
            nl = text.find("\n", h)
            heading = text[h: nl if nl != -1 else end].strip()[:200]
        chunks.append(Chunk(
            doc_id=doc.doc_id, chunk_id=f"{doc.doc_id}-c{len(chunks) + 1:03d}",
            char_start=start, char_end=cut, split=kind, overlap_chars=overlap_used, heading=heading,
            dropped=[(a, b) for a, b in junk if a >= start and b <= cut],
        ))
        if cut >= end:
            break
        if kind == "heading":
            start, overlap_used = cut, 0
        else:
            nxt = _line_start_at_or_after(text, max(cut - overlap, start + 1), cut)
            start, overlap_used = nxt, cut - nxt
    return chunks


def prompt_text(doc: Doc, chunk: Chunk) -> str:
    """Chunk text as sent to the model: the file range minus recorded junk lines."""
    assert doc.text is not None
    parts, pos = [], chunk.char_start
    for a, b in chunk.dropped:
        parts.append(doc.text[pos:a])
        pos = b
    parts.append(doc.text[pos:chunk.char_end])
    return "".join(parts)


def write_chunks(chunks: list[Chunk], path: Path | None = None) -> Path:
    path = path or settings.path("outputs") / "chunks.jsonl"
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for c in chunks:
            fh.write(json.dumps(c.model_dump(mode="json"), ensure_ascii=False) + "\n")
    return path


def read_chunks(path: Path | None = None) -> list[Chunk]:
    path = path or settings.path("outputs") / "chunks.jsonl"
    with path.open(encoding="utf-8") as fh:
        return [Chunk.model_validate_json(line) for line in fh if line.strip()]


def run() -> None:
    from navigator.ingest.corpus import read_docs

    docs = [d for d in read_docs() if d.text_available]
    chunks = [c for d in docs for c in chunk_doc(d)]
    path = write_chunks(chunks)
    multi = Counter(c.doc_id for c in chunks)
    big = ", ".join(f"{k}:{v}" for k, v in sorted(multi.items()) if v > 1)
    dropped = sum(b - a for c in chunks for a, b in c.dropped)
    print(f"chunked {len(docs)} documents into {len(chunks)} chunks (multi-chunk: {big or 'none'}); "
          f"{dropped} chars of navigation junk left out of prompts -> "
          f"{path.relative_to(settings.REPO_ROOT).as_posix()}")
