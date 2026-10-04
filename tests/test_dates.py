"""Date rules (BACKEND_PLAN.md 2.4). Phrases are fixtures copied from corpus text."""
import datetime as dt

import pytest

from navigator.extract import dates


def r(phrase, anchor=None, jurisdiction="NJ", level="state", status_hint="enacted"):
    return dates.resolve(phrase, anchor, jurisdiction=jurisdiction, level=level, status_hint=status_hint)


def test_explicit_date():
    res = r("went into effect on October 14, 2024", jurisdiction="San Francisco, CA", level="city")
    assert (res.date, res.method, res.review_reasons) == ("2024-10-14", "explicit_date", [])


def test_operative_sentence():
    assert r("This section shall become operative on April 1, 2024.").date == "2024-04-01"


def test_first_day_of_twelfth_month_after_enactment():
    res = r("shall take effect on the first day of the twelfth month next following the date of enactment",
            "Approved July 20, 2026")
    assert res.date == "2027-07-01"
    assert res.method == "first_day_of_nth_month_after(anchor, 12)"


def test_relative_without_anchor_fails_closed():
    res = r("shall take effect on the first day of the twelfth month next following the date of enactment")
    assert res.date is None and res.review_reasons


def test_days_after():
    assert r("shall take effect 90 days after its approval", "approved March 3, 2025").date == "2025-06-01"
    assert r("shall take effect on the 30th day after enactment", "enacted 1/10/2026").date == "2026-02-09"
    assert r("shall take effect ninety days after enactment", "enacted 1/10/2026").date == "2026-04-10"


def test_ca_default_flags_review():
    res = r(None, "Chaptered by Secretary of State 10/06/25", jurisdiction="CA")
    assert res.date == "2026-01-01"
    assert res.method.startswith("ca_default_jan1_next_year")
    assert res.review_reasons and res.confidence_penalty > 0


def test_ca_default_only_for_ca_state_enacted():
    assert r(None, "Chaptered 10/06/25", jurisdiction="NJ").date is None
    assert r(None, "Chaptered 10/06/25", jurisdiction="CA", status_hint="bill_or_proposal").date is None


def test_sunset_date_is_not_the_start_date():
    res = r("This section shall become operative on April 1, 2024, and shall remain in effect "
            "only until January 1, 2030, and as of that date is repealed.")
    assert res.date == "2024-04-01"


def test_ambiguous_dates_fail_closed():
    res = r("Adopted May 5, 2025; amended June 9, 2025")
    assert res.date is None and res.review_reasons


def test_dash_numeric_date():
    assert r("effective 6-24-2023", jurisdiction="San Diego, CA", level="city").date == "2023-06-24"


@pytest.mark.parametrize("phrase,start", [
    ("3/01/26 – 2/28/27", "2026-03-01"),
    ("March 1, 2026 – February 28, 2027", "2026-03-01"),
    ("effective March 1, 2026 through February 28, 2027", "2026-03-01"),
    ("July 1, 2025, through June 30, 2026", "2025-07-01"),
])
def test_period_takes_start_date(phrase, start):
    res = r(phrase)
    assert (res.date, res.method, res.review_reasons) == (start, "date_range_start", [])
    assert res.notes


def test_ordinal_day_words():
    phrase = "will take effect and be in force on the thirtieth day from and after its final passage."
    assert r(phrase, "final passage on June 2, 2025").date == "2025-07-02"
    assert r(phrase).date is None


def test_month_precision():
    assert r("effective January 2026").date == "2026-01"


def test_missing_date_enacted_is_noted_not_flagged():
    res = r(None)
    assert res.date is None and res.review_reasons == []
    assert res.notes == ["effective date not stated in source text"] and res.confidence_penalty > 0


@pytest.mark.parametrize("hint,eff,as_of,expected", [
    ("bill_or_proposal", None, "2026-10-01", "pending"),
    ("failed", None, "2026-10-01", "failed"),
    ("enacted", "2027-07-01", "2026-10-01", "not_yet_effective"),
    ("enacted", "2027-07-01", "2027-07-02", "in_force"),
    ("enacted", "2026-01-01", "2025-12-31", "not_yet_effective"),
    ("enacted", "2026-01-01", "2026-01-02", "in_force"),
    ("enacted", "2026-01-01", "2026-01-01", "in_force"),
    ("enacted", "2026-01", "2026-01-15", "not_yet_effective"),
    ("enacted", "2026-01", "2026-02-01", "in_force"),
    ("enacted", None, "2026-10-01", "in_force"),
])
def test_status_on(hint, eff, as_of, expected):
    assert dates.status_on(hint, eff, as_of) == expected


def test_nth_month_wraps_year():
    assert dates.first_day_of_nth_month_after(dt.date(2026, 7, 20), 12) == dt.date(2027, 7, 1)
    assert dates.first_day_of_nth_month_after(dt.date(2026, 11, 30), 3) == dt.date(2027, 2, 1)


# ------------------------------------------------------------------ chaptering line (document anchor)


def test_chaptering_record_single_dated_line():
    text = "Bill history\n10/06/25 - Chaptered\n09/12/25 - Enrolled\n"
    rec = dates.chaptering_record(text)
    assert rec == "10/06/25 - Chaptered"
    res = r(None, rec, jurisdiction="CA")
    assert res.date == "2026-01-01" and res.method == "ca_default_jan1_next_year(chaptered)"
    assert res.review_reasons  # a default not stated in the text is always flagged


def test_chaptering_record_needs_a_date_and_exactly_one_line():
    assert dates.chaptering_record("cross-reference chaptered bills") is None
    assert dates.chaptering_record("10/06/25 - Chaptered\n10/07/24 - Chaptered") is None


def test_chaptering_anchor_gives_no_date_outside_ca():
    assert r(None, "10/06/25 - Chaptered", jurisdiction="NJ").date is None
