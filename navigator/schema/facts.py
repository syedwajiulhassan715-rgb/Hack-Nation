"""Facts a coverage predicate may reference (BACKEND_PLAN.md 2.6).

This is a vocabulary, not law: it names building facts, never thresholds or dates.
`AVAILABLE` facts come from sample_addresses.csv (or are derived from it);
`NOT_AVAILABLE` facts are legitimate coverage conditions the data cannot answer, so the
engine evaluates them as UNKNOWN and names the missing fact. A predicate that uses any
other fact name is dropped by verify and the rule is marked needs_review.

Date facts (`DATE_FACTS`) may also be compared with a date relative to the query date,
`{"years_before_query_date": N}`, for rolling conditions such as "a certificate of
occupancy issued within the previous N years". N comes from the rule text; the query date
comes from the lookup, so the same rule can give different answers on different dates.

`NOT_PRESUMED` facts are never presumed absent by the coverage engine (coverage.py): they
are common statuses (a unit under a local rent-control ordinance), not rare special cases,
so a condition on them always stays UNKNOWN.
"""
from __future__ import annotations

from typing import Any

AVAILABLE: dict[str, str] = {
    "units": "number of residential units in the building (integer)",
    "year_built": "year the building was built (integer)",
    "certificate_of_occupancy_date": "date of the first certificate of occupancy (YYYY-MM-DD); "
                                     "only estimated from year_built",
    "use_description": "assessor land-use description text",
}

NOT_AVAILABLE: dict[str, str] = {
    "owner_type": "kind of owner, e.g. natural person, corporation, REIT, public agency",
    "owner_occupied": "owner lives in the building (boolean)",
    "owner_units_owned": "number of units the owner holds in total (integer)",
    "separately_alienable": "unit can be sold separately, e.g. single-family home or condo (boolean)",
    "government_owned_or_subsidized": "publicly owned or rent-restricted affordable housing (boolean)",
    "deed_restricted_affordable": "deed-restricted affordable housing (boolean)",
    "dormitory_or_institutional": "dormitory, hospital, care facility, hotel or similar (boolean)",
    "shared_living_with_owner": "tenant shares bathroom or kitchen with the owner (boolean)",
    "tenancy_months": "how long the current tenant has occupied the unit (number)",
    "rent_amount": "current monthly rent (number)",
    "tenant_income_source": "tenant's lawful source of income",
    "unit_is_furnished": "unit is rented furnished (boolean)",
    "subject_to_local_rent_control": "unit is regulated by a local rent control or rent "
                                     "stabilization ordinance (boolean); use only when the text "
                                     "does not say which buildings that ordinance covers",
}

# Facts holding a date (YYYY-MM-DD) or a year; they also accept a relative value.
DATE_FACTS = {"certificate_of_occupancy_date", "year_built"}
RELATIVE_KEY = "years_before_query_date"
# Never presumed absent by the engine's lenient pass (see module docstring).
NOT_PRESUMED = {"subject_to_local_rent_control"}

ALLOWED = {**AVAILABLE, **NOT_AVAILABLE}
OPS = {"<", "<=", ">", ">=", "==", "!=", "in", "not_in"}
ORDER_OPS = {"<", "<=", ">", ">="}


def relative_years(value: Any) -> int | None:
    """N for a relative date value {"years_before_query_date": N}, else None."""
    if isinstance(value, dict) and set(value) == {RELATIVE_KEY}:
        n = value[RELATIVE_KEY]
        if isinstance(n, int) and not isinstance(n, bool) and n > 0:
            return n
    return None


def predicate_errors(node: Any, path: str = "$") -> list[str]:
    """Structural check of a predicate tree; returns problems, empty if valid.

    Forms: {"fact", "op", "value"} | {"all": [...]} | {"any": [...]} | {"not": {...}}.
    """
    if not isinstance(node, dict):
        return [f"{path}: not an object"]
    keys = set(node)
    if keys in ({"all"}, {"any"}):
        (k,) = keys
        items = node[k]
        if not isinstance(items, list) or not items:
            return [f"{path}.{k}: must be a non-empty list"]
        return [e for i, item in enumerate(items) for e in predicate_errors(item, f"{path}.{k}[{i}]")]
    if keys == {"not"}:
        return predicate_errors(node["not"], f"{path}.not")
    if keys == {"fact", "op", "value"}:
        errs = []
        if node["fact"] not in ALLOWED:
            errs.append(f"{path}: unknown fact {node['fact']!r}")
        if node["op"] not in OPS:
            errs.append(f"{path}: unknown op {node['op']!r}")
        if node["op"] in ("in", "not_in") and not isinstance(node["value"], list):
            errs.append(f"{path}: op {node['op']} needs a list value")
        if isinstance(node["value"], dict):
            if node["fact"] not in DATE_FACTS:
                errs.append(f"{path}: a relative date value needs a date fact, not {node['fact']!r}")
            elif node["op"] not in ORDER_OPS:
                errs.append(f"{path}: a relative date value needs one of {sorted(ORDER_OPS)}")
            elif relative_years(node["value"]) is None:
                errs.append(f'{path}: relative date value must be {{"{RELATIVE_KEY}": <positive integer>}}')
        return errs
    return [f"{path}: unexpected keys {sorted(keys)}"]


def describe() -> str:
    """Fact list as it appears in the extraction prompt."""
    lines = ["Facts the data has:"]
    lines += [f"- `{k}`: {v}" for k, v in AVAILABLE.items()]
    lines.append("Facts the data does NOT have (still use them when the law depends on them; "
                 "the answer will be 'unknown'):")
    lines += [f"- `{k}`: {v}" for k, v in NOT_AVAILABLE.items()]
    lines.append("Date facts (" + ", ".join(f"`{k}`" for k in sorted(DATE_FACTS)) + ") also accept a "
                 f'value relative to the query date, `{{"{RELATIVE_KEY}": N}}`, with < <= > >=.')
    return "\n".join(lines)
