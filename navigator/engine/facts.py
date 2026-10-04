"""Parcel -> building facts for coverage (BACKEND_PLAN.md 2.6, CONTRACT.md 7).

Input is one record of outputs/parcels.json (Phase 4). Nothing here knows any law: it
only normalises the address data into the fact vocabulary of navigator/schema/facts.py.
Unit counts are an interval [units_min, units_max] (either end may be unknown); a known
`units` value makes both ends equal. The certificate-of-occupancy date is never a fact
of its own: coverage.py derives it from `year_built` per predicate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    text = str(value).strip()
    if not text:
        return None
    try:
        f = float(text)
    except ValueError:
        return None
    return int(f) if f.is_integer() else None


def _str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


@dataclass(frozen=True)
class Facts:
    address_id: str
    state: str
    city: str | None                       # legal city "City, ST", None if outside the 9 cities
    jurisdiction_confidence: str           # "high" | "low"
    jurisdiction_source: str | None
    postal_city: str | None
    year_built: int | None
    units_min: int | None
    units_max: int | None
    units_source: str | None               # "units" | "use_description" | None
    use_description: str | None
    review_reasons: tuple[str, ...] = field(default_factory=tuple)

    @property
    def units_exact(self) -> int | None:
        if self.units_min is not None and self.units_min == self.units_max:
            return self.units_min
        return None

    @property
    def city_confirmed(self) -> bool:
        return self.jurisdiction_confidence == "high"

    def missing(self) -> list[str]:
        out = []
        if self.year_built is None:
            out.append("year_built")
        if self.units_min is None and self.units_max is None:
            out.append("units")
        if self.use_description is None:
            out.append("use_description")
        return out


def parcel_facts(parcel: dict[str, Any]) -> Facts:
    """Normalise one parcels.json record. Unknown values stay None (never guessed)."""
    units = _int(parcel.get("units"))
    lo, hi = _int(parcel.get("units_min")), _int(parcel.get("units_max"))
    source = _str(parcel.get("units_source"))
    if units is not None:
        lo = hi = units
        source = source or "units"
    if lo is not None and hi is not None and lo > hi:
        lo = hi = None                     # contradictory range: treat as unknown
        source = None
    if lo is None and hi is None:
        source = None
    conf = _str(parcel.get("jurisdiction_confidence")) or "low"
    if conf not in ("high", "low"):
        conf = "low"
    return Facts(
        address_id=str(parcel["address_id"]),
        state=str(parcel["state"]).strip(),
        city=_str(parcel.get("city")),
        jurisdiction_confidence=conf,
        jurisdiction_source=_str(parcel.get("jurisdiction_source")),
        postal_city=_str(parcel.get("postal_city")),
        year_built=_int(parcel.get("year_built")),
        units_min=lo,
        units_max=hi,
        units_source=source,
        use_description=_str(parcel.get("use_description")),
        review_reasons=tuple(str(r) for r in parcel.get("review_reasons") or ()),
    )
