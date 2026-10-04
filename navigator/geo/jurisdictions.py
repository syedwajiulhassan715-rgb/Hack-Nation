"""Legal city from Census geographies (BACKEND_PLAN.md 2.7, CONTRACT.md 8).

The legal city is the Census *incorporated place* whose polygon contains the geocoded
point; `postal_city` never decides it (Van Nuys is in Los Angeles, Dorchester in Boston).
config/jurisdictions.yaml maps place GEOIDs to the manifest's jurisdiction strings. It
is a place-name table built from geocoder output, not law, and every entry is checked
here: the jurisdiction must be one the corpus manifest names, and it must equal the
Census BASENAME plus state abbreviation of the place it is keyed by.

In states whose county subdivisions are municipalities (`cousub_crosscheck_states`, NJ
and MA), the county subdivision must agree with the place; disagreement is flagged.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from navigator import settings, starter

CONFIG = settings.REPO_ROOT / "config" / "jurisdictions.yaml"


@lru_cache(maxsize=1)
def manifest_jurisdictions() -> frozenset[str]:
    """Every jurisdiction string the corpus manifest uses (states and cities)."""
    return frozenset(j for row in starter.manifest().values() if (j := row["jurisdictions"].strip()))


@dataclass(frozen=True)
class JurisdictionTable:
    places: dict[str, dict[str, str]]
    county_subdivisions: dict[str, dict[str, str]]
    cousub_crosscheck_states: frozenset[str]


@lru_cache(maxsize=4)
def load_table(path: Path = CONFIG) -> JurisdictionTable:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    known = manifest_jurisdictions()
    problems = []
    for section in ("places", "county_subdivisions"):
        for geoid, entry in (data.get(section) or {}).items():
            j = entry.get("jurisdiction")
            if j is not None and j not in known:
                problems.append(f"{section}.{geoid}: {j!r} is not a jurisdiction in the corpus manifest")
    if problems:
        raise ValueError("config/jurisdictions.yaml: " + "; ".join(problems))
    return JurisdictionTable(
        places={str(k): v for k, v in (data.get("places") or {}).items()},
        county_subdivisions={str(k): v for k, v in (data.get("county_subdivisions") or {}).items()},
        cousub_crosscheck_states=frozenset(data.get("cousub_crosscheck_states") or ()),
    )


@dataclass
class Resolution:
    city: str | None
    state: str | None                       # state abbreviation from Census
    geoids: dict[str, str | None]
    place_name: str | None                  # Census NAME, e.g. "Los Angeles city"
    cousub_name: str | None
    problems: list[str] = field(default_factory=list)   # each one means needs_review


def _first(geo: dict[str, list[dict[str, Any]]], layer: str) -> dict[str, Any] | None:
    items = geo.get(layer) or []
    return items[0] if items else None


def resolve(geo: dict[str, list[dict[str, Any]]], table: JurisdictionTable | None = None) -> Resolution:
    """Census coordinates-lookup geographies -> legal city (or None, with problems)."""
    table = table or load_table()
    st, county = _first(geo, "States"), _first(geo, "Counties")
    place, cousub = _first(geo, "Incorporated Places"), _first(geo, "County Subdivisions")
    abbr = st.get("STUSAB") if st else None
    res = Resolution(
        city=None, state=abbr,
        geoids={"state": st and st["GEOID"], "county": county and county["GEOID"],
                "place": place and place["GEOID"], "county_subdivision": cousub and cousub["GEOID"]},
        place_name=place and place.get("NAME"), cousub_name=cousub and cousub.get("NAME"),
    )
    if len(geo.get("Incorporated Places") or []) > 1:
        res.problems.append("point falls in more than one incorporated place")
    if place is None:
        res.problems.append("point is not inside any Census incorporated place"
                            + (f" (county subdivision {res.cousub_name!r})" if res.cousub_name else "")
                            + "; state rules only")
    else:
        entry = table.places.get(place["GEOID"])
        if entry is None or entry.get("jurisdiction") is None:
            res.problems.append(f"Census place {place.get('NAME')!r} ({place['GEOID']}) is not a "
                                "city in the corpus; state rules only")
        else:
            expected = f"{place.get('BASENAME')}, {abbr}"
            if entry["jurisdiction"] != expected:
                res.problems.append(f"jurisdictions.yaml maps {place['GEOID']} to "
                                    f"{entry['jurisdiction']!r} but Census names it {expected!r}")
            else:
                res.city = entry["jurisdiction"]
    if abbr in table.cousub_crosscheck_states:
        sub = table.county_subdivisions.get(cousub["GEOID"]) if cousub else None
        sub_city = sub.get("jurisdiction") if sub else None
        if sub_city != res.city:
            res.problems.append(f"county subdivision {res.cousub_name!r} "
                                f"({'not a corpus city' if sub_city is None else sub_city}) "
                                f"disagrees with incorporated place {res.place_name!r}")
    return res
