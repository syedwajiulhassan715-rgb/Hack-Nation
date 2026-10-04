"""Eval section [4]: gold set (rules + addresses). BACKEND_PLAN.md 4.4.

Evaluation only; the pipeline never imports this module or reads eval/gold/.

Gold rules are matched to our rules (outputs/rules_internal.json) by document and text
location: the gold `anchor_quote` and our `quoted_span` are both found in the same
whitespace-normalized document text, and they match if the two stretches overlap or lie
within MATCH_GAP characters of each other. team_rule_id is never used, since verify
renumbers rules on each run.

None of these numbers are hard checks: `rep.hard_fail` is never set. Metrics go under
`rep.metrics["gold"]`. Until both gold files have `reviewed_by` set, every line says
"draft gold, unreviewed".
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Callable

GOLD_DIR = Path(__file__).parent / "gold"
RULES_FILE = "rules.yaml"
ADDRESSES_FILE = "addresses.yaml"

MATCH_GAP = 200  # chars between anchor and quoted_span still counted as the same provision
RULE_FIELDS = ("jurisdiction", "level", "category", "status", "effective_date")
STATUSES = {"in_force", "not_yet_effective", "pending", "failed"}
LEVELS = {"state", "city"}
CATEGORIES = {"rent_increase_limits", "just_cause_eviction", "security_deposits",
              "application_screening_fees", "screening_restrictions", "algorithmic_rent_setting"}
RESULTS = {"applies", "unknown", "superseded", "not_yet_effective", "pending", "absent"}
DATE_RE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")

_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"',
                         " ": " ", "­": "", "–": "-", "—": "-"})


# ------------------------------------------------------------------------ text helpers
def norm(text: str) -> str:
    """NFC, straight quotes and dashes, single spaces. Used on both sides of every match."""
    text = unicodedata.normalize("NFC", text).translate(_QUOTES)
    return re.sub(r"\s+", " ", text).strip()


def doc_body(raw: str | None) -> str | None:
    """Normalized document text without the SOURCE/RETRIEVED header."""
    if raw is None:
        return None
    if raw.startswith("SOURCE:"):
        parts = raw.split("\n", 3)
        raw = parts[3] if len(parts) == 4 else ""
    return norm(raw)


def locate(needle: str | None, body: str | None) -> tuple[int, int] | None:
    """(start, end) of needle in body, both normalized; falls back to the needle's first
    60 characters so a span with a damaged tail still has a location."""
    if not needle or not body:
        return None
    n = norm(needle)
    i = body.find(n)
    if i >= 0:
        return i, i + len(n)
    head = n[:60]
    if len(head) >= 20:
        i = body.find(head)
        if i >= 0:
            return i, i + len(n)
    return None


def locate_all(needle: str | None, body: str | None) -> list[tuple[int, int]]:
    """Every occurrence of needle in body (normalized); [locate()] as a fallback."""
    if not needle or not body:
        return []
    n = norm(needle)
    out, i = [], body.find(n)
    while i >= 0:
        out.append((i, i + len(n)))
        i = body.find(n, i + 1)
    if out:
        return out
    loc = locate(needle, body)
    return [loc] if loc else []


def interval_relation(a: tuple[int, int], b: tuple[int, int]) -> tuple[int, int]:
    """(overlap chars, gap chars) between two intervals; one of them is 0."""
    overlap = min(a[1], b[1]) - max(a[0], b[0])
    if overlap > 0:
        return overlap, 0
    return 0, -overlap


# ------------------------------------------------------------------------ loading
def load_gold(gold_dir: Path = GOLD_DIR) -> tuple[dict | None, dict | None]:
    import yaml

    out = []
    for name in (RULES_FILE, ADDRESSES_FILE):
        p = gold_dir / name
        out.append(yaml.safe_load(p.read_text(encoding="utf-8")) if p.is_file() else None)
    return out[0], out[1]


def validate_gold(rules_doc: dict | None, addr_doc: dict | None) -> list[str]:
    """Schema problems in the two gold files (empty list = valid)."""
    errs: list[str] = []
    for label, doc, key in (("rules.yaml", rules_doc, "rules"), ("addresses.yaml", addr_doc, "addresses")):
        if not isinstance(doc, dict):
            errs.append(f"{label}: not a mapping")
            continue
        for f in ("status", "reviewed_by"):
            if f not in doc:
                errs.append(f"{label}: missing top-level '{f}'")
        if not isinstance(doc.get(key), list) or not doc.get(key):
            errs.append(f"{label}: '{key}' must be a non-empty list")
    if errs:
        return errs
    ids: set[str] = set()
    for r in rules_doc["rules"]:
        rid = r.get("id")
        where = f"rules.yaml {rid}"
        if not rid or rid in ids:
            errs.append(f"{where}: missing or duplicate id")
        ids.add(rid)
        for f in ("source_doc_id", "jurisdiction", "level", "category", "status", "anchor_quote", "basis"):
            if not r.get(f):
                errs.append(f"{where}: missing {f}")
        if "effective_date" not in r:
            errs.append(f"{where}: missing effective_date (use null)")
        if r.get("level") not in LEVELS:
            errs.append(f"{where}: bad level {r.get('level')}")
        if r.get("category") not in CATEGORIES:
            errs.append(f"{where}: bad category {r.get('category')}")
        if r.get("status") not in STATUSES:
            errs.append(f"{where}: bad status {r.get('status')}")
        ed = r.get("effective_date")
        if ed is not None and not DATE_RE.match(str(ed)):
            errs.append(f"{where}: bad effective_date {ed}")
        if len(str(r.get("anchor_quote") or "")) < 20:
            errs.append(f"{where}: anchor_quote shorter than 20 chars")
        lvl_ok = (r.get("level") == "state") == ("," not in str(r.get("jurisdiction")))
        if not lvl_ok:
            errs.append(f"{where}: level does not fit jurisdiction")
        for alt in r.get("also_match") or []:
            if not alt.get("source_doc_id") or len(str(alt.get("anchor_quote") or "")) < 20:
                errs.append(f"{where}: bad also_match entry")
        for f in (r.get("also_ok") or {}):
            if f not in RULE_FIELDS:
                errs.append(f"{where}: also_ok on unknown field {f}")
    aids: set[str] = set()
    for a in addr_doc["addresses"]:
        aid = a.get("address_id")
        where = f"addresses.yaml {aid}"
        if not aid or aid in aids:
            errs.append(f"{where}: missing or duplicate address_id")
        aids.add(aid)
        if a.get("state") not in ("CA", "NJ", "MA"):
            errs.append(f"{where}: bad state")
        if not a.get("legal_city"):
            errs.append(f"{where}: missing legal_city (use 'uncertain')")
        for res in a.get("results") or []:
            if res.get("rule") not in ids:
                errs.append(f"{where}: result names unknown gold rule {res.get('rule')}")
            for v in [res.get("expected")] + list(res.get("also_ok") or []):
                if v not in RESULTS:
                    errs.append(f"{where}: bad expected result {v}")
            if not res.get("reason"):
                errs.append(f"{where}: result without reason")
    return errs


# ------------------------------------------------------------------------ rule matching
def _anchors(g: dict) -> list[tuple[str, str]]:
    return [(g["source_doc_id"], g["anchor_quote"])] + [
        (a["source_doc_id"], a["anchor_quote"]) for a in (g.get("also_match") or [])]


def match_rules(gold_rules: list[dict], ours: list[dict],
                body_of: Callable[[str], str | None]) -> tuple[dict[str, dict | None], list[str]]:
    """gold id -> best-matching rule of ours (or None). Also returns anchor problems
    (an anchor not found in its own document is a gold-file error, reported, never scored)."""
    located: dict[str, list[tuple[tuple[int, int], dict]]] = {}
    for r in ours:
        did = r.get("source_doc_id")
        for loc in (locate_all(r.get("quoted_span"), body_of(did)) if did else []):
            located.setdefault(did, []).append((loc, r))
    out: dict[str, dict | None] = {}
    problems: list[str] = []
    for g in gold_rules:
        best, best_key = None, None
        for did, anchor in _anchors(g):
            alocs = locate_all(anchor, body_of(did))
            if not alocs:
                problems.append(f"{g['id']}: anchor not found in {did}")
                continue
            for aloc, (sloc, r) in ((a, s) for a in alocs for s in located.get(did, [])):
                overlap, gap = interval_relation(aloc, sloc)
                if overlap == 0 and gap > MATCH_GAP:
                    continue
                # more overlap first, then closer, then the same category (tie-break only,
                # for several rules quoting one passage), then a stable id order
                key = (overlap, -gap, r.get("category") == g["category"], str(r.get("team_rule_id")))
                if best_key is None or key > best_key:
                    best, best_key = r, key
        out[g["id"]] = best
    return out, problems


def field_ok(field: str, gold: dict, ours: dict) -> bool:
    accepted = [gold.get(field)] + list((gold.get("also_ok") or {}).get(field, []))
    got = ours.get(field)
    if field == "effective_date":
        accepted = [None if v is None else str(v) for v in accepted]
        got = None if got is None else str(got)
    return got in accepted


def _numbers(text: Any) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", str(text or "")))


# ------------------------------------------------------------------------ address scoring
def classify_result(expected: str, got: str, also_ok: list[str] | None = None) -> str:
    """correct | over_cautious (we said unknown, gold is definite) | missed (gold has a row,
    we have none: the worst error) | wrong."""
    if got == expected or got in (also_ok or []):
        return "correct"
    if got == "unknown":
        return "over_cautious"
    if got == "absent":
        return "missed"
    return "wrong"


def classify_city(expected: str, got: str | None) -> str:
    """correct | unresolved (we left the city empty) | wrong | skipped (gold uncertain)."""
    if expected == "uncertain":
        return "skipped"
    exp = None if expected == "none" else expected
    if got == exp:
        return "correct"
    if got is None:
        return "unresolved"
    return "wrong"


# ------------------------------------------------------------------------ section
def _pct(n: int, d: int) -> str:
    return f"{n}/{d} ({100 * n / d:.1f}%)" if d else "0/0"


def _read_json(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _default_body_of() -> Callable[[str], str | None]:
    from navigator import starter

    cache: dict[str, str | None] = {}

    def body_of(did: str) -> str | None:
        if did not in cache:
            cache[did] = doc_body(starter.doc_text(did))
        return cache[did]

    return body_of


def section(rep: Any, out_dir: Path, gold_dir: Path | None = None,
            body_of: Callable[[str], str | None] | None = None) -> None:
    """Append section [4] to `rep` (eval/run_eval.Report). Never sets rep.hard_fail."""
    title = "[4] Gold set (rules + addresses)"
    gold_dir = gold_dir or GOLD_DIR
    if not (gold_dir / RULES_FILE).is_file() or not (gold_dir / ADDRESSES_FILE).is_file():
        rep.lines.append(f"{title}: not measured (no gold files)")
        return
    rules_doc, addr_doc = load_gold(gold_dir)
    errs = validate_gold(rules_doc, addr_doc)
    if errs:
        rep.lines.append(f"{title}: not measured (gold files invalid: {len(errs)} problems)")
        rep.lines.extend(f"  [info] {e}" for e in errs[:20])
        rep.metrics["gold"] = {"valid": False, "problems": len(errs)}
        return
    reviewed = bool(rules_doc.get("reviewed_by")) and bool(addr_doc.get("reviewed_by"))
    tag = "" if reviewed else " [draft gold, unreviewed]"
    rep.lines.append(f"{title} (not hard checks)" + ("" if reviewed else
                     " - DRAFT GOLD, UNREVIEWED: numbers do not count until a human sets reviewed_by"))
    body_of = body_of or _default_body_of()

    internal = _read_json(out_dir / "rules_internal.json")
    ours = (internal or {}).get("rules", []) if isinstance(internal, dict) else []
    if not ours:
        rep.lines.append("  not measured (outputs/rules_internal.json missing or empty)")
        rep.metrics["gold"] = {"valid": True, "reviewed": reviewed, "measured": False}
        return

    gold_rules = rules_doc["rules"]
    matches, anchor_problems = match_rules(gold_rules, ours, body_of)
    matched = {gid: r for gid, r in matches.items() if r is not None}
    m: dict[str, Any] = {"reviewed": reviewed, "valid": True, "measured": True,
                         "gold_rules": len(gold_rules), "gold_addresses": len(addr_doc["addresses"])}
    m["rule_recall"] = {"num": len(matched), "den": len(gold_rules)}
    rep.lines.append(f"  [    ] rule recall{tag}: {_pct(len(matched), len(gold_rules))}")

    mismatches: list[str] = []
    for g in gold_rules:
        if matches[g["id"]] is None:
            mismatches.append(f"rule {g['id']} ({g['source_doc_id']}, {g['jurisdiction']}, {g['category']}): no matching rule")
    field_counts: dict[str, dict[str, int]] = {}
    gold_by_id = {g["id"]: g for g in gold_rules}
    for f in RULE_FIELDS:
        ok = 0
        for gid, r in matched.items():
            g = gold_by_id[gid]
            if field_ok(f, g, r):
                ok += 1
            else:
                mismatches.append(f"rule {gid} -> {r.get('team_rule_id')}: {f} expected "
                                  f"{g.get(f)!r} got {r.get(f)!r}")
        field_counts[f] = {"num": ok, "den": len(matched)}
        rep.lines.append(f"  [    ] {f} accuracy (matched rules){tag}: {_pct(ok, len(matched))}")
    kv = [(gid, r) for gid, r in matched.items() if gold_by_id[gid].get("key_value")]
    kv_ok = sum(1 for gid, r in kv if _numbers(gold_by_id[gid]["key_value"])
                <= (_numbers(r.get("key_value")) | _numbers(r.get("requirement"))))
    field_counts["key_value_numbers"] = {"num": kv_ok, "den": len(kv)}
    rep.lines.append(f"  [info] key_value numbers present (key_value or requirement){tag}: {_pct(kv_ok, len(kv))}")
    m["fields"] = field_counts
    shared = {}
    for gid, r in matched.items():
        shared.setdefault(r.get("team_rule_id"), []).append(gid)
    shared = {k: v for k, v in shared.items() if len(v) > 1}
    if shared:
        rep.lines.append("  [info] one rule matched by several gold entries: "
                         + "; ".join(f"{k} <- {', '.join(v)}" for k, v in sorted(shared.items())))

    # ---- addresses: jurisdiction
    parcels_doc = _read_json(out_dir / "parcels.json")
    parcels = {p["address_id"]: p for p in (parcels_doc or {}).get("parcels", [])} if isinstance(parcels_doc, dict) else {}
    city_counts = {"correct": 0, "unresolved": 0, "wrong": 0, "skipped": 0, "missing": 0}
    state_ok = 0
    for a in addr_doc["addresses"]:
        p = parcels.get(a["address_id"])
        if p is None:
            city_counts["missing"] += 1
            mismatches.append(f"address {a['address_id']}: not in parcels.json")
            continue
        state_ok += p.get("state") == a["state"]
        c = classify_city(a["legal_city"], p.get("city"))
        city_counts[c] += 1
        if c in ("unresolved", "wrong"):
            mismatches.append(f"address {a['address_id']}: legal city expected {a['legal_city']!r} "
                              f"got {p.get('city')!r} ({c})")
    den_city = len(addr_doc["addresses"]) - city_counts["skipped"]
    m["address_state"] = {"num": state_ok, "den": len(addr_doc["addresses"])}
    m["address_city"] = {"num": city_counts["correct"], "den": den_city, **city_counts}
    rep.lines.append(f"  [    ] address legal city{tag}: {_pct(city_counts['correct'], den_city)}"
                     f" (unresolved {city_counts['unresolved']}, wrong {city_counts['wrong']},"
                     f" gold uncertain {city_counts['skipped']}, state {_pct(state_ok, len(addr_doc['addresses']))})")

    # ---- addresses: results
    lookups_doc = _read_json(out_dir / "lookups.json")
    lk = (lookups_doc or {}).get("lookups", {}) if isinstance(lookups_doc, dict) else {}
    res_counts = {"correct": 0, "over_cautious": 0, "missed": 0, "wrong": 0, "not_checkable": 0}
    missed_applies = 0
    for a in addr_doc["addresses"]:
        rows = {row.get("team_rule_id"): row.get("result") for row in lk.get(a["address_id"], [])
                if isinstance(row, dict)}
        for res in a.get("results") or []:
            r = matches.get(res["rule"])
            if r is None:
                res_counts["not_checkable"] += 1
                continue
            got = rows.get(r.get("team_rule_id"), "absent")
            c = classify_result(res["expected"], got, res.get("also_ok"))
            res_counts[c] += 1
            if c == "missed" and res["expected"] == "applies":
                missed_applies += 1
            if c != "correct":
                mismatches.append(f"address {a['address_id']} x {res['rule']} ({r.get('team_rule_id')}): "
                                  f"expected {res['expected']} got {got} ({c})")
    checked = sum(v for k, v in res_counts.items() if k != "not_checkable")
    m["address_results"] = {"num": res_counts["correct"], "den": checked, **res_counts,
                            "missed_applies": missed_applies}
    rep.lines.append(f"  [    ] address results{tag}: {_pct(res_counts['correct'], checked)}"
                     f" (over-cautious unknown {res_counts['over_cautious']}, missed rows {res_counts['missed']}"
                     f" of which missed applies {missed_applies}, wrong {res_counts['wrong']},"
                     f" not checkable {res_counts['not_checkable']})")

    for p in anchor_problems:
        rep.lines.append(f"  [info] gold anchor problem: {p}")
    m["anchor_problems"] = len(anchor_problems)
    m["mismatches"] = len(mismatches)
    rep.lines.append(f"  [info] mismatches ({len(mismatches)}){tag}:")
    rep.lines.extend(f"    - {x}" for x in mismatches)
    rep.metrics["gold"] = m
