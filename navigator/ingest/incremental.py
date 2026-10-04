"""Incremental document path: `ingest-doc`, `rerun-live` and (later) `POST /ingest`.

Public API (stable; the API imports this module):

    from navigator.ingest import incremental

    summary = incremental.run(doc_path, live=False, progress=None,
                              jurisdiction=None, doc_id=None)

- `doc_path`: path to a text file in corpus format: line 1 `SOURCE: <http(s) url>`,
  line 2 `RETRIEVED: YYYY-MM-DD HH:MM UTC`, line 3 blank, then the text (UTF-8, LF line
  endings, no BOM). Anything else is rejected before a single file is written (fail closed).
- `live`: True for `rerun-live`: the LLM cache is bypassed for this document only (every
  other document's candidates are kept as they are). The fresh answer is still written to
  the cache, so the next cached run reproduces it.
- `progress`: optional callable taking one dict per event:
      {"step": str, "index": int, "total": int, "status": "start" | "done" | "error",
       "message": str, "doc_id": str | None}
  Steps, in order: validate, register, ingest, chunk, extract, verify, lookups, changes.
  Every step emits "start" then "done", or "error" and the run stops. Default: print.
- `jurisdiction`: "ST" or "City, ST". Optional when the document's url is already in
  data/supplement/manifest.csv or is a starter manifest row without text (e.g. a released
  check-terms page); otherwise required (never guessed).
- `doc_id`: optional; default is the existing supplement id for this file, or the next `S###`.

Returns a JSON-serialisable summary dict (doc_id, jurisdiction, source_url, retrieved_at,
live, n_chunks, n_candidates, rules_new, rules_changed, rules_removed, rules_unchanged,
as_of, disclaimer). Raises `IngestError` (a ValueError with `.step`) on rejection or failure.

What it does (BACKEND_PLAN.md 2.1-2.9, CONTRACT.md 6): validate the header; register the
file as a supplement document (exact bytes copied to data/supplement/text/<id>.txt plus a
manifest row; data/starter/ is never written); re-run ingest and chunk (deterministic);
extract only this document's chunks; then verify, lookups and changes for the whole rule set.
Geocoding is not repeated: addresses do not change when a document is added.

Rule ids stay stable: verify numbers rules by sort position, so a new rule could shift
every later id. After verify, rules whose candidates are unchanged keep their previous
`team_rule_id`, new rules get ids after the previous maximum, and rules.json /
rules_internal.json are rewritten with those ids. Rules a new document does not touch are
therefore byte-identical in rules.json (tests/test_incremental.py checks this).
Each step writes one line to outputs/audit.jsonl (stage "incremental").
"""
from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from navigator import audit, settings

ProgressFn = Callable[[dict[str, Any]], None]

STEPS = ("validate", "register", "ingest", "chunk", "extract", "verify", "lookups", "changes")
MANIFEST_COLUMNS = ["doc_id", "jurisdictions", "url", "source_type", "capture", "retrieved_at",
                    "sha256", "text_file", "status"]
URL_RE = re.compile(r"^https?://\S+$")
RETRIEVED_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC$")
DOC_ID_RE = re.compile(r"^[A-Z][A-Za-z0-9_-]{0,31}$")
SUPPLEMENT_ID_RE = re.compile(r"^S(\d+)$")
MIN_BODY_CHARS = 20          # the shortest quoted_span verify accepts
MAX_BYTES = 5_000_000        # the largest starter text is ~160 KB


class IngestError(ValueError):
    def __init__(self, step: str, reason: str):
        self.step = step
        self.reason = reason
        super().__init__(f"{step}: {reason}")


def print_progress(event: dict[str, Any]) -> None:
    mark = {"start": "...", "done": "ok ", "error": "ERR"}[event["status"]]
    print(f"[{event['index']}/{event['total']}] {mark} {event['step']}: {event['message']}", flush=True)


# ------------------------------------------------------------------ validate


def validate_file(doc_path: str | Path) -> dict[str, Any]:
    """Check the corpus format. Returns {"raw", "text", "url", "retrieved_at", "body_offset"}."""
    from navigator.ingest.corpus import _header_time_to_manifest, parse_header

    path = Path(doc_path)
    if not path.is_file():
        raise IngestError("validate", f"file not found: {doc_path}")
    raw = path.read_bytes()
    if not raw:
        raise IngestError("validate", "empty file")
    if len(raw) > MAX_BYTES:
        raise IngestError("validate", f"file larger than {MAX_BYTES} bytes")
    if raw.startswith(b"\xef\xbb\xbf"):
        raise IngestError("validate", "file starts with a UTF-8 BOM; corpus files have none")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise IngestError("validate", f"not UTF-8 text ({exc.reason} at byte {exc.start})") from exc
    if "\r" in text:
        # Offsets are stored against the file on disk; corpus files use LF only.
        raise IngestError("validate", "CR line endings; corpus files use LF only")
    header = parse_header(text)
    if header is None:
        raise IngestError("validate", "missing corpus header: line 1 'SOURCE: <url>', "
                                      "line 2 'RETRIEVED: YYYY-MM-DD HH:MM UTC', line 3 blank")
    url, retrieved, body_offset = header
    if not URL_RE.fullmatch(url):
        raise IngestError("validate", f"SOURCE is not an http(s) url: {url!r}")
    if not RETRIEVED_RE.fullmatch(retrieved):
        raise IngestError("validate", f"RETRIEVED is not 'YYYY-MM-DD HH:MM UTC': {retrieved!r}")
    try:
        dt.datetime.strptime(retrieved, "%Y-%m-%d %H:%M UTC")
    except ValueError as exc:
        raise IngestError("validate", f"RETRIEVED is not a valid date and time: {retrieved!r}") from exc
    if len(text[body_offset:].strip()) < MIN_BODY_CHARS:
        raise IngestError("validate", "no extractable text after the header")
    return {"raw": raw, "text": text, "url": url, "body_offset": body_offset,
            "retrieved_at": _header_time_to_manifest(retrieved)}


# ------------------------------------------------------------------ register


def supplement_manifest_path() -> Path:
    return settings.path("supplement") / "manifest.csv"


def _read_supplement() -> list[dict[str, str]]:
    from navigator.ingest.corpus import read_manifest

    path = supplement_manifest_path()
    return read_manifest(path) if path.is_file() else []


def _starter_rows() -> list[dict[str, str]]:
    from navigator.ingest.corpus import read_manifest

    return read_manifest(settings.path("manifest"))


def _state(jurisdiction: str) -> str:
    return jurisdiction.rsplit(", ", 1)[-1]


def _check_jurisdiction(jurisdiction: str, starter_rows: list[dict[str, str]]) -> str:
    from navigator.ingest.corpus import jurisdiction_level

    jurisdiction = " ".join(jurisdiction.split())
    if jurisdiction_level(jurisdiction) is None:
        raise IngestError("register", f"jurisdiction {jurisdiction!r} is neither 'ST' nor 'City, ST'")
    # In-scope states come from the starter manifest, never from a list in code.
    states = {_state(r["jurisdictions"].strip()) for r in starter_rows if r["jurisdictions"].strip()}
    if _state(jurisdiction) not in states:
        raise IngestError("register", f"state {_state(jurisdiction)!r} is not in the corpus "
                                      f"(manifest states: {', '.join(sorted(states))})")
    return jurisdiction


def register(checked: dict[str, Any], jurisdiction: str | None = None,
             doc_id: str | None = None) -> dict[str, Any]:
    """Add the file to data/supplement/ (CONTRACT.md 6). Idempotent for identical bytes.

    Returns the manifest row plus "new" (bool) and "note" (str | None).
    """
    sha = hashlib.sha256(checked["raw"]).hexdigest()
    url = checked["url"]
    starter_rows = _starter_rows()
    supplement = _read_supplement()
    starter_ids = {r["doc_id"].strip() for r in starter_rows}
    sup_dir = supplement_manifest_path().parent
    if jurisdiction:
        jurisdiction = _check_jurisdiction(jurisdiction, starter_rows)

    # Already registered (same stored bytes) or a hand-added row for this url (CONTRACT.md 6).
    same_url: list[dict[str, str]] = []
    for r in supplement:
        rel = r.get("text_file", "").strip()
        stored = sup_dir / rel if rel else None
        stored_sha = hashlib.sha256(stored.read_bytes()).hexdigest() if stored and stored.is_file() else None
        if stored_sha == sha:
            if r["url"].strip() != url:
                raise IngestError("register", f"same text already registered as {r['doc_id']} "
                                              f"under url {r['url']!r}")
            if jurisdiction and jurisdiction != r["jurisdictions"].strip():
                raise IngestError("register", f"already registered as {r['doc_id']} with jurisdiction "
                                              f"{r['jurisdictions']!r}, not {jurisdiction!r}")
            if doc_id and doc_id != r["doc_id"].strip():
                raise IngestError("register", f"already registered as {r['doc_id']}")
            return {**r, "new": False, "note": "already registered; reused"}
        if r["url"].strip() == url:
            if stored_sha is not None:
                raise IngestError("register", f"url already registered as {r['doc_id']} with different "
                                              "text; supplement documents are append-only")
            same_url.append(r)                             # hand-added row whose text is not stored yet
    starter_same_url = [r for r in starter_rows if r["url"].strip() == url]
    note = None
    for r in starter_same_url:
        if r["text_file"].strip():
            raise IngestError("register", f"url is starter document {r['doc_id']}, which already has text")
    if starter_same_url:
        note = "supplies text for starter " + ", ".join(
            f"{r['doc_id']} ({r['capture']})" for r in starter_same_url)

    # Jurisdiction: given, or from a manifest row for the same url; never guessed.
    known = {r["jurisdictions"].strip() for r in same_url + starter_same_url if r["jurisdictions"].strip()}
    if jurisdiction:
        if known and jurisdiction not in known:
            raise IngestError("register", f"jurisdiction {jurisdiction!r} differs from the manifest's "
                                          f"{', '.join(sorted(known))} for this url")
    elif len(known) == 1:
        jurisdiction = _check_jurisdiction(known.pop(), starter_rows)
    else:
        raise IngestError("register", "jurisdiction unknown: pass --jurisdiction 'City, ST' or 'ST', "
                                      "or add a data/supplement/manifest.csv row for this url")

    pre = same_url[0] if same_url else None          # a hand-added row without text yet
    if pre and doc_id and doc_id != pre["doc_id"]:
        raise IngestError("register", f"url already has supplement row {pre['doc_id']}")
    taken = starter_ids | {r["doc_id"].strip() for r in supplement if r is not pre}
    if pre:
        doc_id = pre["doc_id"].strip()
    elif doc_id:
        if not DOC_ID_RE.fullmatch(doc_id):
            raise IngestError("register", f"doc_id {doc_id!r} must match {DOC_ID_RE.pattern}")
    else:
        n = max((int(m.group(1)) for d in taken if (m := SUPPLEMENT_ID_RE.fullmatch(d))), default=0)
        doc_id = f"S{n + 1:03d}"
    if doc_id in taken:
        raise IngestError("register", f"doc_id {doc_id} is already used")

    text_rel = f"text/{doc_id}.txt"
    text_path = supplement_manifest_path().parent / text_rel
    if text_path.exists():
        raise IngestError("register", f"{text_rel} already exists in data/supplement/ but is not in its manifest")
    row = {"doc_id": doc_id, "jurisdictions": jurisdiction, "url": url, "source_type": "official",
           "capture": "manual", "retrieved_at": checked["retrieved_at"], "sha256": sha,
           "text_file": text_rel, "status": "ok"}
    text_path.parent.mkdir(parents=True, exist_ok=True)
    text_path.write_bytes(checked["raw"])              # exact bytes: offsets refer to this file
    rows = [r for r in supplement if r is not pre] + [row]
    tmp = supplement_manifest_path().with_suffix(".csv.tmp")
    with tmp.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=MANIFEST_COLUMNS, lineterminator="\n", extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    tmp.replace(supplement_manifest_path())
    return {**row, "new": True, "note": note}


# ------------------------------------------------------------------ rule ids


def _read_internal() -> list[dict[str, Any]]:
    path = settings.path("outputs") / "rules_internal.json"
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8"))["rules"]


def _read_public() -> dict[str, dict[str, Any]]:
    path = settings.path("outputs") / "rules.json"
    if not path.is_file():
        return {}
    return {r["team_rule_id"]: r for r in json.loads(path.read_text(encoding="utf-8"))["rules"]}


def _cand_key(rule: dict[str, Any]) -> frozenset[str]:
    return frozenset(p["candidate_id"] for p in rule.get("provenance") or [])


def stable_ids(prior: list[dict[str, Any]], current: list[dict[str, Any]]) -> dict[str, str]:
    """Map verify's fresh ids to stable ids. Pure.

    A rule keeps its previous id when its candidate set is unchanged, or when it is the only
    current rule whose candidates include a previous rule's candidates (a merge). Other rules
    get new ids after the previous maximum, in verify's order.
    """
    by_key = {_cand_key(r): r["team_rule_id"] for r in prior if _cand_key(r)}
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for r in current:
        old = by_key.get(_cand_key(r))
        if old and old not in used:
            mapping[r["team_rule_id"]] = old
            used.add(old)
    open_prior = {rid: k for k, rid in by_key.items() if rid not in used}
    open_now = {r["team_rule_id"]: _cand_key(r) for r in current if r["team_rule_id"] not in mapping}
    for rid, k in open_prior.items():
        holders = [cur for cur, ck in open_now.items() if k <= ck]
        if len(holders) == 1 and sum(pk <= open_now[holders[0]] for pk in open_prior.values()) == 1:
            mapping[holders[0]] = rid
            del open_now[holders[0]]
    numbers = [int(rid[2:]) for rid in [r["team_rule_id"] for r in prior] if re.fullmatch(r"r-\d+", rid)]
    n = max(numbers, default=0)
    for r in current:
        if r["team_rule_id"] not in mapping:
            n += 1
            mapping[r["team_rule_id"]] = f"r-{n:04d}"
    return mapping


def _rewrite_ids(prior: list[dict[str, Any]]) -> dict[str, str]:
    """Apply stable_ids to rules_internal.json and rules.json (verify's outputs)."""
    from navigator.engine import precedence
    from navigator.ingest.corpus import manifest_rows
    from navigator.schema.models import RuleInternal
    from navigator.schema.writers import dump_json, write_rules

    out = settings.path("outputs")
    data = json.loads((out / "rules_internal.json").read_text(encoding="utf-8"))
    mapping = stable_ids(prior, data["rules"])
    rules = [RuleInternal.model_validate({**r, "team_rule_id": mapping[r["team_rule_id"]]}) for r in data["rules"]]
    rules.sort(key=lambda r: r.team_rule_id)
    # Same links as verify; supplement documents' jurisdictions are included.
    doc_jur = {k: v.get("jurisdictions") or "" for k, v in manifest_rows().items()}
    links = precedence.link(rules, doc_jur)
    write_rules([r.model_copy(update=links[r.team_rule_id]) for r in rules])
    dump_json({**data, "rules": [r.model_dump(mode="json") for r in rules]}, out / "rules_internal.json")
    return mapping


# ------------------------------------------------------------------ steps


def _step_ingest(doc_id: str) -> str:
    from navigator.ingest.corpus import load_all, write_docs

    docs = load_all()
    write_docs(docs)
    doc = next((d for d in docs if d.doc_id == doc_id), None)
    if doc is None or not doc.text_available:
        reason = doc.unavailable_reason if doc else "not in the merged manifest"
        raise IngestError("ingest", f"{doc_id} has no usable text: {reason}")
    warn = f"; warnings: {'; '.join(doc.warnings)}" if doc.warnings else ""
    return f"{len(docs)} documents ({sum(d.text_available for d in docs)} with text); {doc_id} {doc.n_chars} chars{warn}"


def _step_chunk(doc_id: str) -> tuple[str, int]:
    from navigator.extract import chunk

    chunk.run()
    n = sum(1 for c in chunk.read_chunks() if c.doc_id == doc_id)
    if n == 0:
        raise IngestError("chunk", f"{doc_id} produced no chunks")
    return f"{doc_id}: {n} chunk(s)", n


def _step_extract(doc_id: str, live: bool) -> tuple[str, int]:
    from navigator.extract import extract

    try:
        extract.run(docs=[doc_id], no_cache=live)
    except SystemExit as exc:            # extract reports failed chunks this way
        raise IngestError("extract", str(exc.code)) from None
    path = settings.path("outputs") / "candidates.jsonl"
    n = sum(1 for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and json.loads(line)["source_doc_id"] == doc_id)
    return f"{n} candidate(s) from {doc_id} (cache {'off' if live else 'on'})", n


def _step_verify(prior: list[dict[str, Any]]) -> tuple[str, dict[str, str]]:
    from navigator.verify import gates

    gates.run()
    mapping = _rewrite_ids(prior)
    moved = {k: v for k, v in mapping.items() if k != v}
    return f"{len(mapping)} rules; {len(moved)} id(s) kept stable against verify's numbering", moved


def _step_lookups() -> str:
    from navigator.engine import lookup

    lookup.run()
    return "lookups.json, timeline.json, snapshots.json rewritten"


def _step_changes() -> str:
    from navigator.changes import tracker

    tracker.run()
    return "changes.json rewritten"


# ------------------------------------------------------------------ run


def run(doc_path: str | Path, live: bool = False, progress: ProgressFn | None = None,
        jurisdiction: str | None = None, doc_id: str | None = None) -> dict[str, Any]:
    """Register one corpus-format document and rebuild every output. See the module docstring."""
    emit = progress or print_progress
    total = len(STEPS)
    state: dict[str, Any] = {"doc_id": None}

    def step(name: str, fn: Callable[[], Any]) -> Any:
        i = STEPS.index(name) + 1
        emit({"step": name, "index": i, "total": total, "status": "start",
              "message": "running", "doc_id": state["doc_id"]})
        try:
            result = fn()
        except Exception as exc:
            reason = exc.reason if isinstance(exc, IngestError) else f"{type(exc).__name__}: {exc}"
            audit.log("incremental", f"{name}_failed", reason, step=name, doc_id=state["doc_id"],
                      path=str(doc_path), live=live)
            emit({"step": name, "index": i, "total": total, "status": "error",
                  "message": reason, "doc_id": state["doc_id"]})
            if isinstance(exc, IngestError):
                raise
            raise IngestError(name, reason) from exc
        message = result[0] if isinstance(result, tuple) else result
        audit.log("incremental", f"{name}_done", message, step=name, doc_id=state["doc_id"], live=live)
        emit({"step": name, "index": i, "total": total, "status": "done",
              "message": message, "doc_id": state["doc_id"]})
        return result

    def do_validate() -> tuple[str, dict[str, Any]]:
        checked = validate_file(doc_path)
        return f"corpus header ok (SOURCE {checked['url']}, retrieved {checked['retrieved_at']})", checked

    checked = step("validate", do_validate)[1]

    def do_register() -> tuple[str, dict[str, Any]]:
        row = register(checked, jurisdiction=jurisdiction, doc_id=doc_id)
        state["doc_id"] = row["doc_id"]
        what = "registered" if row["new"] else "found"
        return (f"{what} {row['doc_id']} ({row['jurisdictions']}) in data/supplement/"
                + (f"; {row['note']}" if row["note"] else "")), row

    row = step("register", do_register)[1]
    did = row["doc_id"]
    prior_internal = _read_internal()
    prior_public = _read_public()

    step("ingest", lambda: _step_ingest(did))
    n_chunks = step("chunk", lambda: _step_chunk(did))[1]
    n_candidates = step("extract", lambda: _step_extract(did, live))[1]
    step("verify", lambda: _step_verify(prior_internal))
    step("lookups", _step_lookups)
    step("changes", _step_changes)

    after = _read_public()
    new = sorted(set(after) - set(prior_public))
    removed = sorted(set(prior_public) - set(after))
    changed = sorted(k for k in set(after) & set(prior_public) if after[k] != prior_public[k])
    cfg = settings.load()
    summary = {
        "doc_id": did, "jurisdiction": row["jurisdictions"], "source_url": row["url"],
        "retrieved_at": row["retrieved_at"], "registered": bool(row["new"]), "live": live,
        "n_chunks": n_chunks, "n_candidates": n_candidates,
        "rules_new": new, "rules_changed": changed, "rules_removed": removed,
        "rules_unchanged": len(set(after) & set(prior_public)) - len(changed),
        "rules_from_doc": sorted(k for k, r in after.items() if r.get("source_doc_id") == did),
        "as_of": cfg["default_as_of"], "disclaimer": cfg["disclaimer"],
    }
    audit.log("incremental", "summary", None, **{k: v for k, v in summary.items() if k != "disclaimer"})
    return summary
