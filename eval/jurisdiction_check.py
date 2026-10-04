"""[7] Jurisdiction check (BACKEND_PLAN.md 4.7, CONTRACT.md 7-8).

Reads outputs/parcels.json, the sample address CSV, the manifest jurisdictions and
config/jurisdictions.yaml (a Census place-name table, not law), plus
outputs/lookups_internal.json and rules_internal.json for the lookup sanity check.

Hard checks (they set rep.hard_fail):
  - every parcel's state equals the CSV state (must be 100%);
  - no lookup row carries a city rule from a city other than the address's legal city,
    or a state rule from another state.
Everything else is reported for review only. Results go to rep.metrics["jurisdiction"].
"""
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import yaml

from navigator import settings

JURISDICTIONS_YAML = settings.REPO_ROOT / "config" / "jurisdictions.yaml"
MAX_LISTED = 25


def _city_name(jur: str | None) -> str | None:
    return jur.rsplit(", ", 1)[0] if jur else None


def _norm(s: str | None) -> str:
    return " ".join((s or "").split()).casefold()


def analyze(parcels: list[dict[str, Any]], csv_rows: list[dict[str, str]], manifest_jurs: set[str],
            cousub_table: dict[str, dict[str, Any]], crosscheck_states: set[str],
            lookups: dict[str, list[dict[str, Any]]] | None,
            rules: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Pure analysis over already-loaded data. Returns a JSON-able dict."""
    by_id = {str(p.get("address_id")): p for p in parcels}
    csv_by_id = {r["address_id"]: r for r in csv_rows}
    res: dict[str, Any] = {}

    res["by_state"] = dict(sorted(Counter(p.get("state") or "(none)" for p in parcels).items()))
    res["by_city"] = dict(sorted(Counter(p.get("city") or "(no legal city)" for p in parcels).items()))
    res["by_confidence"] = dict(sorted(Counter(p.get("jurisdiction_confidence") or "(none)"
                                               for p in parcels).items()))
    res["by_source"] = dict(sorted(Counter(p.get("jurisdiction_source") or "(none)"
                                           for p in parcels).items()))

    # legal city vs postal city
    differs: dict[str, list[str]] = defaultdict(list)
    with_city = 0
    for p in parcels:
        if not p.get("city"):
            continue
        with_city += 1
        if _norm(_city_name(p["city"])) != _norm(p.get("postal_city")):
            differs[f"{p.get('postal_city')} -> {p['city']}"].append(str(p.get("address_id")))
    res["legal_ne_postal"] = {"num": sum(len(v) for v in differs.values()), "den": with_city,
                              "groups": {k: sorted(v) for k, v in sorted(differs.items())}}

    # no legal city
    res["no_city"] = [{"address_id": str(p.get("address_id")), "state": p.get("state"),
                       "postal_city": p.get("postal_city"),
                       "source": p.get("jurisdiction_source"),
                       "reasons": list(p.get("review_reasons") or []) or ["(no reason recorded)"]}
                      for p in parcels if not p.get("city")]

    # every parcel resolves to a manifest city or is flagged for review
    manifest_cities = {j for j in manifest_jurs if ", " in j}
    outside = [str(p.get("address_id")) for p in parcels if p.get("city") and p["city"] not in manifest_cities]
    res["city_outside_manifest"] = sorted(outside)
    res["unflagged_without_city"] = sorted(str(p.get("address_id")) for p in parcels
                                           if not p.get("city") and not p.get("needs_review"))

    # NJ/MA county subdivision agreement
    agree, den, disagree = 0, 0, []
    for p in parcels:
        if p.get("state") not in crosscheck_states:
            continue
        cousub = (p.get("geoids") or {}).get("county_subdivision")
        if not cousub:
            continue
        den += 1
        sub_city = (cousub_table.get(str(cousub)) or {}).get("jurisdiction")
        if sub_city == p.get("city"):
            agree += 1
        else:
            disagree.append(f"{p.get('address_id')} (place {p.get('city')}, county subdivision "
                            f"{cousub} -> {sub_city or 'not a corpus city'})")
    no_geoid = sum(1 for p in parcels if p.get("state") in crosscheck_states
                   and not (p.get("geoids") or {}).get("county_subdivision"))
    res["cousub"] = {"num": agree, "den": den, "disagree": disagree, "no_geoid": no_geoid,
                     "states": sorted(crosscheck_states)}

    # parcel state == CSV state
    mismatched = []
    for aid, row in csv_by_id.items():
        p = by_id.get(aid)
        if p is None:
            mismatched.append(f"{aid} (no parcel)")
        elif p.get("state") != row.get("state"):
            mismatched.append(f"{aid} (parcel {p.get('state')}, CSV {row.get('state')})")
    extra = sorted(set(by_id) - set(csv_by_id))
    res["state_match"] = {"num": len(csv_by_id) - len(mismatched), "den": len(csv_by_id),
                          "mismatched": mismatched, "extra_parcels": extra}

    # lookup sanity
    if lookups is None or rules is None:
        res["lookup_sanity"] = None
    else:
        rules_by_id = {r.get("team_rule_id"): r for r in rules}
        bad: list[str] = []
        rows_checked = 0
        for aid, rows in lookups.items():
            p = by_id.get(str(aid)) or {}
            for row in rows or []:
                rows_checked += 1
                rid = row.get("team_rule_id")
                rule = rules_by_id.get(rid)
                if rule is None:
                    bad.append(f"{aid}: {rid} not in rules_internal.json")
                    continue
                jur, level = rule.get("jurisdiction"), rule.get("level")
                if level == "city":
                    if jur != p.get("city"):
                        bad.append(f"{aid}: city rule {rid} ({jur}) but legal city is {p.get('city')}")
                elif level == "state":
                    if jur != p.get("state"):
                        bad.append(f"{aid}: state rule {rid} ({jur}) but state is {p.get('state')}")
                else:
                    bad.append(f"{aid}: rule {rid} has level {level!r}")
        res["lookup_sanity"] = {"rows_checked": rows_checked, "violations": bad}
    return res


# ------------------------------------------------------------------ loading


def _read_json(path: Path) -> Any:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _manifest_jurisdictions() -> set[str]:
    try:
        from navigator.ingest.corpus import manifest_rows  # starter + supplement

        rows = manifest_rows().values()
    except Exception:  # noqa: BLE001 - fall back to the starter manifest only
        from navigator import starter

        rows = starter.manifest().values()
    return {j for r in rows if (j := (r.get("jurisdictions") or "").strip())}


def load(out_dir: Path) -> dict[str, Any] | None:
    pdoc = _read_json(out_dir / "parcels.json")
    if pdoc is None:
        return None
    parcels = pdoc["parcels"] if isinstance(pdoc, dict) else pdoc
    with settings.path("addresses").open(encoding="utf-8", newline="") as fh:
        csv_rows = list(csv.DictReader(fh))
    table = yaml.safe_load(JURISDICTIONS_YAML.read_text(encoding="utf-8")) or {}
    ldoc = _read_json(out_dir / "lookups_internal.json")
    rdoc = _read_json(out_dir / "rules_internal.json")
    return analyze(
        parcels, csv_rows, _manifest_jurisdictions(),
        {str(k): v for k, v in (table.get("county_subdivisions") or {}).items()},
        set(table.get("cousub_crosscheck_states") or ()),
        ldoc.get("lookups") if isinstance(ldoc, dict) else None,
        rdoc.get("rules") if isinstance(rdoc, dict) else None,
    )


# ------------------------------------------------------------------ report


def _listed(items: list[str]) -> str:
    shown = ", ".join(items[:MAX_LISTED])
    return shown + (f", ... (+{len(items) - MAX_LISTED} more)" if len(items) > MAX_LISTED else "")


def _fmt_counts(c: dict[str, int]) -> str:
    return ", ".join(f"{k} {v}" for k, v in c.items())


def section(rep: Any, out_dir: Path) -> None:
    rep.lines.append("[7] Jurisdiction check (legal city from Census geographies, never postal city)")
    res = load(Path(out_dir))
    if res is None:
        rep.lines.append("  [n/a ] parcels.json missing; run `python -m navigator geocode`")
        rep.metrics["jurisdiction"] = None
        return
    before = set(rep.metrics)

    rep.lines.append(f"  [info] by state: {_fmt_counts(res['by_state'])}")
    rep.lines.append(f"  [info] by legal city: {_fmt_counts(res['by_city'])}")
    rep.lines.append(f"  [info] by jurisdiction_confidence: {_fmt_counts(res['by_confidence'])}")
    rep.lines.append(f"  [info] by source: {_fmt_counts(res['by_source'])}")

    rep.ratio("jur_state_match", "parcel state equals CSV state", res["state_match"]["num"],
              res["state_match"]["den"], True)
    if res["state_match"]["mismatched"]:
        rep.lines.append("    mismatched: " + _listed(res["state_match"]["mismatched"]))
    if res["state_match"]["extra_parcels"]:
        rep.lines.append("    parcels not in the CSV: " + _listed(res["state_match"]["extra_parcels"]))

    lp = res["legal_ne_postal"]
    rep.ratio("jur_legal_ne_postal", "legal city differs from postal city (of addresses with a legal city)",
              lp["num"], lp["den"], False)
    for group, ids in lp["groups"].items():
        rep.lines.append(f"    {group}: {len(ids)} ({_listed(ids)})")

    rep.lines.append(f"  [info] no legal city: {len(res['no_city'])} (state rules only)")
    for nc in res["no_city"]:
        rep.lines.append(f"    {nc['address_id']} {nc['state']} postal {nc['postal_city']!r} "
                         f"[{nc['source']}]: {'; '.join(nc['reasons'])}")

    rep.check("jur_cities_in_manifest", "no parcel city outside the manifest jurisdictions",
              not res["city_outside_manifest"], _listed(res["city_outside_manifest"]), hard=False)
    rep.check("jur_unresolved_flagged", "every address without a legal city is flagged needs_review",
              not res["unflagged_without_city"], _listed(res["unflagged_without_city"]), hard=False)

    cs = res["cousub"]
    rep.ratio("jur_cousub_agree", f"{'/'.join(cs['states'])} county subdivision agrees with legal city",
              cs["num"], cs["den"], False)
    for d in cs["disagree"][:MAX_LISTED]:
        rep.lines.append(f"    {d}")
    if cs["no_geoid"]:
        rep.lines.append(f"    {cs['no_geoid']} {'/'.join(cs['states'])} addresses have no county "
                         "subdivision (not geocoded)")

    ls = res["lookup_sanity"]
    if ls is None:
        rep.lines.append("  [n/a ] lookup sanity: lookups_internal.json or rules_internal.json missing")
    else:
        rep.check("jur_lookup_sanity",
                  f"lookup rows only from the address's own state and legal city ({ls['rows_checked']} rows)",
                  not ls["violations"], f"{len(ls['violations'])} violations: {_listed(ls['violations'])}"
                  if ls["violations"] else "", hard=True)

    checks = {k: rep.metrics.pop(k) for k in set(rep.metrics) - before}
    rep.metrics["jurisdiction"] = {
        "checks": dict(sorted(checks.items())),
        "by_state": res["by_state"], "by_city": res["by_city"],
        "by_confidence": res["by_confidence"], "by_source": res["by_source"],
        "legal_ne_postal": {"num": lp["num"], "den": lp["den"]},
        "no_city": [nc["address_id"] for nc in res["no_city"]],
        "cousub_disagree": len(cs["disagree"]),
        "lookup_violations": None if ls is None else len(ls["violations"]),
    }
