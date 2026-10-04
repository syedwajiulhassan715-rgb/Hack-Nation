"""Request logic for the API. Deterministic, no LLM (golden rules 4 and 5).

Precomputed lookups come from outputs/lookups_internal.json; any other as_of, and every
POST /lookup with user-entered facts, runs `navigator.engine.lookup.evaluate_address`
(plain Python). Nothing here knows any law: rule text, citations and dates all come
from outputs/rules_internal.json.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import math
import re
import threading
from typing import Any, get_args

from navigator import settings
from navigator.api.models import (
    BuildingFacts,
    CategoryBlock,
    JurisdictionLevel,
    LookupRowOut,
    NoteOut,
    Offsets,
    TextWindow,
)
from navigator.api.store import DataUnavailable, Store
from navigator.engine import lookup as engine
from navigator.engine.facts import CONFIRMED_LEVELS
from navigator.engine.status import status_on
from navigator.schema.models import Category, LookupRowInternal, RuleInternal

CATEGORIES: list[str] = list(get_args(Category))
RESULT_ORDER = ["applies", "superseded", "unknown", "not_yet_effective", "pending"]
MAX_RESOLVE_M = 30.0
WINDOW_CHARS = 1200
SNAP_CHARS = 300
NO_RULE_NOTE = "No rule found in our sources for this level."

# UI copy (questions, not law). Owner wording describes obligations only (golden rule 11).
QUESTIONS: dict[str, dict[str, str]] = {
    "rent_increase_limits": {"tenant": "How much can my rent go up?",
                             "owner": "What limits apply when I raise the rent?"},
    "just_cause_eviction": {"tenant": "Can I be evicted without a reason?",
                            "owner": "What rules apply when ending a tenancy?"},
    "security_deposits": {"tenant": "How much deposit can I be charged?",
                          "owner": "What rules apply to security deposits?"},
    "application_screening_fees": {"tenant": "What can I be charged to apply?",
                                   "owner": "What rules apply to application fees?"},
    "screening_restrictions": {"tenant": "What can be checked when I apply?",
                               "owner": "What rules apply to screening applicants?"},
    "algorithmic_rent_setting": {"tenant": "Can my rent be set by pricing software?",
                                 "owner": "What rules apply to pricing software?"},
}
STATE_NAMES = {"CA": "California", "NJ": "New Jersey", "MA": "Massachusetts"}

_engine_lock = threading.Lock()   # the engine keeps a module-level precedence cache


class NotFound(Exception):
    pass


class BadRequest(Exception):
    pass


# ------------------------------------------------------------------ helpers


def parse_as_of(value: str | None, default: str) -> str:
    if value is None or value == "":
        return default
    msg = f"as_of must be a calendar date YYYY-MM-DD, got {value!r}"
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise BadRequest(msg)
    try:
        return dt.date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise BadRequest(msg) from exc


def utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def numbers_grounded(answer: str, span: str) -> bool:
    """Golden rule 7: every number in a summary must appear in its quoted_span."""
    flat = span.replace(",", "")
    for tok in _NUM.findall(answer):
        tok = tok.rstrip(",.")
        if tok not in span and tok.replace(",", "") not in flat:
            return False
    return True


def summary_answer(store: Store, rule: RuleInternal, role: str, lang: str) -> str | None:
    s = store.summaries().get(rule.team_rule_id)
    if not isinstance(s, dict):
        return None
    # written for this exact quote? (rule ids can be reassigned by a later verify run)
    want = s.get("source_quote_sha")
    if not want or want != hashlib.sha256(rule.quoted_span.encode("utf-8")).hexdigest():
        return None
    key = f"answer_{role}" if lang == "en" else f"answer_{role}_{lang}"
    text = s.get(key)
    if not isinstance(text, str) or not text.strip():
        return None
    return text if numbers_grounded(text, rule.quoted_span) else None


def address_line(parcel: dict[str, Any], zip_code: str | None) -> str:
    parts = [str(parcel.get("street_address") or "").strip()]
    if parcel.get("postal_city"):
        parts.append(str(parcel["postal_city"]))
    tail = str(parcel.get("state") or "")
    if zip_code:
        tail = f"{tail} {zip_code}".strip()
    parts.append(tail)
    return ", ".join(p for p in parts if p)


def get_parcel(store: Store, address_id: str) -> dict[str, Any]:
    p = store.parcels().get(address_id)
    if p is None:
        raise NotFound(f"address_id {address_id!r} is not a sample address")
    return p


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def nearest(store: Store, lat: float, lng: float) -> tuple[dict[str, Any] | None, float | None]:
    best, best_d = None, None
    for p in store.parcels().values():
        if p.get("lat") is None or p.get("lng") is None:
            continue
        d = haversine_m(lat, lng, float(p["lat"]), float(p["lng"]))
        if best_d is None or d < best_d:
            best, best_d = p, d
    return best, best_d


# ------------------------------------------------------------------ search


def search(store: Store, q: str, limit: int) -> tuple[str, list[dict[str, Any]]]:
    q = q.strip()
    zips = store.zips()
    parcels = store.parcels()
    if re.fullmatch(r"\d{5}", q):
        hits = [p for aid, p in parcels.items() if zips.get(aid) == q]
        return "zip", [_hit(p, zips) for p in hits[:limit]]
    tokens = [t for t in re.split(r"[\s,]+", q.lower()) if t]
    out = []
    for aid, p in parcels.items():
        hay = " ".join(str(x) for x in (aid, p.get("street_address"), p.get("postal_city"),
                                         p.get("city"), p.get("state"), zips.get(aid)) if x).lower()
        if all(t in hay for t in tokens):
            out.append(_hit(p, zips))
            if len(out) >= limit:
                break
    return "text", out


def _hit(p: dict[str, Any], zips: dict[str, str]) -> dict[str, Any]:
    aid = str(p["address_id"])
    return {"address_id": aid, "address": address_line(p, zips.get(aid)),
            "street_address": p.get("street_address") or "", "postal_city": p.get("postal_city"),
            "state": p.get("state") or "", "city": p.get("city"), "zip": zips.get(aid) or None,
            "lat": p.get("lat"), "lng": p.get("lng")}


# ------------------------------------------------------------------ lookup


def precomputed_rows(store: Store, address_id: str, as_of: str) -> tuple[list[LookupRowInternal], str] | None:
    """Rows from lookups_internal.json if it was computed for this as_of, else None."""
    data = store.lookups()
    if data.get("as_of") != as_of:
        return None
    rows = data.get("lookups", {}).get(address_id)
    if rows is None:
        raise DataUnavailable(f"lookups_internal.json has no entry for {address_id}; outputs are out of sync. "
                              "Re-run `python -m navigator lookups`.")
    return [LookupRowInternal.model_validate(r) for r in rows], store.mtime("lookups_internal.json") or ""


_last_rules: list[list[RuleInternal]] = []   # strong ref to the rules list last given to the engine


def live_rows(store: Store, parcel: dict[str, Any], as_of: str) -> list[LookupRowInternal]:
    rules = store.rules()
    with _engine_lock:
        # The engine caches precedence relations keyed by id() of the rule objects; after a
        # reload of rules_internal.json freed objects' ids can be reused, so drop the cache
        # whenever the rules list changes.
        if not _last_rules or _last_rules[0] is not rules:
            engine._REL_CACHE.clear()
            _last_rules[:] = [rules]
        return engine.evaluate_address(parcel, rules, as_of)


def merge_facts(parcel: dict[str, Any], facts: dict[str, int | None]) -> tuple[dict[str, Any], dict[str, int]]:
    """Copy of the parcel with user-entered building facts; jurisdiction is never changed."""
    p = dict(parcel)
    used: dict[str, int] = {}
    missing = set(p.get("missing_facts") or [])
    if facts.get("year_built") is not None:
        p["year_built"] = used["year_built"] = int(facts["year_built"])
        missing.discard("year_built")
    if facts.get("units") is not None:
        n = used["units"] = int(facts["units"])
        p.update(units=n, units_min=n, units_max=n, units_source="user_input")
        missing.discard("units")
    elif facts.get("units_min") is not None or facts.get("units_max") is not None:
        lo, hi = facts.get("units_min"), facts.get("units_max")
        if lo is not None and hi is not None and lo > hi:
            raise BadRequest("units_min must not exceed units_max")
        p.update(units=None, units_min=lo, units_max=hi, units_source="user_input")
        used.update({k: int(v) for k, v in (("units_min", lo), ("units_max", hi)) if v is not None})
        missing.discard("units")
    p["missing_facts"] = sorted(missing)
    return p, used


def _row_out(row: LookupRowInternal, rule: RuleInternal, rules: dict[str, RuleInternal], as_of: str,
             answer: str | None, lang: str) -> LookupRowOut:
    sup = rules.get(row.superseded_by) if row.superseded_by else None
    return LookupRowOut(
        team_rule_id=rule.team_rule_id, result=row.result, status=status_on(rule, as_of),
        level=rule.level, jurisdiction=rule.jurisdiction, category=rule.category, title=rule.title,
        answer=answer, answer_lang=lang if answer else None, explanation=row.explanation,
        requirement=rule.requirement, key_value=rule.key_value, quoted_span=rule.quoted_span,
        citation=rule.citation, source_doc_id=rule.source_doc_id, source_url=rule.source_url,
        retrieved_at=rule.retrieved_at, effective_date=rule.effective_date,
        missing_facts=row.missing_facts, superseded_by=row.superseded_by,
        superseded_by_citation=sup.citation if sup else None,
        conflict_flag=row.conflict_flag, conflict_note=rule.conflict_note,
        confidence=row.confidence, confidence_reasons=row.confidence_reasons,
        needs_review=rule.needs_review, review_reasons=rule.review_reasons,
        checked=row.checked, not_checked=row.not_checked,
    )


def build_lookup(store: Store, parcel: dict[str, Any], rows: list[LookupRowInternal], *, as_of: str,
                 role: str, lang: str, computed: str, generated_at: str,
                 user_facts: dict[str, int] | None = None) -> dict[str, Any]:
    rules = store.rules_file()["by_id"]
    aid = str(parcel["address_id"])
    state, city = str(parcel.get("state") or ""), parcel.get("city")
    city_confirmed = bool(parcel.get("city")) and parcel.get("jurisdiction_confidence") in CONFIRMED_LEVELS

    by_cat: dict[str, list[LookupRowOut]] = {c: [] for c in CATEGORIES}
    for row in rows:
        rule = rules.get(row.team_rule_id)
        if rule is None:   # fail closed: never silently drop a row
            raise DataUnavailable(f"lookup row references {row.team_rule_id}, which is not in "
                                  "rules_internal.json; outputs are out of sync. Re-run the pipeline.")
        by_cat.setdefault(rule.category, []).append(
            _row_out(row, rule, rules, as_of, summary_answer(store, rule, role, lang), lang))

    level_rank = {"city": 0, "state": 1}
    categories = []
    for cat in CATEGORIES:
        cat_rows = sorted(by_cat.get(cat, []), key=lambda r: (RESULT_ORDER.index(r.result),
                                                              level_rank.get(r.level, 2), r.team_rule_id))
        q = QUESTIONS[cat]
        categories.append(CategoryBlock(
            category=cat, question=q[role], question_tenant=q["tenant"], question_owner=q["owner"],
            rows=cat_rows, no_rule_note=None if cat_rows else NO_RULE_NOTE))

    stack = [JurisdictionLevel(level="state", jurisdiction=state, name=STATE_NAMES.get(state, state))]
    if city:
        stack.append(JurisdictionLevel(level="city", jurisdiction=city, name=city.rsplit(",", 1)[0].strip(),
                                       confirmed=city_confirmed))

    notes = []
    for r in store.rules():
        if r.status == "failed" and (r.jurisdiction == state or (city and r.jurisdiction == city)):
            notes.append(NoteOut(jurisdiction=r.jurisdiction, text=r.title, date=r.effective_date,
                                 team_rule_id=r.team_rule_id, citation=r.citation, quoted_span=r.quoted_span,
                                 source_url=r.source_url, retrieved_at=r.retrieved_at))

    facts = BuildingFacts(
        year_built=parcel.get("year_built"), units=parcel.get("units"), units_min=parcel.get("units_min"),
        units_max=parcel.get("units_max"), units_source=parcel.get("units_source"),
        use_description=parcel.get("use_description"), postal_city=parcel.get("postal_city"),
        legal_city=city, jurisdiction_confidence=parcel.get("jurisdiction_confidence"),
        jurisdiction_source=parcel.get("jurisdiction_source"), lat=parcel.get("lat"), lng=parcel.get("lng"))

    return {
        "as_of": as_of, "generated_at": generated_at, "disclaimer": disclaimer(),
        "address_id": aid, "address": address_line(parcel, store.zips().get(aid)),
        "role": role, "lang": lang, "computed": computed,
        "jurisdiction_stack": stack, "facts": facts, "user_facts": user_facts or {},
        "missing_facts": list(parcel.get("missing_facts") or []),
        "categories": categories, "notes": notes,
    }


def disclaimer() -> str:
    return settings.load()["disclaimer"]


def default_as_of() -> str:
    return settings.load()["default_as_of"]


# ------------------------------------------------------------------ rule detail


def text_window(text: str, rule: RuleInternal, body_offset: int = 0) -> TextWindow | None:
    s, e = rule.span_start, rule.span_end
    if s is None or e is None or not (0 <= s < e <= len(text)):
        return None
    lo = max(body_offset, s - WINDOW_CHARS)
    if lo > body_offset:   # snap back to a line start if one is close
        nl = text.rfind("\n", max(body_offset, lo - SNAP_CHARS), lo)
        lo = nl + 1 if nl >= 0 else lo
    hi = min(len(text), e + WINDOW_CHARS)
    if hi < len(text):     # snap forward to a line end if one is close
        nl = text.find("\n", hi, hi + SNAP_CHARS)
        hi = nl if nl >= 0 else hi
    lo = min(lo, s)
    window = text[lo:hi]
    u = utf16_len
    offsets = Offsets(span_start=s, span_end=e, window_start=lo, window_end=hi,
                      span_start_in_window=s - lo, span_end_in_window=e - lo)
    u_lo = u(text[:lo])
    u_s, u_e = u(text[:s]), u(text[:e])
    offsets16 = Offsets(span_start=u_s, span_end=u_e, window_start=u_lo, window_end=u_lo + u(window),
                        span_start_in_window=u_s - u_lo, span_end_in_window=u_e - u_lo)
    span_text = text[s:e]
    return TextWindow(doc_id=rule.source_doc_id or "", text=window, offsets=offsets, offsets_utf16=offsets16,
                      span_text=span_text, span_text_equals_quote=span_text == rule.quoted_span)


def rule_detail(store: Store, rule: RuleInternal, as_of: str) -> dict[str, Any]:
    tw, note = None, None
    if not rule.source_doc_id:
        note = "rule has no source_doc_id; the quote cannot be located in a stored document"
    else:
        try:
            rec = store.docs().get(rule.source_doc_id)
        except DataUnavailable as exc:
            rec, note = None, exc.message
        text = rec.get("text") if rec else None
        if text:
            tw = text_window(text, rule, int(rec.get("body_offset") or 0))
            if tw is None:
                note = "stored span offsets are missing or out of range; highlight the quote by substring"
        elif note is None:
            note = f"no stored text for {rule.source_doc_id}; highlight the quote by substring"
    summ = store.summaries().get(rule.team_rule_id)
    answers = {}
    for role in ("tenant", "owner"):
        answers[f"answer_{role}"] = summary_answer(store, rule, role, "en") if summ else None
    return {
        "as_of": as_of, "generated_at": store.mtime("rules_internal.json"), "disclaimer": disclaimer(),
        "rule": rule, "status_on_as_of": status_on(rule, as_of), "source_url": rule.source_url,
        "retrieved_at": rule.retrieved_at, **answers, "text_window": tw,
        "highlight": "offsets" if tw else ("substring" if rule.quoted_span else "none"), "note": note,
    }


# ------------------------------------------------------------------ audit


def audit_for(store: Store, rule: RuleInternal) -> list[dict[str, Any]]:
    """Audit lines for this rule's current provenance.

    team_rule_ids are reassigned when verify re-runs, so a verify line counts only if its
    candidate ids overlap this rule's provenance; extract lines match by chunk id and
    ingest lines by document id.
    """
    cand = {p.get("candidate_id") for p in rule.provenance if p.get("candidate_id")}
    chunks = {p.get("chunk_id") for p in rule.provenance if p.get("chunk_id")}
    docs = {p.get("source_doc_id") for p in rule.provenance if p.get("source_doc_id")}
    if rule.source_doc_id:
        docs.add(rule.source_doc_id)
    out = []
    for e in store.audit():
        stage = e.get("stage")
        if stage == "verify":
            if e.get("team_rule_id") != rule.team_rule_id:
                continue
            ec = set(e.get("candidates") or [])
            if cand and ec and not (ec & cand):
                continue
        elif stage == "extract":
            if e.get("chunk_id") not in chunks:
                continue
        elif stage == "ingest":
            if e.get("doc_id") not in docs:
                continue
        else:
            continue
        out.append(e)
    return out


# ------------------------------------------------------------------ changes


def change_tests(store: Store) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    changes = store.changes()
    internal = store.changes_internal()
    details = (internal or {}).get("tests", {})
    tests = []
    for tid in sorted(changes):
        c = changes[tid]
        d = details.get(tid, {})
        tests.append({
            "test_id": tid, "title": d.get("title"), "type": d.get("type"),
            "expected_behavior": d.get("expected_behavior"),
            "affected_address_ids": list(c.get("affected_address_ids", [])),
            "conflict_flag_address_ids": list(c.get("conflict_flag_address_ids", [])),
            "affected_count": len(c.get("affected_address_ids", [])),
            "conflict_count": len(c.get("conflict_flag_address_ids", [])),
            "notes": c.get("notes", ""), "notes_list": list(d.get("notes", [])),
            "checks": list(d.get("checks", [])),
        })
    return tests, internal
