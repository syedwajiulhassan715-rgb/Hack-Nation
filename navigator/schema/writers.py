"""Write the three submission files in exactly the contract shapes.

Each writer validates before writing and refuses (raises OutputError listing every
problem) rather than emit a file that breaks the contract. Output is deterministic:
stable ordering, 2-space indent, UTF-8, trailing newline, atomic replace.
"""
from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import jsonschema

from navigator import settings, starter
from navigator.schema.models import (
    ChangeResult,
    ChangesFile,
    LookupRow,
    LookupsFile,
    RuleRecord,
    RulesFile,
)


class OutputError(ValueError):
    def __init__(self, filename: str, problems: list[str]):
        self.problems = problems
        shown = "\n  ".join(problems[:20])
        more = f"\n  ... and {len(problems) - 20} more" if len(problems) > 20 else ""
        super().__init__(f"refusing to write {filename}:\n  {shown}{more}")


def dump_json(data: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, path)


def _out(name: str, out_dir: Path | None) -> Path:
    return (out_dir or settings.path("outputs")) / name


# ---------------------------------------------------------------- rules.json


def check_rules(rules: Iterable[RuleRecord]) -> list[str]:
    rules = list(rules)
    problems: list[str] = []
    validator = jsonschema.Draft202012Validator(starter.rule_schema())
    ids = [r.team_rule_id for r in rules]
    seen: set[str] = set()
    for rid in ids:
        if rid in seen:
            problems.append(f"duplicate team_rule_id {rid}")
        seen.add(rid)
    from navigator.ingest.corpus import manifest_rows  # starter + supplement (CONTRACT.md 6)

    manifest = manifest_rows()
    for r in rules:
        rec = r.model_dump(include=set(RuleRecord.model_fields))
        for err in validator.iter_errors(rec):
            problems.append(f"{r.team_rule_id}: schema: {err.message}")
        for other in r.overrides:
            if other not in seen:
                problems.append(f"{r.team_rule_id}: overrides unknown rule {other}")
            if other == r.team_rule_id:
                problems.append(f"{r.team_rule_id}: overrides itself")
        # Golden rule 3: source fields always filled from the manifest.
        row = manifest.get(r.source_doc_id or "")
        if row is None:
            problems.append(f"{r.team_rule_id}: source_doc_id {r.source_doc_id!r} not in manifest")
        elif r.source_url != row["url"]:
            problems.append(f"{r.team_rule_id}: source_url differs from manifest for {r.source_doc_id}")
    return problems


def write_rules(rules: Iterable[RuleRecord], out_dir: Path | None = None) -> Path:
    # Strip internal fields: RuleInternal -> RuleRecord.
    records = [
        r.to_record() if hasattr(r, "to_record") else RuleRecord.model_validate(r.model_dump())
        for r in rules
    ]
    records.sort(key=lambda r: r.team_rule_id)
    problems = check_rules(records)
    if problems:
        raise OutputError("rules.json", problems)
    payload = RulesFile(rules=records).model_dump(mode="json")
    path = _out("rules.json", out_dir)
    dump_json(payload, path)
    return path


# -------------------------------------------------------------- lookups.json


def check_lookups(as_of: str, lookups: Mapping[str, list[LookupRow]],
                  rules: Iterable[RuleRecord]) -> list[str]:
    problems: list[str] = []
    expected = set(starter.address_ids())
    got = set(lookups)
    if missing := sorted(expected - got):
        problems.append(f"{len(missing)} address ids missing, e.g. {missing[:5]}")
    if extra := sorted(got - expected):
        problems.append(f"{len(extra)} unknown address ids, e.g. {extra[:5]}")
    by_id = {r.team_rule_id: r for r in rules}
    for aid, rows in lookups.items():
        seen: set[str] = set()
        for row in rows:
            rule = by_id.get(row.team_rule_id)
            if rule is None:
                problems.append(f"{aid}: rule {row.team_rule_id} not in rules.json")
                continue
            if row.team_rule_id in seen:
                problems.append(f"{aid}: rule {row.team_rule_id} listed twice")
            seen.add(row.team_rule_id)
            # Golden rule 9: failed measures never appear in lookups; pending never in force.
            if rule.status == "failed":
                problems.append(f"{aid}: failed rule {rule.team_rule_id} must not appear")
            if rule.status == "pending" and row.result != "pending":
                problems.append(f"{aid}: pending rule {rule.team_rule_id} reported as {row.result}")
    try:
        LookupsFile(as_of=as_of, lookups={k: list(v) for k, v in lookups.items()})
    except ValueError as exc:
        problems.append(f"shape: {exc}")
    return problems


def write_lookups(as_of: str, lookups: Mapping[str, list[LookupRow]],
                  rules: Iterable[RuleRecord], out_dir: Path | None = None) -> Path:
    rows = {
        aid: [r.to_row() if hasattr(r, "to_row") else r for r in lookups[aid]]
        for aid in lookups
    }
    problems = check_lookups(as_of, rows, list(rules))
    if problems:
        raise OutputError("lookups.json", problems)
    order = {aid: i for i, aid in enumerate(starter.address_ids())}
    payload = {
        "as_of": as_of,
        "lookups": {
            aid: [r.model_dump(mode="json") for r in sorted(rows[aid], key=lambda r: r.team_rule_id)]
            for aid in sorted(rows, key=order.__getitem__)
        },
    }
    path = _out("lookups.json", out_dir)
    dump_json(payload, path)
    return path


# -------------------------------------------------------------- changes.json


def check_changes(changes: Mapping[str, ChangeResult]) -> list[str]:
    problems: list[str] = []
    expected = starter.change_test_ids()
    if missing := [t for t in expected if t not in changes]:
        problems.append(f"missing tests {missing}")
    if extra := [t for t in changes if t not in expected]:
        problems.append(f"tests not in change_tests.json: {extra}")
    valid_ids = set(starter.address_ids())
    for tid, res in changes.items():
        for field in ("affected_address_ids", "conflict_flag_address_ids"):
            ids = getattr(res, field)
            if len(ids) != len(set(ids)):
                problems.append(f"{tid}.{field}: duplicate ids")
            if bad := sorted(set(ids) - valid_ids):
                problems.append(f"{tid}.{field}: unknown ids {bad[:5]}")
        if not res.notes.strip():
            problems.append(f"{tid}: notes empty")
    return problems


def write_changes(changes: Mapping[str, ChangeResult], out_dir: Path | None = None) -> Path:
    problems = check_changes(changes)
    if problems:
        raise OutputError("changes.json", problems)
    order = {aid: i for i, aid in enumerate(starter.address_ids())}
    payload = ChangesFile(
        {
            tid: ChangeResult(
                affected_address_ids=sorted(set(changes[tid].affected_address_ids), key=order.__getitem__),
                conflict_flag_address_ids=sorted(set(changes[tid].conflict_flag_address_ids), key=order.__getitem__),
                notes=changes[tid].notes,
            )
            for tid in starter.change_test_ids()
        }
    ).model_dump(mode="json")
    path = _out("changes.json", out_dir)
    dump_json(payload, path)
    return path
