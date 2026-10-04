"""[8] Determinism: the deterministic stages, re-run twice from the committed inputs and the
LLM cache, must write byte-identical files, equal to the committed outputs/.

Stages re-run: verify (rules.json, rules_internal.json, rejects.jsonl), lookups (lookups.json,
lookups_internal.json, timeline.json, snapshots.json), changes (changes.json,
changes_internal.json) and summaries (summaries.json, LLM answers from cache only).
Inputs copied from outputs/: docs.jsonl, candidates.jsonl, parcels.json (ingest, extract and
geocode are not re-run).

Each run is a separate Python process (`--worker`) with a different PYTHONHASHSEED, so set
or dict ordering that depends on string hashing shows up as a difference. In the worker,
`settings.path("outputs")` and `settings.path("scores")` point into the temporary run
directory; the real outputs/, scores/, cache/ and config/test_rule_map.yaml are never
written (checked by a before/after fingerprint). The Anthropic client is replaced by a stub
that records the miss and raises: any cache miss fails the check loudly, no API call is made.

Excluded by design, nothing else: the top-level `generated_at` timestamp in
changes_internal.json and summaries.json (wall-clock time of the run). The audit log
(audit.jsonl) is an append-only, timestamped log and is not compared.

`python -m eval.determinism` writes scores/determinism.json; `section(rep, out_dir)` reads it.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from navigator import settings

INPUTS = ["docs.jsonl", "candidates.jsonl", "parcels.json"]
COMPARED = ["rules.json", "rules_internal.json", "rejects.jsonl",
            "lookups.json", "lookups_internal.json", "timeline.json", "snapshots.json",
            "changes.json", "changes_internal.json", "summaries.json"]
# file -> top-level fields whose value is a wall-clock timestamp. Nothing else is excluded.
EXCLUDED_FIELDS: dict[str, list[str]] = {
    "changes_internal.json": ["generated_at"],
    "summaries.json": ["generated_at"],
}
SEEDS = ("1", "2")
WORKER_TIMEOUT = 1800
MISS_FILE = "cache_misses.json"
# Never written by the check; fingerprinted before and after the run.
GUARDED = ["outputs", "cache", "config/test_rule_map.yaml"]


class CacheMiss(RuntimeError):
    pass


# ------------------------------------------------------------------ comparison


def normalize(name: str, data: bytes) -> bytes:
    """Replace the value of each excluded top-level field with a fixed marker.

    Only a field at the top level of the JSON object (one indent step) is touched; the field
    must exist exactly once there, otherwise the bytes are returned unchanged so the files
    still compare raw (a missing timestamp is not silently ignored)."""
    lines = data.split(b"\n", 2)
    if len(lines) < 2:
        return data
    # summaries.json uses indent=1, changes_internal.json indent=2: the top-level indent is
    # the second line's, and only lines with exactly that indent are considered.
    indent = len(lines[1]) - len(lines[1].lstrip(b" "))
    if indent == 0:
        return data
    for field in EXCLUDED_FIELDS.get(name, []):
        pattern = re.compile(rb'(?m)^( {' + str(indent).encode() + rb'}"' + re.escape(field.encode())
                             + rb'": )"[^"\n]*"')
        matches = pattern.findall(data)
        if len(matches) == 1:
            data = pattern.sub(rb'\1"<excluded>"', data)
    return data


def compare_bytes(name: str, a: bytes | None, b: bytes | None) -> str:
    if a is None or b is None:
        return "missing"
    return "identical" if normalize(name, a) == normalize(name, b) else "differs"


def first_difference(name: str, a: bytes, b: bytes) -> str:
    """Short diagnosis: first differing line (1-based) with both versions, truncated."""
    la, lb = normalize(name, a).split(b"\n"), normalize(name, b).split(b"\n")
    for i, (x, y) in enumerate(zip(la, lb), 1):
        if x != y:
            return (f"line {i}: {x[:160].decode('utf-8', 'replace')!r} vs "
                    f"{y[:160].decode('utf-8', 'replace')!r}")
    return f"line count {len(la)} vs {len(lb)}"


def _read(path: Path) -> bytes | None:
    return path.read_bytes() if path.is_file() else None


def compare_dirs(run1: Path, run2: Path, committed: Path) -> dict[str, Any]:
    files: dict[str, str] = {}
    detail: dict[str, Any] = {}
    for name in COMPARED:
        a, b, c = _read(run1 / name), _read(run2 / name), _read(committed / name)
        runs = compare_bytes(name, a, b)
        vs_committed = compare_bytes(name, a, c)
        files[name] = "identical" if runs == vs_committed == "identical" else "differs"
        d: dict[str, Any] = {"run1_vs_run2": runs, "run_vs_committed": vs_committed}
        if runs == "differs":
            d["run_diff"] = first_difference(name, a, b)
        if vs_committed == "differs":
            d["committed_diff"] = first_difference(name, a, c)
        detail[name] = d
    return {"files": files, "detail": detail}


# ------------------------------------------------------------------ safety


def fingerprint(paths: list[str] = GUARDED) -> dict[str, list]:
    """(size, mtime_ns, sha256) of every file under the guarded paths."""
    out: dict[str, list] = {}
    for rel in paths:
        root = settings.REPO_ROOT / rel
        files = [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file()) if root.is_dir() else []
        for f in files:
            st = f.stat()
            out[f.relative_to(settings.REPO_ROOT).as_posix()] = [
                st.st_size, st.st_mtime_ns, hashlib.sha256(f.read_bytes()).hexdigest()]
    return out


def fingerprint_changes(before: dict[str, list], after: dict[str, list]) -> list[str]:
    keys = sorted(set(before) | set(after))
    return [k for k in keys if before.get(k) != after.get(k)]


# ------------------------------------------------------------------ worker


def _redirect_paths(out: Path, scores: Path) -> None:
    original = settings.path

    def path(key: str) -> Path:
        if key == "outputs":
            return out
        if key == "scores":
            return scores
        return original(key)

    settings.path = path  # every navigator module calls settings.path(...) at run time


def _block_api(misses: list[str]) -> None:
    from navigator.extract import llm

    def no_client():
        misses.append("LLM cache miss: a stage asked for the Anthropic client")
        raise CacheMiss("determinism check: LLM cache miss; refusing to call the API")

    llm._get_client = no_client


def worker(run_dir: Path) -> int:
    """Run verify, lookups, changes, summaries into run_dir/outputs. Exit 3 on a cache miss."""
    out, scores = run_dir / "outputs", run_dir / "scores"
    out.mkdir(parents=True, exist_ok=True)
    scores.mkdir(parents=True, exist_ok=True)
    real_out = settings.REPO_ROOT / settings.load()["paths"]["outputs"]
    for name in INPUTS:
        shutil.copy2(real_out / name, out / name)
    _redirect_paths(out, scores)
    misses: list[str] = []
    _block_api(misses)

    from navigator.changes import matcher, tracker
    from navigator.engine import lookup
    from navigator.explain import plain
    from navigator.verify import gates

    original_resolve = matcher.resolve
    matcher.resolve = lambda rules, write=True: original_resolve(rules, write=False)

    timings: dict[str, float] = {}
    for name, fn in (
        ("verify", gates.run),
        ("lookups", lambda: lookup.run(out_dir=out)),
        ("changes", lambda: tracker.run(out_dir=out)),
        ("summaries", lambda: plain.run(rules_path=out / "rules_internal.json",
                                        out_path=out / "summaries.json")),
    ):
        t0 = time.monotonic()
        fn()
        timings[name] = round(time.monotonic() - t0, 1)
    (run_dir / MISS_FILE).write_text(json.dumps({"misses": misses, "timings": timings}),
                                     encoding="utf-8")
    return 3 if misses else 0


# ------------------------------------------------------------------ check


def _spawn(run_dir: Path, seed: str) -> dict[str, Any]:
    env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONIOENCODING": "utf-8"}
    env.pop("ANTHROPIC_API_KEY", None)
    proc = subprocess.run([sys.executable, "-m", "eval.determinism", "--worker", str(run_dir)],
                          cwd=settings.REPO_ROOT, env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=WORKER_TIMEOUT)
    info = {"seed": seed, "returncode": proc.returncode}
    mf = run_dir / MISS_FILE
    if mf.is_file():
        info.update(json.loads(mf.read_text(encoding="utf-8")))
    if proc.returncode != 0:
        info["stderr_tail"] = proc.stderr[-2000:]
    return info


def check(tmp_dir: Path) -> dict[str, Any]:
    """Two isolated runs into tmp_dir/run1 and tmp_dir/run2, compared with each other and
    with the committed outputs/. Never writes outside tmp_dir."""
    tmp_dir = Path(tmp_dir)
    committed = settings.REPO_ROOT / settings.load()["paths"]["outputs"]
    before = fingerprint()
    t0 = time.monotonic()
    runs = [_spawn(tmp_dir / f"run{i}", seed) for i, seed in enumerate(SEEDS, 1)]
    seconds = round(time.monotonic() - t0, 1)
    touched = fingerprint_changes(before, fingerprint())

    result: dict[str, Any] = {"excluded_fields": EXCLUDED_FIELDS, "runs": runs, "seconds": seconds,
                              "guarded_paths_touched": touched}
    errors = []
    for r in runs:
        if r.get("misses"):
            errors.append(f"seed {r['seed']}: {len(r['misses'])} LLM cache misses (API blocked)")
        if r["returncode"] != 0:
            errors.append(f"seed {r['seed']}: worker exit {r['returncode']}")
    if touched:
        errors.append(f"guarded files changed during the check: {touched[:10]}")
    result.update(compare_dirs(tmp_dir / "run1" / "outputs", tmp_dir / "run2" / "outputs", committed))
    result["errors"] = errors
    result["ok"] = not errors and all(v == "identical" for v in result["files"].values())
    return result


def _git(*args: str) -> str | None:
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True,
                              cwd=settings.REPO_ROOT, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    if argv[:1] == ["--worker"]:
        return worker(Path(argv[1]))
    commit = _git("rev-parse", "--short", "HEAD")
    dirty = bool(_git("status", "--porcelain", "--", "navigator", "eval", "config", "outputs", "cache"))
    with tempfile.TemporaryDirectory(prefix="navigator-determinism-") as tmp:
        result = check(Path(tmp))
    doc = {"ts": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "commit": commit, "tree_dirty": dirty, **result}
    scores = settings.path("scores")
    scores.mkdir(parents=True, exist_ok=True)
    (scores / "determinism.json").write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                                             encoding="utf-8", newline="\n")
    for name, state in doc["files"].items():
        print(f"{state:9s} {name}  {doc['detail'][name]}")
    for e in doc["errors"]:
        print(f"ERROR: {e}")
    print(f"determinism {'PASS' if doc['ok'] else 'FAIL'} in {doc['seconds']}s "
          f"(commit {commit}{', dirty tree' if dirty else ''}) -> scores/determinism.json")
    return 0 if doc["ok"] else 1


# ------------------------------------------------------------------ eval section


def section(rep: Any, out_dir: Path, scores_dir: Path | None = None) -> None:
    rep.lines.append("[8] Determinism (two cached runs byte-identical; `python -m eval.determinism`)")
    path = (scores_dir or settings.path("scores")) / "determinism.json"
    if not path.is_file():
        rep.lines.append("  [n/a ] not run: scores/determinism.json missing; run `python -m eval.determinism`")
        rep.metrics["determinism"] = {"state": "not run"}
        return
    doc = json.loads(path.read_text(encoding="utf-8"))
    head = _git("rev-parse", "--short", "HEAD")
    stale = doc.get("commit") != head
    excluded = ", ".join(f"{f}:{'/'.join(v)}" for f, v in (doc.get("excluded_fields") or {}).items())
    rep.lines.append(f"  [info] run {doc.get('ts')} at commit {doc.get('commit')}"
                     f"{' (dirty tree)' if doc.get('tree_dirty') else ''}, {doc.get('seconds')}s; "
                     f"excluded fields: {excluded or 'none'}")
    if stale:
        rep.lines.append(f"  [info] stale: run at commit {doc.get('commit')}, HEAD is {head}; re-run it")
    files = doc.get("files") or {}
    differ = [n for n, s in files.items() if s != "identical"]
    for name, state in files.items():
        d = (doc.get("detail") or {}).get(name, {})
        extra = "" if state == "identical" else (
            f" (runs {d.get('run1_vs_run2')}, vs committed {d.get('run_vs_committed')}; "
            f"{d.get('run_diff') or d.get('committed_diff') or ''})")
        rep.lines.append(f"    {state:9s} {name}{extra}")
    errors = doc.get("errors") or []
    for e in errors:
        rep.lines.append(f"    error: {e}")
    ok = not differ and not errors and bool(files)
    # A stale result describes another commit: shown, but only a current mismatch is hard.
    rep.check("determinism_identical", f"{len(files) - len(differ)}/{len(files)} files byte-identical "
              "(run 1 = run 2 = committed outputs/)" + (" [stale]" if stale else ""), ok,
              "" if ok else f"differs: {', '.join(differ) or 'none'}; errors: {len(errors)}",
              hard=not stale)
    ok_key = rep.metrics.pop("determinism_identical")
    rep.metrics["determinism"] = {"state": "stale" if stale else "current", "ok": ok_key,
                                  "commit": doc.get("commit"), "files": files}


if __name__ == "__main__":
    sys.exit(main())
