"""Self-evaluation harness (BACKEND_PLAN.md 4). The pack has no scoring script.

Independent of the pipeline on purpose: it validates the written files against the
official JSON schema and the corpus text directly, not through navigator's models.
Writes scores/eval_latest.txt and appends scores/history.jsonl.
Exits 1 if a must-be-100% check (format, grounding) fails.
"""
from __future__ import annotations

import datetime as dt
import importlib
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Any

import jsonschema

from navigator import settings, starter

RESULTS = {"applies", "unknown", "superseded", "not_yet_effective", "pending"}
LOOKUP_ROW_KEYS = {"team_rule_id", "result", "explanation", "conflict_flag"}
CHANGE_KEYS = {"affected_address_ids", "conflict_flag_address_ids", "notes"}

CHECKLIST = Path(__file__).parent / "brief_checklist.yaml"
CATEGORIES = ["rent_increase_limits", "just_cause_eviction", "security_deposits",
              "application_screening_fees", "screening_restrictions", "algorithmic_rent_setting"]
CAT_ABBR = ["rent", "jcause", "deposit", "appfee", "screen", "algo"]

# optional sections, each a module with section(rep, out_dir); absent module = not measured
SECTIONS = [
    ("4", "Gold set (rules + addresses)", "eval.gold_eval"),
    ("7", "Jurisdiction check", "eval.jurisdiction_check"),
    ("8", "Determinism (two cached runs byte-identical)", "eval.determinism"),
]


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()


def _load(path: Path) -> tuple[Any, str | None]:
    if not path.is_file():
        return None, "missing"
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc}"


class Report:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.metrics: dict[str, Any] = {}
        self.hard_fail = False

    def check(self, key: str, label: str, ok: bool, detail: str = "", hard: bool = True) -> None:
        self.metrics[key] = ok
        if hard and not ok:
            self.hard_fail = True
        self.lines.append(f"  [{'PASS' if ok else 'FAIL'}] {label}{(' - ' + detail) if detail else ''}")

    def ratio(self, key: str, label: str, num: int, den: int, must_be_full: bool) -> None:
        self.metrics[key] = {"num": num, "den": den}
        if den == 0:
            self.lines.append(f"  [n/a ] {label}: 0/0")
            return
        ok = num == den
        if must_be_full and not ok:
            self.hard_fail = True
        tag = "PASS" if ok else ("FAIL" if must_be_full else "    ")
        self.lines.append(f"  [{tag}] {label}: {num}/{den} ({100 * num / den:.1f}%)")


def evaluate(out_dir: Path) -> Report:
    rep = Report()
    rules_doc, rules_err = _load(out_dir / "rules.json")
    lookups_doc, lookups_err = _load(out_dir / "lookups.json")
    changes_doc, changes_err = _load(out_dir / "changes.json")
    address_ids = starter.address_ids()
    manifest = starter.manifest()

    # ---------------------------------------------------------- 1. format
    rep.lines.append("[1] Format validity (must be 100%)")
    rules: list[dict] = []
    if rules_err:
        rep.check("rules_file", "rules.json readable", False, rules_err)
    else:
        shape_ok = isinstance(rules_doc, dict) and set(rules_doc) == {"rules"} and isinstance(rules_doc["rules"], list)
        rep.check("rules_shape", 'rules.json is {"rules": [...]}', shape_ok)
        rules = rules_doc["rules"] if shape_ok else []
        validator = jsonschema.Draft202012Validator(starter.rule_schema())
        valid = sum(1 for r in rules if not any(validator.iter_errors(r)))
        rep.ratio("rules_schema_valid", "rule records valid against official schema", valid, len(rules), True)
        ids = [r.get("team_rule_id") for r in rules]
        rep.check("rules_unique_ids", "team_rule_id unique", len(ids) == len(set(ids)))
    rules_by_id = {r.get("team_rule_id"): r for r in rules}

    if lookups_err:
        rep.check("lookups_file", "lookups.json readable", False, lookups_err)
    else:
        ok_shape = isinstance(lookups_doc, dict) and set(lookups_doc) == {"as_of", "lookups"}
        rep.check("lookups_shape", 'lookups.json is {"as_of", "lookups"}', ok_shape)
        lk = lookups_doc.get("lookups", {}) if ok_shape else {}
        as_of = lookups_doc.get("as_of") if ok_shape else None
        rep.check("lookups_as_of", "as_of is YYYY-MM-DD", bool(as_of and re.fullmatch(r"\d{4}-\d{2}-\d{2}", as_of)), str(as_of))
        covered = len(set(lk) & set(address_ids))
        rep.ratio("lookups_cover_all", "address ids covered", covered, len(address_ids), True)
        rep.check("lookups_no_extra_ids", "no unknown address ids", not (set(lk) - set(address_ids)))
        bad_rows, unknown_rules, failed_in_lookups = 0, 0, 0
        for rows in lk.values():
            for row in rows if isinstance(rows, list) else [None]:
                if not isinstance(row, dict) or set(row) != LOOKUP_ROW_KEYS or row.get("result") not in RESULTS:
                    bad_rows += 1
                    continue
                rule = rules_by_id.get(row["team_rule_id"])
                if rule is None:
                    unknown_rules += 1
                elif rule.get("status") == "failed":
                    failed_in_lookups += 1
        rep.check("lookups_row_shape", "every row has exactly {team_rule_id, result, explanation, conflict_flag}", bad_rows == 0, f"{bad_rows} bad")
        rep.check("lookups_rules_exist", "every row's rule is in rules.json", unknown_rules == 0, f"{unknown_rules} unknown")
        rep.check("lookups_no_failed", "no failed rule appears in lookups", failed_in_lookups == 0)
        rows_total = sum(len(v) for v in lk.values() if isinstance(v, list))
        rep.metrics["lookup_rows_total"] = rows_total
        rep.lines.append(f"  [info] lookup rows: {rows_total}; addresses with no rows: "
                         f"{sum(1 for v in lk.values() if v == [])}")

    if changes_err:
        rep.check("changes_file", "changes.json readable", False, changes_err)
    else:
        test_ids = starter.change_test_ids()
        rep.check("changes_all_tests", f"has all tests {test_ids}", isinstance(changes_doc, dict) and all(t in changes_doc for t in test_ids))
        entries = [changes_doc.get(t) for t in test_ids] if isinstance(changes_doc, dict) else []
        rep.check("changes_entry_shape", "each test has affected_address_ids, conflict_flag_address_ids, notes",
                  all(isinstance(e, dict) and set(e) == CHANGE_KEYS for e in entries))
        bad = [i for e in entries if isinstance(e, dict)
               for k in ("affected_address_ids", "conflict_flag_address_ids")
               for i in e.get(k, []) if i not in set(address_ids)]
        rep.check("changes_ids_valid", "all listed ids are sample address ids", not bad, f"{len(bad)} unknown")

    # ------------------------------------------------------- 2. grounding
    rep.lines.append("[2] Grounding (must be 100%)")
    text_cache: dict[str, str | None] = {}
    found = 0
    url_ok = 0
    for r in rules:
        did = r.get("source_doc_id")
        if did not in text_cache:
            raw = starter.doc_text(did) if did else None
            if raw and raw.startswith("SOURCE:"):
                raw = raw.split("\n", 3)[3] if raw.count("\n") >= 3 else ""  # body only, no header
            text_cache[did] = _norm(raw) if raw else None
        body = text_cache[did]
        if body and r.get("quoted_span") and _norm(r["quoted_span"]) in body:
            found += 1
        if did in manifest and r.get("source_url") == manifest[did]["url"]:
            url_ok += 1
    rep.ratio("grounding_span_found", "quoted_span found in its source_doc_id text", found, len(rules), True)
    rep.ratio("grounding_source_url", "source_url equals manifest url", url_ok, len(rules), True)

    applies_ids = {row["team_rule_id"] for rows in (lookups_doc or {}).get("lookups", {}).values()
                   if isinstance(rows, list) for row in rows
                   if isinstance(row, dict) and row.get("result") == "applies"}
    backed = sum(
        1 for rid in applies_ids
        if (r := rules_by_id.get(rid)) and r.get("quoted_span") and r.get("citation") and r.get("source_url")
        and manifest.get(r.get("source_doc_id") or "", {}).get("retrieved_at")
    )
    rep.ratio("grounding_applies_backed", "rules behind 'applies' rows have span, citation, url, retrieval date",
              backed, len(applies_ids), True)

    # ---------------------------------------------- 3. brief recall checklist
    rep.lines.append("[3] Brief recall checklist (laws the briefs name; misses count only with text in corpus)")
    items = _checklist()
    hits, den, missing = 0, 0, []
    for it in items:
        ok = _checklist_found(it, rules)
        with_text = it.get("text_in_corpus", "yes") not in ("no", False)
        if with_text:
            den += 1
            hits += ok
        if not ok:
            missing.append(it["id"] + ("" if with_text else " (no text in corpus)"))
    rep.ratio("checklist_recall", "checklist laws found", hits, den, False)
    if missing:
        rep.lines.append("  [info] not found: " + ", ".join(missing))

    # ---------------------------------------------------- 6. coverage matrix
    rep.lines.append("[6] Coverage matrix (rules per jurisdiction x category; ! = checklist law with text but no rule)")
    counts: dict[tuple[str, str], int] = {}
    for r in rules:
        counts[(r.get("jurisdiction"), r.get("category"))] = counts.get((r.get("jurisdiction"), r.get("category")), 0) + 1
    red = {(it["jurisdiction"], it["category"]) for it in items
           if it.get("text_in_corpus", "yes") not in ("no", False) and not _checklist_found(it, rules)}
    jurs = sorted({j for j, _ in counts} | {it["jurisdiction"] for it in items},
                  key=lambda j: (j.rsplit(", ", 1)[-1], ", " in j, j))
    rep.lines.append("  " + "jurisdiction".ljust(18) + "".join(a.rjust(8) for a in CAT_ABBR))
    for j in jurs:
        cells = [(str(counts.get((j, c), 0)) + ("!" if (j, c) in red else "")).rjust(8) for c in CATEGORIES]
        rep.lines.append("  " + j.ljust(18) + "".join(cells))
    rep.metrics["coverage_red_cells"] = len(red)
    rep.metrics["rules_total"] = len(rules)
    status_counts: dict[str, int] = {}
    for r in rules:
        status_counts[r.get("status")] = status_counts.get(r.get("status"), 0) + 1
    rep.metrics["rules_by_status"] = status_counts
    rep.lines.append(f"  [info] rules: {len(rules)}; by status {dict(sorted(status_counts.items()))}; red cells: {len(red)}")

    _change_checks(rep, out_dir)
    for num, label, module in SECTIONS:
        try:
            mod = importlib.import_module(module)
        except ModuleNotFoundError as exc:
            if exc.name != module:
                raise
            rep.lines.append(f"[{num}] {label}: not measured yet ({module} not built)")
            continue
        mod.section(rep, out_dir)
    return rep


def _change_checks(rep: Report, out_dir: Path) -> None:
    """[5] the change tracker's explicit assertions (outputs/changes_internal.json)."""
    doc, err = _load(out_dir / "changes_internal.json")
    if doc is None:
        rep.lines.append(f"[5] Change tests T1-T5 expected behavior: not measured ({err})")
        return
    rep.lines.append("[5] Change tests T1-T5 expected behavior (assertions from dev/change_tests.json)")
    counts = {True: 0, False: 0, None: 0}
    for tid, t in doc["tests"].items():
        rep.lines.append(f"  {tid}: {t['affected']} affected, {t['conflicts']} conflict-flagged")
        for c in t["checks"]:
            counts[c["passed"]] += 1
            tag = {True: "PASS", False: "FAIL", None: "n/a "}[c["passed"]]
            rep.lines.append(f"    [{tag}] {c['name']} - {c['detail']}")
    rep.metrics["change_checks"] = {"pass": counts[True], "fail": counts[False], "not_checkable": counts[None]}
    rep.lines.append(f"  [info] checks: {counts[True]} pass, {counts[False]} fail, "
                     f"{counts[None]} not checkable (no source text)")


def _checklist() -> list[dict[str, Any]]:
    import yaml

    return yaml.safe_load(CHECKLIST.read_text(encoding="utf-8"))["items"]


def _checklist_found(item: dict[str, Any], rules: list[dict]) -> bool:
    cite = re.sub(r"\s+", "", str(item.get("cite") or "")).lower()
    for r in rules:
        if r.get("jurisdiction") != item["jurisdiction"] or r.get("category") != item["category"]:
            continue
        if r.get("source_doc_id") in (item.get("docs") or []):
            return True
        if cite and cite in re.sub(r"\s+", "", r.get("citation") or "").lower():
            return True
    return False


def _git_commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, cwd=settings.REPO_ROOT, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def run(out_dir: Path | None = None, scores_dir: Path | None = None) -> Report:
    out_dir = out_dir or settings.path("outputs")
    scores_dir = scores_dir or settings.path("scores")
    stub = (out_dir / "STUB").exists()
    rep = evaluate(out_dir)
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    header = [
        "Self-evaluation (team harness; the pack has no official scoring script). Not legal advice.",
        f"generated_at {now}  commit {_git_commit()}  as_of default {settings.load()['default_as_of']}",
    ]
    if stub:
        header.insert(0, "*** STUB OUTPUTS: pipeline not run; numbers below say nothing about answers ***")
    header.append(f"overall hard checks: {'FAIL' if rep.hard_fail else 'PASS'}")
    text = "\n".join(header + [""] + rep.lines) + "\n"

    scores_dir.mkdir(parents=True, exist_ok=True)
    (scores_dir / "eval_latest.txt").write_text(text, encoding="utf-8", newline="\n")
    with (scores_dir / "history.jsonl").open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps({"ts": now, "commit": _git_commit(), "stub": stub,
                             "hard_fail": rep.hard_fail, "metrics": rep.metrics}) + "\n")
    if out_dir == settings.path("outputs") and not stub:
        from eval import render_docs

        render_docs.update(rep.metrics, {"ts": now, "commit": _git_commit(), "hard_fail": rep.hard_fail}, out_dir)
    print(text, end="")
    if rep.hard_fail:
        sys.exit(1)
    return rep
