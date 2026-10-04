"""Geocode: sample_addresses.csv -> outputs/parcels.json (BACKEND_PLAN.md 2.6, 2.7).

1. One Census batch call for all rows (street, postal city, state, zip).
2. Rows the batch did not match (No_Match / Tie) are retried with the single-line
   endpoint, first as given, then with the house number and street cleaned (number ranges
   -> first number, "05TH" -> "5TH", "AV" -> "AVE", "A/B" -> "A"), then without the zip.
3. Every point is looked up in the Census geographies (state, county, incorporated place,
   county subdivision); the legal city is the incorporated place (jurisdictions.py).
4. Units come from the `units` column, else from `use_description` (units.py).

Fail closed: a row is never dropped. Unmatched rows keep the postal city only if it is a
corpus city, with `jurisdiction_confidence: "low"`; points outside every corpus city get
`city: null` (state rules only). Both carry `needs_review` and a reason.

All Census responses are cached in cache/geocode/ (commit it); a cached run makes no
network calls and writes a byte-identical parcels.json.
"""
from __future__ import annotations

import os
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from navigator import audit, settings, starter
from navigator.geo import census, jurisdictions, units as unitmod
from navigator.schema.writers import dump_json

FIELDS = ["address_id", "street_address", "postal_city", "state", "city", "lat", "lng", "geoids",
          "jurisdiction_confidence", "jurisdiction_source", "year_built", "units", "units_min",
          "units_max", "units_source", "use_code", "use_description", "missing_facts",
          "needs_review", "review_reasons"]


@dataclass(frozen=True)
class Candidate:
    lon: str
    lat: str
    matched_address: str
    source: str          # "census_batch" | "census_single_line"
    exact: bool


# ------------------------------------------------------------------ street cleanup


def clean_street(street: str) -> str:
    s = street.strip()
    s = s.split("/")[0].strip()                                       # "600 JACKSON/601 HARRISON"
    s = re.sub(r"^(\d+)(?:\.\d+)?\s*-\s*\d+(?:\.\d+)?(?=\s)", r"\1", s)  # "322-322.5 X" -> "322 X"
    s = re.sub(r"\b0+(\d+(?:ST|ND|RD|TH))\b", r"\1", s, flags=re.I)   # "05TH" -> "5TH"
    s = re.sub(r"\bAV\b", "AVE", s)
    s = re.sub(r"\.(?=\s|$)", "", s)                                  # "AVE." -> "AVE"
    return re.sub(r"\s+", " ", s)


def has_house_number(street: str) -> bool:
    return bool(re.match(r"\s*\d", street))


def house_number_range(street: str) -> tuple[int, int] | None:
    """Leading house number(s): "1031-1035 X" -> (1031, 1035), "238 & 242 X" -> (238, 242)."""
    m = re.match(r"\s*(\d+)[A-Z]?(?:\.\d+)?(?:\s*(?:-|&)\s*(\d+)(?:\.\d+)?)?\b", street, re.I)
    if not m:
        return None
    nums = [int(g) for g in m.groups() if g]
    return min(nums), max(nums)


def number_agrees(street: str, matched: str) -> bool:
    """The geocoder's matched house number must fall within the input's number(s)."""
    rng, m = house_number_range(street), re.match(r"\s*(\d+)", matched)
    return bool(rng and m and rng[0] <= int(m.group(1)) <= rng[1])


def retry_queries(row: dict[str, str]) -> list[str]:
    street, city, state, zip_ = row["street_address"], row["postal_city"], row["state"], row["zip"].strip()
    cleaned = clean_street(street)
    out: list[str] = []
    for s, z in ((cleaned, zip_), (street.strip(), zip_), (cleaned, "")):
        q = f"{s}, {city}, {state}" + (f" {z}" if z else "")
        if q not in out:
            out.append(q)
    return out


def locate(row: dict[str, str], batch_row: dict[str, str] | None,
           client: census.Client) -> tuple[list[Candidate], list[str]]:
    """Candidate points for one address, plus notes on how they were found."""
    notes: list[str] = []
    if batch_row and batch_row["match"] == "Match" and batch_row["lonlat"]:
        if number_agrees(row["street_address"], batch_row["matched_address"]):
            lon, lat = batch_row["lonlat"].split(",")
            return [Candidate(lon, lat, batch_row["matched_address"], "census_batch",
                              batch_row["match_type"] == "Exact")], notes
        notes.append(f"batch match {batch_row['matched_address']!r} has a different house number; ignored")
    else:
        notes.append(f"batch geocode: {batch_row['match'] if batch_row else 'missing from batch response'}")
    if not has_house_number(row["street_address"]):
        notes.append("street address has no house number, so it cannot be placed on a parcel")
        return [], notes
    for q in retry_queries(row):
        found = client.oneline(q)
        matches = [m for m in found if number_agrees(row["street_address"], m["matchedAddress"])]
        if len(matches) < len(found):
            notes.append(f"single-line matches with a different house number ignored for {q!r}")
        if matches:
            return [Candidate(repr(float(m["coordinates"]["x"])), repr(float(m["coordinates"]["y"])),
                              m["matchedAddress"], "census_single_line", False) for m in matches], notes
        notes.append(f"single-line geocode found no match for {q!r}")
    return [], notes


# ------------------------------------------------------------------ one parcel


def _zip_of(matched: str) -> str:
    m = re.search(r"(\d{5})\s*$", matched)
    return m.group(1) if m else ""


def build_parcel(row: dict[str, str], cands: list[Candidate], notes: list[str],
                 geo_by_point: dict[tuple[str, str], dict[str, Any]],
                 table: jurisdictions.JurisdictionTable) -> tuple[dict[str, Any], dict[str, Any]]:
    """-> (parcel, audit fields)."""
    reasons: list[str] = []
    known = jurisdictions.manifest_jurisdictions()
    postal_jur = f"{row['postal_city'].strip()}, {row['state'].strip()}"
    lat = lng = None
    geoids: dict[str, str | None] = {"state": None, "county": None, "place": None, "county_subdivision": None}
    city: str | None = None
    detail = ""

    if not cands:
        source = "postal_city_fallback"
        confidence = "low"
        reasons.extend(notes)
        if postal_jur in known:
            city = postal_jur
            reasons.append(f"address not geocoded; city taken from postal city {row['postal_city']!r} "
                           "without verification (low confidence)")
        else:
            reasons.append(f"address not geocoded and postal city {row['postal_city']!r} is not a city "
                           "in the corpus; city rules could not be checked")
    else:
        source = cands[0].source
        resolved = [(c, jurisdictions.resolve(geo_by_point[(c.lon, c.lat)], table)) for c in cands]
        cities = sorted({r.city or "" for _, r in resolved})
        if len(resolved) > 1 and len(cities) > 1:
            confidence = "low"
            reasons.extend(notes)
            reasons.append("geocoder returned several matches in different jurisdictions: "
                           + "; ".join(f"{c.matched_address} -> {r.city or r.place_name or 'no place'}"
                                       for c, r in resolved))
            chosen = None
        else:
            # Same jurisdiction for every candidate: prefer the one in the input zip, else the first.
            in_zip = [cr for cr in resolved if row["zip"].strip() and _zip_of(cr[0].matched_address) == row["zip"].strip()]
            chosen = (in_zip or resolved)[0]
            confidence = "high" if (source == "census_batch" and chosen[0].exact) else "medium"
            detail = f"{chosen[0].matched_address} ({source}{', exact' if chosen[0].exact else ''})"
            if len(resolved) > 1:
                detail += f"; {len(resolved)} candidate points, all in the same jurisdiction"
        if chosen is not None:
            cand, res = chosen
            lng, lat = float(cand.lon), float(cand.lat)
            geoids = res.geoids
            city = res.city
            if res.state != row["state"].strip():
                reasons.append(f"Census state {res.state!r} differs from the address state {row['state']!r}")
                city = None
                confidence = "low"
            if res.problems:
                reasons.extend(notes)
                reasons.extend(res.problems)
                if confidence != "low":
                    confidence = "medium"
            if city and postal_jur in known and postal_jur != city:
                reasons.append(f"postal city {postal_jur!r} is a different corpus city than the Census "
                               f"incorporated place {city!r}; place used")
                confidence = "medium"

    unit = unitmod.resolve_units(row["units"], row["use_description"], row["state"])
    reasons.extend(unit.review_reasons)
    year = row["year_built"].strip()
    year_built = int(year) if year.isdigit() else None
    missing = []
    if year_built is None:
        missing.append("year_built")
    if unit.units_min is None and unit.units_max is None:
        missing.append("units")
    if city is None:
        missing.append("city")

    parcel = {
        "address_id": row["address_id"],
        "street_address": row["street_address"],
        "postal_city": row["postal_city"],
        "state": row["state"],
        "city": city,
        "lat": lat,
        "lng": lng,
        "geoids": geoids,
        "jurisdiction_confidence": confidence,
        "jurisdiction_source": source,
        "year_built": year_built,
        "units": unit.units,
        "units_min": unit.units_min,
        "units_max": unit.units_max,
        "units_source": unit.units_source,
        "use_code": row["use_code"],
        "use_description": row["use_description"],
        "missing_facts": missing,
        "needs_review": bool(reasons),
        "review_reasons": reasons,
    }
    assert list(parcel) == FIELDS
    return parcel, {"match": detail or None, "units_note": unit.note}


# ------------------------------------------------------------------ run


def build_parcels(client: census.Client, rows: list[dict[str, str]] | None = None,
                  table: jurisdictions.JurisdictionTable | None = None,
                  workers: int = 8) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    rows = rows if rows is not None else starter.addresses()
    table = table or jurisdictions.load_table()
    batch = client.batch([(r["address_id"], r["street_address"], r["postal_city"], r["state"], r["zip"])
                          for r in rows])
    located = {r["address_id"]: locate(r, batch.get(r["address_id"]), client) for r in rows}
    points = sorted({(c.lon, c.lat) for cands, _ in located.values() for c in cands})
    with ThreadPoolExecutor(max_workers=workers) as pool:
        geos = list(pool.map(lambda p: client.coordinates(*p), points))
    geo_by_point = dict(zip(points, geos))
    parcels, extra = [], {}
    for r in rows:
        cands, notes = located[r["address_id"]]
        parcel, info = build_parcel(r, cands, notes, geo_by_point, table)
        parcels.append(parcel)
        extra[r["address_id"]] = info
    parcels.sort(key=lambda p: p["address_id"])
    return parcels, extra


def summarize(parcels: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(parcels)
    by_conf = Counter(p["jurisdiction_confidence"] for p in parcels)
    by_src = Counter(p["jurisdiction_source"] for p in parcels)
    by_city = Counter(p["city"] or "(none)" for p in parcels)
    differs = sum(1 for p in parcels if p["city"] and p["city"] != f"{p['postal_city']}, {p['state']}")
    with_range = sum(1 for p in parcels if p["units_min"] is not None or p["units_max"] is not None)
    return {
        "parcels": n,
        "matched": n - by_src.get("postal_city_fallback", 0),
        "unmatched": by_src.get("postal_city_fallback", 0),
        "by_source": dict(sorted(by_src.items())),
        "by_confidence": dict(sorted(by_conf.items())),
        "by_city": dict(sorted(by_city.items())),
        "legal_city_differs_from_postal": differs,
        "units_known": with_range,
        "units_from_column": sum(1 for p in parcels if p["units_source"] == "units"),
        "units_from_description": sum(1 for p in parcels if p["units_source"] == "use_description"),
        "needs_review": sum(1 for p in parcels if p["needs_review"]),
    }


def output_path() -> Path:
    return settings.path("outputs") / "parcels.json"


def run(offline: bool | None = None) -> Path:
    if offline is None:
        offline = os.environ.get("NAVIGATOR_GEOCODE_OFFLINE", "") == "1"
    client = census.Client(offline=offline)
    parcels, extra = build_parcels(client)
    expected = starter.address_ids()
    if sorted(p["address_id"] for p in parcels) != sorted(expected):
        raise RuntimeError("parcels do not cover every address id exactly once")
    path = output_path()
    dump_json({"parcels": parcels}, path)

    for p in parcels:
        if p["needs_review"] or p["jurisdiction_confidence"] != "high":
            audit.log("geocode", "needs_review" if p["needs_review"] else p["jurisdiction_confidence"],
                      "; ".join(p["review_reasons"]) or None, address_id=p["address_id"],
                      city=p["city"], confidence=p["jurisdiction_confidence"],
                      source=p["jurisdiction_source"], match=extra[p["address_id"]]["match"])
    s = summarize(parcels)
    audit.log("geocode", "summary", None, network_calls=client.network_calls,
              cache_hits=client.cache_hits, **s)
    cities = ", ".join(f"{k} {v}" for k, v in s["by_city"].items())
    print(f"geocode: {s['parcels']} parcels, matched {s['matched']}, unmatched {s['unmatched']} "
          f"(confidence {s['by_confidence']}); cities: {cities}; legal city differs from postal "
          f"city for {s['legal_city_differs_from_postal']}; units known for {s['units_known']} "
          f"({s['units_from_column']} column, {s['units_from_description']} use_description); "
          f"needs_review {s['needs_review']}; network calls {client.network_calls} -> {path}")
    return path
