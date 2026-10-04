"""Plain-language layer (BACKEND_PLAN.md 2.10): rules_internal.json -> outputs/summaries.json.

Per rule the model writes `answer_tenant` and `answer_owner` from `quoted_span` plus a few
structured fields. Deterministic guards in `navigator.explain.guards` then decide: any
failure drops that answer (null), and the UI shows the quote instead. Optional Spanish
(`answer_tenant_es` / `answer_owner_es`) translates only approved English sentences and
passes the same guards.

UI text only: lookups.json explanations do not come from here. Calls are cached on disk
under the LLM cache dir keyed by (rule content sha, prompt version, model, task); a cached
run never calls the API. Every call and every keep/drop decision goes to the audit log.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

from navigator import audit, settings
from navigator.explain import guards

STAGE = "summaries"
PROMPT_VERSION = "summary_v1"
PROMPT_FILE = Path(__file__).resolve().parent.parent / "extract" / "prompts" / f"{PROMPT_VERSION}.md"
ROLES = ("tenant", "owner")
WORKERS = 6
# Fields the model sees. Exemptions and dates are left out on purpose: owner text must not
# describe exemptions, and dates may only come from the quote (number guard).
INPUT_FIELDS = ("jurisdiction", "level", "category", "status", "title", "requirement",
                "key_value", "coverage_conditions", "quoted_span")

EN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"answer_tenant": {"type": ["string", "null"]},
                   "answer_owner": {"type": ["string", "null"]}},
    "required": ["answer_tenant", "answer_owner"],
    "additionalProperties": False,
}
ES_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"answer_tenant_es": {"type": ["string", "null"]},
                   "answer_owner_es": {"type": ["string", "null"]}},
    "required": ["answer_tenant_es", "answer_owner_es"],
    "additionalProperties": False,
}

# caller(system, user, schema, key_parts, label) -> {"data", "cached", "model", "usage"}
Caller = Callable[..., dict[str, Any]]


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@lru_cache(maxsize=None)
def prompt_text() -> str:
    return PROMPT_FILE.read_text(encoding="utf-8")


@lru_cache(maxsize=None)
def prompts() -> dict[str, str]:
    """System prompts {"en", "repair", "es"} from the sections of the prompt file."""
    en, sep1, rest = prompt_text().partition("## Repair")
    repair, sep2, es = rest.partition("## Translation")
    if not (sep1 and sep2):
        raise RuntimeError(f"{PROMPT_FILE.name}: needs '## Repair' and '## Translation' sections")
    return {"en": en.strip() + "\n", "repair": "## Repair" + repair.rstrip() + "\n",
            "es": es.strip() + "\n"}


def prompt_sha() -> str:
    """Part of every cache key, so an edited prompt can never reuse a stale answer."""
    return sha256(prompt_text())


def rule_input(rule: dict[str, Any]) -> dict[str, Any]:
    return {k: rule.get(k) for k in INPUT_FIELDS}


def model_name() -> str:
    from navigator.extract import llm

    return llm.stage_settings(STAGE)["model"]


# ------------------------------------------------------------------ cached LLM call


def cached_call(*, system: str, user: str, schema: dict[str, Any], key_parts: dict[str, Any],
                label: str, use_cache: bool = True) -> dict[str, Any]:
    """Structured-output call with the same disk cache format as navigator.extract.llm.

    `llm.call_json` takes its prompt version from settings (the extraction prompt), so this
    wrapper keys on PROMPT_VERSION instead; client, cache paths and key hashing are reused.
    """
    from navigator.extract import llm

    cfg = llm.stage_settings(STAGE)
    key_parts = {**key_parts, "stage": STAGE, "prompt_version": PROMPT_VERSION,
                 "prompt_sha": prompt_sha(), "model": cfg["model"]}
    key = llm.cache_key(key_parts)
    path = llm.cache_path(key)
    if use_cache and path.exists():
        entry = json.loads(path.read_text(encoding="utf-8"))
        audit.log(STAGE, "llm_cache_hit", cache_key=key, label=label,
                  prompt_version=PROMPT_VERSION)
        return {"data": entry["response"], "cached": True, "model": entry["model"],
                "usage": entry.get("usage")}

    client = llm._get_client()
    started = time.monotonic()
    with client.messages.stream(
        model=cfg["model"],
        max_tokens=cfg.get("max_tokens", 32000),
        system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": cfg.get("effort", "high"),
                       "format": {"type": "json_schema", "schema": schema}},
    ) as stream:
        msg = stream.get_final_message()
    seconds = round(time.monotonic() - started, 1)
    usage = {"input_tokens": msg.usage.input_tokens, "output_tokens": msg.usage.output_tokens}
    request_id = getattr(msg, "_request_id", None)

    def fail(reason: str) -> RuntimeError:
        audit.log(STAGE, "llm_error", reason, cache_key=key, label=label,
                  request_id=request_id, seconds=seconds, **usage)
        return RuntimeError(f"{label}: {reason}")

    if msg.stop_reason == "refusal":
        raise fail("model refused")
    if msg.stop_reason == "max_tokens":
        raise fail("output truncated at max_tokens")
    text = next((b.text for b in msg.content if b.type == "text"), None)
    if text is None:
        raise fail("no text block in response")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise fail(f"invalid JSON: {exc}") from exc

    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {"key_parts": key_parts, "model": cfg["model"], "served_model": msg.model,
             "request_id": request_id, "usage": usage, "stop_reason": msg.stop_reason,
             "response": data}
    path.write_text(json.dumps(entry, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    audit.log(STAGE, "llm_call", cache_key=key, label=label, model=cfg["model"],
              served_model=msg.model, prompt_version=PROMPT_VERSION, request_id=request_id,
              seconds=seconds, input_sha=key_parts.get("rule_sha"),
              output_sha=sha256(json.dumps(data, sort_keys=True, ensure_ascii=False)), **usage)
    return {"data": data, "cached": False, "model": cfg["model"], "usage": usage}


# ------------------------------------------------------------------ one rule

# Failures a rewrite may fix. Evasion wording is never sent back for a rewrite: it is dropped.
NOT_REPAIRABLE = ("evasion_wording", "no_answer")
MAX_REPAIRS = 2


def _guarded(data: dict[str, Any], roles: list[str], suffix: str,
             check: Callable[[str, str | None], list[str]]) -> tuple[dict, dict]:
    """(kept {role: text}, failures {role: [reasons]}) for the answers in `data`."""
    kept, failed = {}, {}
    for role in roles:
        text = data.get(f"answer_{role}{suffix}")
        text = text.strip() if isinstance(text, str) else None
        reasons = check(role, text)
        if reasons:
            failed[role] = reasons
        else:
            kept[role] = text
    return kept, failed


def _generate(*, caller: Caller, system: str, user: str, schema: dict[str, Any],
              key_parts: dict[str, Any], label: str, roles: list[str], suffix: str,
              check: Callable[[str, str | None], list[str]]
              ) -> tuple[dict[str, str], dict[str, list[str]], list[str]]:
    """One call, the guards, and up to MAX_REPAIRS repair calls for repairable failures.

    Returns (kept answers, final failures, repair notes). Every kept answer passed the full
    guard set on its final text; a repair never bypasses a guard.
    """
    data = caller(system=system, user=user, schema=schema, key_parts=key_parts,
                  label=label)["data"]
    latest = {r: data.get(f"answer_{r}{suffix}") for r in roles}
    kept, failed = _guarded(data, roles, suffix, check)
    notes: list[str] = []
    for attempt in range(1, MAX_REPAIRS + 1):
        to_fix = {r: why for r, why in failed.items()
                  if not any(w.startswith(NOT_REPAIRABLE) for w in why)}
        if not to_fix:
            break
        previous = {f"answer_{r}{suffix}": latest[r] for r in roles}
        repair_user = (user + "\n\n## Previous answers\n\n"
                       + json.dumps(previous, ensure_ascii=False, indent=1)
                       + "\n\n## Failed checks\n\n"
                       + json.dumps({f"answer_{r}{suffix}": why for r, why in to_fix.items()},
                                    ensure_ascii=False, indent=1) + "\n")
        tag = "" if attempt == 1 else str(attempt)
        try:
            fixed = caller(system=system + "\n" + prompts()["repair"], user=repair_user,
                           schema=schema, label=f"{label}-repair{tag}",
                           key_parts={**key_parts, "task": f"{key_parts['task']}_repair{tag}",
                                      "previous_sha": sha256(json.dumps(
                                          previous, sort_keys=True, ensure_ascii=False))})
        except Exception as exc:  # the earlier failures stand
            notes.append(f"repair_llm_error: {exc}")
            break
        new_kept, new_failed = _guarded(fixed["data"], list(to_fix), suffix, check)
        for role, why in to_fix.items():
            latest[role] = fixed["data"].get(f"answer_{role}{suffix}")
            if role in new_kept:
                kept[role] = new_kept[role]
                failed.pop(role)
                notes.append(f"{role}{suffix}: repaired ({', '.join(why)})")
            else:
                failed[role] = new_failed[role]
    return kept, failed, notes


def summarize_rule(rule: dict[str, Any], caller: Caller, spanish: bool = True) -> dict[str, Any]:
    """Summary entry for one rule. Never raises: an LLM failure drops the answers."""
    rid = rule["team_rule_id"]
    quote = rule["quoted_span"]
    status = rule["status"]
    payload = rule_input(rule)
    rule_sha = sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False))
    entry: dict[str, Any] = {"answer_tenant": None, "answer_owner": None, "dropped": [],
                             "source_quote_sha": sha256(quote)}
    if status == "failed":
        # Failed measures never appear in lookups; no plain-language text for them.
        entry["dropped"].append("status_failed: no plain-language answer")
        audit.log(STAGE, "summary_skipped", "status failed", team_rule_id=rid)
        return entry

    def check_en(role: str, text: str | None) -> list[str]:
        return guards.check(text, role=role, status=status, quote=quote)

    try:
        kept, failed, notes = _generate(
            caller=caller, system=prompts()["en"],
            user="## Rule\n\n" + json.dumps(payload, ensure_ascii=False, indent=1),
            schema=EN_SCHEMA, key_parts={"task": "en", "rule_sha": rule_sha},
            label=f"{rid}-en", roles=list(ROLES), suffix="", check=check_en)
    except Exception as exc:  # one bad call must not stop the run; recorded as a drop
        entry["dropped"].append(f"llm_error: {exc}")
        audit.log(STAGE, "summary_failed", str(exc), team_rule_id=rid)
        return entry
    for role in ROLES:
        entry[f"answer_{role}"] = kept.get(role)
        entry["dropped"].extend(f"{role}: {r}" for r in failed.get(role, []))

    if spanish and kept:
        notes += _translate(entry, rule, rule_sha, caller)

    audit.log(STAGE, "summary_kept" if not entry["dropped"] else "summary_partial",
              "; ".join(entry["dropped"]) or None, team_rule_id=rid,
              doc_id=rule.get("source_doc_id"), prompt_version=PROMPT_VERSION,
              input_sha=rule_sha, repairs=notes or None)
    return entry


def _translate(entry: dict[str, Any], rule: dict[str, Any], rule_sha: str,
               caller: Caller) -> list[str]:
    """Spanish for approved English answers only, under the same guards."""
    rid, quote, status = rule["team_rule_id"], rule["quoted_span"], rule["status"]
    approved = {"answer_tenant": entry["answer_tenant"], "answer_owner": entry["answer_owner"]}
    roles = [r for r in ROLES if entry[f"answer_{r}"]]

    def check_es(role: str, text: str | None) -> list[str]:
        reasons = guards.check(text, role=role, status=status, quote=quote, lang="es")
        if text:  # the translation may not introduce a number the approved English lacks
            en_values = {v for v, _ in guards.numbers(entry[f"answer_{role}"], "en")}
            reasons += [f"number_not_in_english:{v}" for v, _ in guards.numbers(text, "es")
                        if v not in en_values]
        return sorted(set(reasons))

    user = "## Sentences\n\n" + json.dumps(
        {"status": status, **approved, "quoted_span": quote}, ensure_ascii=False, indent=1)
    try:
        kept, failed, notes = _generate(
            caller=caller, system=prompts()["es"], user=user, schema=ES_SCHEMA,
            key_parts={"task": "es", "rule_sha": rule_sha,
                       "english_sha": sha256(json.dumps(approved, sort_keys=True,
                                                        ensure_ascii=False))},
            label=f"{rid}-es", roles=roles, suffix="_es", check=check_es)
    except Exception as exc:
        entry["dropped"].append(f"es: llm_error: {exc}")
        return []
    for role in roles:
        if role in kept:
            entry[f"answer_{role}_es"] = kept[role]
        entry["dropped"].extend(f"{role}_es: {r}" for r in failed.get(role, []))
    return notes


# ------------------------------------------------------------------ stage


def run(*, caller: Caller | None = None, rules_path: Path | None = None,
        out_path: Path | None = None, spanish: bool = True, use_cache: bool = True,
        workers: int = WORKERS) -> dict[str, Any]:
    outputs = settings.path("outputs")
    rules_path = rules_path or outputs / "rules_internal.json"
    out_path = out_path or outputs / "summaries.json"
    rules = json.loads(rules_path.read_text(encoding="utf-8"))["rules"]
    if caller is None:
        def caller(**kw):
            return cached_call(use_cache=use_cache, **kw)
        model = model_name()
    else:
        model = getattr(caller, "model", "fake")

    print(f"summarizing {len(rules)} rules (model {model}, prompt {PROMPT_VERSION}, "
          f"spanish {'on' if spanish else 'off'})", flush=True)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        entries = list(pool.map(lambda r: summarize_rule(r, caller, spanish), rules))
    summaries = {r["team_rule_id"]: e for r, e in sorted(zip(rules, entries),
                                                         key=lambda p: p[0]["team_rule_id"])}
    doc = {
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "prompt_version": PROMPT_VERSION,
        "model": model,
        "disclaimer": settings.load()["disclaimer"],
        "summaries": summaries,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8",
                        newline="\n")
    stats = counts(summaries)
    print(f"tenant kept {stats['tenant_kept']}/{len(rules)}, owner kept "
          f"{stats['owner_kept']}/{len(rules)}"
          + (f", es kept {stats['tenant_es_kept']}+{stats['owner_es_kept']}" if spanish else "")
          + f" -> {out_path.name}", flush=True)
    return doc


def counts(summaries: dict[str, dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {f"{k}_kept": sum(1 for e in summaries.values() if e.get(f"answer_{k}"))
                           for k in ("tenant", "owner", "tenant_es", "owner_es")}
    reasons: dict[str, int] = {}
    for e in summaries.values():
        for d in e["dropped"]:
            role, _, why = d.partition(": ")
            key = f"{role}: {why.split(':')[0]}"
            reasons[key] = reasons.get(key, 0) + 1
    out["drop_reasons"] = dict(sorted(reasons.items(), key=lambda kv: -kv[1]))
    return out
