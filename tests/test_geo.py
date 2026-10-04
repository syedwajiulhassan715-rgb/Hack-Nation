"""Phase 4: geocode, jurisdiction resolution, unit parsing. No network: the Census client
runs offline against the committed cache/geocode/, and any send attempt fails the test."""
import json
from collections import Counter

import pytest

from navigator import settings, starter
from navigator.geo import census, geocode, jurisdictions
from navigator.geo.units import parse_use_description, resolve_units
from navigator.schema.writers import dump_json


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(self, request):
        raise AssertionError(f"test tried to reach the network: {request['endpoint']}")
    monkeypatch.setattr(census.Client, "_send", refuse)


@pytest.fixture(scope="module")
def built():
    client = census.Client(offline=True)
    parcels, extra = geocode.build_parcels(client)
    return parcels, extra, client


# ------------------------------------------------------------------ street helpers


@pytest.mark.parametrize("street,expected", [
    ("6238 DE LONGPRE AVE", (6238, 6238)),
    ("1031-1035 CLINTON ST", (1031, 1035)),
    ("238 & 242 X ST", (238, 242)),
    ("12A MAIN ST", (12, 12)),
    ("322-322.5 X ST", (322, 322)),
    ("WILLOWWOOD ST", None),
])
def test_house_number_range(street, expected):
    assert geocode.house_number_range(street) == expected


def test_number_agrees():
    assert geocode.number_agrees("1031-1035 CLINTON ST", "1035 CLINTON ST, HOBOKEN, NJ, 07030")
    assert geocode.number_agrees("6238 DE LONGPRE AVE", "6238 DE LONGPRE AVE, LOS ANGELES, CA, 90028")
    assert not geocode.number_agrees("6238 DE LONGPRE AVE", "6200 DE LONGPRE AVE, LOS ANGELES, CA, 90028")
    assert not geocode.number_agrees("HARVARD ST", "1 HARVARD ST, BOSTON, MA, 02124")


def test_clean_street_and_retry_queries():
    assert geocode.clean_street("322-322.5 05TH AV.") == "322 5TH AVE"
    assert geocode.clean_street("600 JACKSON/601 HARRISON") == "600 JACKSON"
    qs = geocode.retry_queries({"street_address": "1031-1035 CLINTON ST", "postal_city": "Hoboken",
                                "state": "NJ", "zip": "07030"})
    assert qs == ["1031 CLINTON ST, Hoboken, NJ 07030", "1031-1035 CLINTON ST, Hoboken, NJ 07030",
                  "1031 CLINTON ST, Hoboken, NJ"]


# ------------------------------------------------------------------ census client


def test_cache_miss_offline(tmp_path):
    client = census.Client(offline=True, cache=tmp_path)
    with pytest.raises(census.CacheMiss):
        client.oneline("1 NOWHERE ST, Nowhere, CA")
    assert client.network_calls == 0


def test_cache_key_is_request_content():
    a = {"endpoint": "x", "params": {"a": "1", "b": "2"}}
    b = {"params": {"b": "2", "a": "1"}, "endpoint": "x"}
    assert census.request_key(a) == census.request_key(b)
    assert census.request_key(a) != census.request_key({**a, "params": {"a": "1"}})


def test_parse_batch():
    text = ('"A1","1 X ST, Y, CA, 90001","Match","Exact","1 X ST, Y, CA, 90001",'
            '"-118.1,34.1","1","L","06","037","1","1"\n"A2","2 X ST","No_Match"\n')
    out = census.parse_batch(text)
    assert out["A1"]["lonlat"] == "-118.1,34.1" and out["A1"]["match_type"] == "Exact"
    assert out["A2"]["match"] == "No_Match" and out["A2"]["lonlat"] == ""


def test_committed_cache_is_clean():
    files = sorted(census.cache_dir().glob("*"))
    assert files
    for f in files:
        assert f.suffix == ".json", f
        rec = json.loads(f.read_text(encoding="utf-8"))
        assert census.request_key(rec["request"]) == f.stem
        assert rec["response"].strip()
        if rec["request"]["params"].get("format") == "json":
            assert "result" in json.loads(rec["response"])


# ------------------------------------------------------------------ jurisdictions


def _geo(state="NJ", place=("3432250", "Hoboken city", "Hoboken"),
         cousub=("3401732250", "Hoboken city")):
    g = {"States": [{"GEOID": "34" if state == "NJ" else "06", "STUSAB": state}],
         "Counties": [{"GEOID": "34017"}], "Incorporated Places": [], "County Subdivisions": []}
    if place:
        g["Incorporated Places"] = [{"GEOID": place[0], "NAME": place[1], "BASENAME": place[2]}]
    if cousub:
        g["County Subdivisions"] = [{"GEOID": cousub[0], "NAME": cousub[1]}]
    return g


def test_table_entries_are_manifest_jurisdictions():
    table = jurisdictions.load_table()
    known = jurisdictions.manifest_jurisdictions()
    cities = {e["jurisdiction"] for e in table.places.values()}
    assert cities <= known
    assert cities == {"Los Angeles, CA", "San Francisco, CA", "San Diego, CA", "Berkeley, CA",
                      "Jersey City, NJ", "Hoboken, NJ", "Newark, NJ", "Boston, MA", "Cambridge, MA"}


def test_resolve_place():
    r = jurisdictions.resolve(_geo())
    assert r.city == "Hoboken, NJ" and not r.problems
    assert r.geoids == {"state": "34", "county": "34017", "place": "3432250",
                        "county_subdivision": "3401732250"}


def test_resolve_unknown_place_is_state_only():
    r = jurisdictions.resolve(_geo(place=("3474000", "Union City city", "Union City"),
                                   cousub=("3401774000", "Union City city")))
    assert r.city is None and any("not a city in the corpus" in p for p in r.problems)


def test_resolve_no_place():
    r = jurisdictions.resolve(_geo(place=None, cousub=("3401300000", "Somewhere township")))
    assert r.city is None and any("not inside any Census incorporated place" in p for p in r.problems)


def test_resolve_cousub_disagreement_flagged():
    r = jurisdictions.resolve(_geo(cousub=("3401736000", "Jersey City city")))
    assert r.city == "Hoboken, NJ"
    assert any("disagrees" in p for p in r.problems)


def test_resolve_basename_mismatch_fails_closed():
    r = jurisdictions.resolve(_geo(place=("3432250", "Weehawken city", "Weehawken")))
    assert r.city is None and r.problems


# ------------------------------------------------------------------ units


@pytest.mark.parametrize("desc,state,lo,hi", [
    ("Five or more apartments", "CA", 5, None),
    ("Apartment 5 to 14 Units", "CA", 5, 14),
    ("Apartment 15 Units or more", "CA", 15, None),
    ("TIC Bldg 4 units or less", "CA", None, 4),
    ("SANDAG asr_landuse 14-16 (5+ units)", "CA", 5, None),
    ("APT 7-30 UNITS", "MA", 7, 30),
    ("4-8-UNIT-APT", "MA", 4, 8),
    (">8-UNIT-APT", "MA", 9, None),
    ("SUBSD HOUSING S- 8", "MA", None, None),
    ("3S-B-A-22U", "NJ", 22, 22),
    ("5B-10U-H-BA", "NJ", 10, 10),
    ("3B-7U/4B-24U-G", "NJ", 31, 31),
    ("4 1/2B-10U-BA", "NJ", 10, 10),
    ("3SB2UG", "NJ", None, None),          # ambiguous glued token: fail closed
    ("USCB16UG", "NJ", None, None),
    ("5B-1OU", "NJ", None, None),          # letter O typo
    ("3SB", "NJ", None, None),
    ("Apartments (class 4C)", "NJ", None, None),
    ("Apartment 5 to 14 Units", "NJ", None, None),   # parsers are state-scoped
])
def test_parse_use_description(desc, state, lo, hi):
    r = parse_use_description(desc, state)
    assert (r.units_min, r.units_max) == (lo, hi)


def test_resolve_units_column_wins():
    u = resolve_units("12", "Apartment 5 to 14 Units", "CA")
    assert (u.units, u.units_min, u.units_max, u.units_source) == (12, 12, 12, "units")
    assert not u.review_reasons


def test_resolve_units_conflict_widens_and_flags():
    u = resolve_units("15", "Apartment 5 to 14 Units", "CA")
    assert (u.units, u.units_min, u.units_max) == (15, 5, 15) and u.review_reasons
    u = resolve_units("5", "TIC Bldg 4 units or less", "CA")
    assert (u.units_min, u.units_max) == (None, 5) and u.review_reasons


def test_resolve_units_bad_column_and_description_fallback():
    u = resolve_units("abc", "", "CA")
    assert (u.units, u.units_min, u.units_max, u.units_source) == (None, None, None, None)
    assert u.review_reasons
    u = resolve_units("", "3S-B-A-22U", "NJ")
    assert (u.units, u.units_min, u.units_max, u.units_source) == (None, 22, 22, "use_description")


# ------------------------------------------------------------------ end to end (cached)


def test_build_parcels_offline(built):
    parcels, _, client = built
    assert client.network_calls == 0
    assert [p["address_id"] for p in parcels] == sorted(starter.address_ids())
    assert len(parcels) == 500
    for p in parcels:
        assert list(p) == geocode.FIELDS
        assert p["jurisdiction_confidence"] in ("high", "medium", "low")
        assert p["needs_review"] == bool(p["review_reasons"])
        if p["jurisdiction_confidence"] == "low":
            assert p["needs_review"]
        if p["city"] is None:
            assert "city" in p["missing_facts"] and p["needs_review"]
        if p["units_min"] is None and p["units_max"] is None:
            assert "units" in p["missing_facts"]


def test_legal_city_not_postal_city(built):
    parcels, _, _ = built
    by_id = {p["address_id"]: p for p in parcels}
    # Neighborhood postal names resolve to the incorporated place that contains them.
    neighborhoods = [p for p in parcels if p["postal_city"] in ("Dorchester", "Roxbury", "Brighton")
                     and p["lat"] is not None]
    assert neighborhoods and all(p["city"] == "Boston, MA" for p in neighborhoods)
    # A row with no house number is never placed and never given a guessed city.
    assert by_id["A0098"]["city"] is None and by_id["A0098"]["jurisdiction_source"] == "postal_city_fallback"
    counts = Counter(p["city"] for p in parcels)
    assert counts["Los Angeles, CA"] == 80 and counts["San Francisco, CA"] == 80


def test_output_is_deterministic_and_matches_committed(built, tmp_path):
    parcels, _, _ = built
    out = tmp_path / "parcels.json"
    dump_json({"parcels": parcels}, out)
    committed = settings.path("outputs") / "parcels.json"
    assert out.read_bytes() == committed.read_bytes()
