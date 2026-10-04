"""Find a model-supplied quote in the stored document (BACKEND_PLAN.md 2.5 gate 2).

Three levels, strictest first; offsets always refer to the full stored file:
- exact:      the quote occurs character for character in the body
- normalized: equal after collapsing whitespace runs to one space
- tolerant:   also equal after folding curly quotes, dashes, non-breaking and soft hyphens,
              line-break hyphenation and spacing after the section sign
No fuzzy matching: a quote that differs in any word is not found, and the record is rejected.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Literal

Match = Literal["exact", "normalized", "tolerant"]
MIN_SPAN = 20
SECTION_SIGN = chr(0xA7)

FOLD = {
    "‘": "'", "’": "'", "‚": "'", "′": "'", "`": "'",
    "“": '"', "”": '"', "„": '"', "″": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-",
    " ": " ", " ": " ", " ": " ", " ": " ",
}
DROP = {"­", "​", "﻿"}


def _normalize(s: str, tolerant: bool) -> tuple[str, list[int]]:
    """Normalized text plus, for each output char, the index of its source char."""
    out: list[str] = []
    idx: list[int] = []
    s_nfc = unicodedata.normalize("NFC", s)
    # NFC can change length; offsets are only meaningful when it does not.
    src = s_nfc if len(s_nfc) == len(s) else s
    prev_space = True
    i = 0
    while i < len(src):
        c = src[i]
        if tolerant:
            if c in DROP:
                i += 1
                continue
            c = FOLD.get(c, c)
            # "regu-\nlation" -> "regulation"
            if c == "-" and i + 1 < len(src) and src[i + 1] == "\n" and out and out[-1].isalpha():
                j = i + 1
                while j < len(src) and src[j].isspace():
                    j += 1
                if j < len(src) and src[j].islower():
                    i = j
                    continue
        if c.isspace():
            if not prev_space:
                out.append(" ")
                idx.append(i)
            prev_space = True
        else:
            if tolerant and c == SECTION_SIGN:
                # a section sign followed by spaces compares equal to one without
                out.append(c)
                idx.append(i)
                j = i + 1
                while j < len(src) and src[j].isspace():
                    j += 1
                i = j
                prev_space = True
                continue
            out.append(c)
            idx.append(i)
            prev_space = False
        i += 1
    while out and out[-1] == " ":
        out.pop()
        idx.pop()
    return "".join(out), idx


def find_span(text: str, quote: str, start: int = 0) -> tuple[int, int, Match] | None:
    """(span_start, span_end, match) in `text` coordinates, searching from `start`; None if absent."""
    q = quote.strip()
    if len(q) < MIN_SPAN:
        return None
    pos = text.find(q, start)
    if pos >= 0:
        return pos, pos + len(q), "exact"
    body = text[start:]
    for level, tolerant in (("normalized", False), ("tolerant", True)):
        nb, idx = _normalize(body, tolerant)
        nq, _ = _normalize(q, tolerant)
        if len(nq) < MIN_SPAN:
            return None
        p = nb.find(nq)
        if p >= 0:
            return start + idx[p], start + idx[p + len(nq) - 1] + 1, level  # type: ignore[return-value]
    return None


NUMBER = re.compile(r"\$?\d[\d,]*(?:\.\d+)?%?")


def numbers_in(s: str) -> set[str]:
    """Numbers as written, without $ , % decoration ("$1,500.00" -> "1500.00")."""
    return {n.strip("$%").replace(",", "").rstrip(".") for n in NUMBER.findall(s or "")} - {""}


WORD_NUMBERS = {
    "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7",
    "eight": "8", "nine": "9", "ten": "10", "eleven": "11", "twelve": "12", "fifteen": "15",
    "twenty": "20", "thirty": "30", "sixty": "60", "ninety": "90", "half": "0.5",
}


def numbers_supported(claim: str | None, source: str) -> list[str]:
    """Numbers in `claim` that do not appear in `source` (digits or number words)."""
    if not claim:
        return []
    have = numbers_in(source)
    low = source.lower()
    have |= {v for w, v in WORD_NUMBERS.items() if re.search(rf"\b{w}\b", low)}
    if re.search(r"one and one-half|one and a half", low):
        have.add("1.5")
    return sorted(n for n in numbers_in(claim) if n not in have and n.lstrip("0") not in have)
