"""Verify gates: span matching, number checks, predicates, citation keys, merging. No LLM."""
import pytest

from navigator.schema import facts
from navigator.verify import gates
from navigator.verify.spans import find_span, numbers_supported

pytestmark = pytest.mark.smoke

TEXT = ("SOURCE: x\nRETRIEVED: y\n\n(a) A landlord shall not  charge\na deposit "
        "of more than one and one‑half months’ rent.\n(b) Regu-\nlation applies "
        "to § 12.5 units.")
BODY = TEXT.index("(a)")


def test_exact():
    q = "(a) A landlord shall not  charge"
    s, e, m = find_span(TEXT, q, BODY)
    assert m == "exact" and TEXT[s:e] == q


def test_whitespace_normalized_maps_to_file_offsets():
    q = "A landlord shall not charge a deposit"
    s, e, m = find_span(TEXT, q, BODY)
    assert m == "normalized"
    assert TEXT[s:e] == "A landlord shall not  charge\na deposit"


def test_tolerant_quotes_dashes_hyphenation_section_sign():
    s, e, m = find_span(TEXT, "one and one-half months' rent.", BODY)
    assert m == "tolerant" and TEXT[s:e].endswith("rent.")
    assert find_span(TEXT, "Regulation applies to §12.5 units.", BODY)[2] == "tolerant"


def test_changed_word_is_rejected():
    assert find_span(TEXT, "A landlord shall not charge a fee", BODY) is None


def test_short_quote_is_rejected():
    assert find_span(TEXT, "landlord", BODY) is None


def test_header_is_not_searched():
    assert find_span(TEXT, "SOURCE: x\nRETRIEVED: y", BODY) is None


def test_numbers_supported():
    assert numbers_supported("1.5 months' rent", "one and one-half months") == []
    assert numbers_supported("cap of 5% plus CPI, max 10%", "5 percent ... 10 percent") == []
    assert numbers_supported("$75 fee", "a reasonable fee") == ["75"]


@pytest.mark.parametrize("pred,ok", [
    ({"fact": "units", "op": ">=", "value": 3}, True),
    ({"all": [{"fact": "units", "op": ">", "value": 2},
              {"not": {"fact": "owner_occupied", "op": "==", "value": True}}]}, True),
    ({"fact": "zip", "op": "==", "value": "94110"}, False),
    ({"fact": "units", "op": "~", "value": 3}, False),
    ({"any": []}, False),
    ({"fact": "use_description", "op": "in", "value": "APT"}, False),
])
def test_predicate_validation(pred, ok):
    assert (facts.predicate_errors(pred) == []) is ok


def test_citation_key_matches_different_spellings():
    assert gates.citation_key("Civil Code Section 1947.12 (Stats. 2023)") == \
        gates.citation_key("Cal. Civ. Code § 1947.12") == "1947.12"
    assert gates.citation_key("Bill S.2983") == gates.citation_key("S 2983") == "s2983"


def _item(doc, start, end, cite="Sec. 1.2", cat="security_deposits", jur="NJ", cid="x"):
    return {"c": {"source_doc_id": doc, "category": cat, "citation": cite, "candidate_id": cid,
                  "source_type": "official"},
            "v": {"jur": jur, "start": start, "end": end, "match": "exact", "quote": "q" * (end - start)}}


def test_merge_overlapping_spans_in_one_document():
    groups = gates.merge([_item("D1", 0, 50, cid="a"), _item("D1", 40, 90, cid="b")])
    assert len(groups) == 1


def test_no_merge_for_separate_rules_in_one_document():
    groups = gates.merge([_item("D1", 0, 50, cid="a"), _item("D1", 100, 150, cid="b")])
    assert len(groups) == 2


def test_merge_one_to_one_across_documents():
    assert len(gates.merge([_item("D1", 0, 50, cid="a"), _item("D2", 0, 50, cid="b")])) == 1


def test_no_merge_when_cross_document_match_is_ambiguous():
    groups = gates.merge([_item("D1", 0, 50, cid="a"), _item("D1", 100, 150, cid="b"),
                          _item("D2", 0, 50, cid="c")])
    assert len(groups) == 3
