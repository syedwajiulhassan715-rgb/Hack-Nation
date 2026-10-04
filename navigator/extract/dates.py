"""Effective dates and rule status, deterministic (BACKEND_PLAN.md 2.4, CONTRACT.md 6).

The model returns a verbatim `effective_date_phrase` and `effective_date_anchor`; the
named rules here turn them into an ISO (or partial) date. Every result names the rule
used (`method`) and any reason for human review. Nothing unparseable is guessed: the
date stays null and the record is flagged.
"""
from __future__ import annotations

import calendar
import datetime as dt
import re
from dataclasses import dataclass, field

MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})
MONTHS["sept"] = 9

ORDINALS = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6,
    "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12,
    "thirteenth": 13, "fourteenth": 14, "fifteenth": 15, "eighteenth": 18,
    "twenty-fourth": 24,
}
NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20,
    "thirty": 30, "forty-five": 45, "sixty": 60, "ninety": 90, "one hundred eighty": 180,
}

_MONTH_RE = r"(?P<mon>" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\.?"
LONG_DATE = re.compile(_MONTH_RE + r"\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?,?\s+(?P<year>\d{4})", re.I)
MONTH_YEAR = re.compile(_MONTH_RE + r",?\s+(?P<year>\d{4})\b", re.I)
NUMERIC_DATE = re.compile(r"\b(?P<m>\d{1,2})(?P<sep>[/-])(?P<d>\d{1,2})(?P=sep)(?P<y>\d{4}|\d{2})\b")
ISO_DATE = re.compile(r"\b(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})\b")
# words that mark the date a rule starts, as opposed to sunset or history dates
START_WORD = re.compile(r"\b(effect|effective|operative|enforce\w*|takes?|went|begin\w*|commenc\w*)\b", re.I)
END_WORD = re.compile(r"\b(until|repealed|expires?|sunset|inoperative|through)\b", re.I)

NTH_MONTH = re.compile(
    r"first day of the (?P<ord>[a-z\-]+|\d{1,2}(?:st|nd|rd|th)) (?:calendar )?month"
    r"\s+(?:next\s+)?(?:following|after)", re.I)
DAYS_AFTER = re.compile(
    r"\b(?:(?P<num>\d{1,3})|(?P<word>" + "|".join(sorted(NUMBER_WORDS, key=len, reverse=True)) + r"))"
    r"\s*(?:\(\d+\)\s*)?(?:calendar )?days?\s+(?:after|following|from)", re.I)
DAY_ORDINALS = {"tenth": 10, "fifteenth": 15, "twentieth": 20, "thirtieth": 30, "forty-fifth": 45,
                "sixtieth": 60, "ninetieth": 90}
NTH_DAY_AFTER = re.compile(
    r"(?:(?P<num>\d{1,3})(?:st|nd|rd|th)|(?P<word>" + "|".join(DAY_ORDINALS) + r"))"
    r" day (?:from and after|after|following)", re.I)
# "March 1, 2026 - February 28, 2027", "July 1, 2026 through June 30, 2027": a period
RANGE_SEP = re.compile(r"^\s*(?:,?\s*(?:through|thru|to|until)|[–—-])\s*$", re.I)
IMMEDIATELY = re.compile(r"\btake effect immediately\b", re.I)
CHAPTERED = re.compile(r"\bchaptered\b", re.I)


@dataclass
class DateResult:
    date: str | None                 # YYYY, YYYY-MM or YYYY-MM-DD
    method: str                      # named rule used
    review_reasons: list[str] = field(default_factory=list)
    confidence_penalty: float = 0.0  # subtracted from the record's confidence
    notes: list[str] = field(default_factory=list)  # informational, no human review needed


def _mk(y: int, m: int, d: int) -> dt.date | None:
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def find_dates(text: str) -> list[tuple[int, str]]:
    """All full or month-precision dates in text as (position, iso), in order."""
    found: list[tuple[int, str]] = []
    taken: list[range] = []

    def add(pos: int, end: int, iso: str | None) -> None:
        if iso and not any(pos in r for r in taken):
            found.append((pos, iso))
            taken.append(range(pos, end))

    for m in LONG_DATE.finditer(text):
        d = _mk(int(m["year"]), MONTHS[m["mon"].lower()], int(m["day"]))
        add(m.start(), m.end(), d.isoformat() if d else None)
    for m in ISO_DATE.finditer(text):
        d = _mk(int(m["y"]), int(m["m"]), int(m["d"]))
        add(m.start(), m.end(), d.isoformat() if d else None)
    for m in NUMERIC_DATE.finditer(text):
        y = int(m["y"])
        y = y + 2000 if y < 100 else y
        d = _mk(y, int(m["m"]), int(m["d"]))
        add(m.start(), m.end(), d.isoformat() if d else None)
    for m in MONTH_YEAR.finditer(text):
        add(m.start(), m.end(), f"{int(m['year']):04d}-{MONTHS[m['mon'].lower()]:02d}")
    return sorted(found)


def parse_anchor(anchor: str | None) -> str | None:
    """The single full date in an anchor phrase, or None if absent or ambiguous."""
    if not anchor:
        return None
    full = {iso for _, iso in find_dates(anchor) if len(iso) == 10}
    return full.pop() if len(full) == 1 else None


def first_day_of_nth_month_after(anchor: dt.date, n: int) -> dt.date:
    """First day of the n-th month after the anchor's month ("the first day of the twelfth
    month next following" an enactment in July 2026 -> 2027-07-01)."""
    months = anchor.year * 12 + (anchor.month - 1) + n
    return dt.date(months // 12, months % 12 + 1, 1)


def days_after(anchor: dt.date, n: int) -> dt.date:
    return anchor + dt.timedelta(days=n)


def ca_default_jan1_next_year(chaptered: dt.date) -> dt.date:
    """California non-urgency statutes take effect January 1 of the year after chaptering.
    This is not stated in the corpus text, so callers must flag the result for review."""
    return dt.date(chaptered.year + 1, 1, 1)


def _ordinal(word: str) -> int | None:
    word = word.lower()
    if word in ORDINALS:
        return ORDINALS[word]
    m = re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)", word)
    return int(m.group(1)) if m else None


def resolve(phrase: str | None, anchor: str | None, *, jurisdiction: str, level: str,
            status_hint: str) -> DateResult:
    """Effective date from the verbatim phrase and anchor. Never raises."""
    anchor_iso = parse_anchor(anchor)
    if phrase:
        if m := NTH_MONTH.search(phrase):
            n = _ordinal(m["ord"])
            if n and anchor_iso:
                d = first_day_of_nth_month_after(dt.date.fromisoformat(anchor_iso), n)
                return DateResult(d.isoformat(), f"first_day_of_nth_month_after(anchor, {n})")
            return DateResult(None, "unresolved", ["relative effective date without a parseable anchor date"])
        m = NTH_DAY_AFTER.search(phrase) or DAYS_AFTER.search(phrase)
        if m and not find_dates(phrase):
            word = (m.groupdict().get("word") or "").strip().lower()
            n = int(m["num"]) if m["num"] else DAY_ORDINALS.get(word) or NUMBER_WORDS.get(word)
            if n and anchor_iso:
                d = days_after(dt.date.fromisoformat(anchor_iso), n)
                return DateResult(d.isoformat(), f"days_after(anchor, {n})")
            return DateResult(None, "unresolved", ["relative effective date without a parseable anchor date"])
        if IMMEDIATELY.search(phrase) and not find_dates(phrase):
            if anchor_iso:
                return DateResult(anchor_iso, "immediately_on_anchor")
            return DateResult(None, "unresolved", ["takes effect immediately, but no anchor date stated"])

        dates = find_dates(phrase)
        if len({iso for _, iso in dates}) == 1:
            return DateResult(dates[0][1], "explicit_date")
        if len(dates) == 2 and _is_range(phrase, dates):
            return DateResult(dates[0][1], "date_range_start", [], 0.0,
                              [f"stated for the period {dates[0][1]} to {dates[1][1]}"])
        if dates:
            # Several dates: keep those introduced by a start word and not by a sunset word.
            starts = []
            for pos, iso in dates:
                before = phrase[max(0, pos - 80):pos]
                if START_WORD.search(before) and not END_WORD.search(before[-30:]):
                    starts.append(iso)
            if len(set(starts)) == 1:
                return DateResult(starts[0], "explicit_date", ["several dates in the effective-date phrase"],
                                  0.05)
            return DateResult(None, "unresolved", ["effective-date phrase has several dates; none chosen"])
        return DateResult(None, "unresolved", ["effective-date phrase has no date this parser understands"])

    if status_hint == "enacted" and level == "state" and jurisdiction == "CA" \
            and anchor and CHAPTERED.search(anchor) and anchor_iso:
        d = ca_default_jan1_next_year(dt.date.fromisoformat(anchor_iso))
        return DateResult(d.isoformat(), "ca_default_jan1_next_year(chaptered)",
                          ["California default effective date for non-urgency statutes "
                           "(not stated in the source text)"], 0.2)
    if status_hint == "enacted":
        # Normal for codified law; status is in_force, so say so but don't flag for review.
        return DateResult(None, "not_stated", [], 0.1, ["effective date not stated in source text"])
    return DateResult(None, "not_stated")


def _is_range(phrase: str, dates: list[tuple[int, str]]) -> bool:
    """Two dates joined only by a dash, 'to' or 'through', the first one earlier."""
    (p1, d1), (p2, d2) = dates
    m1 = next((m for rx in (LONG_DATE, ISO_DATE, NUMERIC_DATE, MONTH_YEAR) if (m := rx.match(phrase, p1))), None)
    return m1 is not None and bool(RANGE_SEP.match(phrase[m1.end():p2])) and d1 < d2


def status_on(status_hint: str, effective_date: str | None, as_of: str) -> str:
    """Rule status on a query date (BACKEND_PLAN.md 2.4). Partial dates count as their
    first day only once fully past: a rule effective "2026-01" is in force from 2026-02-01
    for sure, and in January 2026 its status is decided conservatively as not yet effective."""
    if status_hint == "bill_or_proposal":
        return "pending"
    if status_hint == "failed":
        return "failed"
    if effective_date is None:
        return "in_force"
    return "not_yet_effective" if _latest_day(effective_date) > as_of else "in_force"


def _latest_day(partial: str) -> str:
    """Last calendar day a partial date can mean ("2026" -> 2026-12-31)."""
    parts = partial.split("-")
    if len(parts) == 3:
        return partial
    y = int(parts[0])
    if len(parts) == 2:
        m = int(parts[1])
        return dt.date(y, m, calendar.monthrange(y, m)[1]).isoformat()
    return f"{y:04d}-12-31"
