"""Read-only access to the precomputed outputs the API serves (golden rule 5).

Files are parsed lazily and re-read when their mtime or size changes, so a pipeline
re-run is picked up without restarting the server. A missing required file raises
`DataUnavailable` (the API turns it into HTTP 503); it is never read as "no rules".
"""
from __future__ import annotations

import datetime as dt
import json
import threading
from pathlib import Path
from typing import Any, Callable

from navigator import settings, starter
from navigator.schema.models import RuleInternal

# file name -> pipeline command that produces it (used in 503 messages)
PRODUCERS: dict[str, str] = {
    "rules_internal.json": "python -m navigator verify",
    "parcels.json": "python -m navigator geocode",
    "lookups_internal.json": "python -m navigator lookups",
    "timeline.json": "python -m navigator lookups",
    "snapshots.json": "python -m navigator lookups",
    "changes.json": "python -m navigator changes",
    "changes_internal.json": "python -m navigator changes",
    "docs.jsonl": "python -m navigator ingest",
    "audit.jsonl": "any pipeline stage",
    "summaries.json": "python -m navigator summaries",
    "eval_latest.txt": "python -m navigator eval",
}


class DataUnavailable(Exception):
    """A precomputed file the request needs is missing, unreadable or a stub."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def iso_utc(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Store:
    def __init__(self, outputs_dir: Path | None = None, scores_dir: Path | None = None):
        self.outputs = Path(outputs_dir) if outputs_dir else settings.path("outputs")
        self.scores = Path(scores_dir) if scores_dir else settings.path("scores")
        self._cache: dict[str, tuple[tuple, Any]] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------ plumbing

    def path(self, name: str) -> Path:
        return (self.scores if name == "eval_latest.txt" else self.outputs) / name

    def exists(self, name: str) -> bool:
        return self.path(name).is_file()

    def mtime(self, name: str) -> str | None:
        p = self.path(name)
        return iso_utc(p.stat().st_mtime) if p.is_file() else None

    def _sig(self, names: tuple[str, ...]) -> tuple:
        out = []
        for n in names:
            p = self.path(n)
            if not p.is_file():
                hint = PRODUCERS.get(n, "the pipeline")
                raise DataUnavailable(f"{p.name} is not available; run `{hint}` first. "
                                      "No answer is given rather than an empty one (fail closed).")
            st = p.stat()
            out.append((n, st.st_mtime_ns, st.st_size))
        return tuple(out)

    def cached(self, key: str, names: tuple[str, ...], build: Callable[[], Any]) -> Any:
        with self._lock:
            sig = self._sig(names)
            hit = self._cache.get(key)
            if hit is not None and hit[0] == sig:
                return hit[1]
            try:
                value = build()
            except DataUnavailable:
                raise
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise DataUnavailable(f"{', '.join(names)} could not be read: {exc}") from exc
            self._cache[key] = (sig, value)
            return value

    def _json(self, name: str) -> Any:
        return json.loads(self.path(name).read_text(encoding="utf-8"))

    def is_stub(self) -> bool:
        return (self.outputs / "STUB").is_file()

    def require_real(self) -> None:
        if self.is_stub():
            raise DataUnavailable("outputs are stubs (outputs/STUB exists): lookups were not computed. "
                                  "Run the pipeline (`python -m navigator all`) first.")

    # ------------------------------------------------------------ rules

    def rules_file(self) -> dict[str, Any]:
        def build():
            data = self._json("rules_internal.json")
            rules = [RuleInternal.model_validate(r) for r in data["rules"]]
            return {"as_of": data.get("as_of"), "list": rules, "by_id": {r.team_rule_id: r for r in rules}}
        return self.cached("rules", ("rules_internal.json",), build)

    def rules(self) -> list[RuleInternal]:
        return self.rules_file()["list"]

    def rule(self, team_rule_id: str) -> RuleInternal | None:
        return self.rules_file()["by_id"].get(team_rule_id)

    # ------------------------------------------------------------ parcels

    def parcels(self) -> dict[str, dict[str, Any]]:
        def build():
            data = self._json("parcels.json")
            items = data["parcels"] if isinstance(data, dict) else data
            return {str(p["address_id"]): p for p in items}
        return self.cached("parcels", ("parcels.json",), build)

    def zips(self) -> dict[str, str]:
        try:
            return {r["address_id"]: r.get("zip") or "" for r in starter.addresses()}
        except OSError:
            return {}

    # ------------------------------------------------------------ lookups

    def lookups(self) -> dict[str, Any]:
        return self.cached("lookups", ("lookups_internal.json",), lambda: self._json("lookups_internal.json"))

    def timeline(self) -> dict[str, Any]:
        return self.cached("timeline", ("timeline.json",), lambda: self._json("timeline.json"))

    def snapshots(self) -> dict[str, Any]:
        return self.cached("snapshots", ("snapshots.json",), lambda: self._json("snapshots.json"))

    # ------------------------------------------------------------ changes

    def changes(self) -> dict[str, Any]:
        return self.cached("changes", ("changes.json",), lambda: self._json("changes.json"))

    def changes_internal(self) -> dict[str, Any] | None:
        if not self.exists("changes_internal.json"):
            return None
        return self.cached("changes_internal", ("changes_internal.json",),
                            lambda: self._json("changes_internal.json"))

    # ------------------------------------------------------------ documents, audit, summaries

    def docs(self) -> dict[str, dict[str, Any]]:
        def build():
            out = {}
            with self.path("docs.jsonl").open(encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        d = json.loads(line)
                        out[d["doc_id"]] = d
            return out
        return self.cached("docs", ("docs.jsonl",), build)

    def doc_text(self, doc_id: str) -> str | None:
        """Full stored text (header included) so rule offsets index into it directly."""
        rec = self.docs().get(doc_id)
        if rec and rec.get("text"):
            return rec["text"]
        return None

    def audit(self) -> list[dict[str, Any]]:
        def build():
            out = []
            with self.path("audit.jsonl").open(encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        try:
                            out.append(json.loads(line))
                        except ValueError:
                            continue          # a torn last line from a concurrent writer
            return out
        return self.cached("audit", ("audit.jsonl",), build)

    def summaries(self) -> dict[str, dict[str, Any]]:
        """outputs/summaries.json if present, else {} (the UI then shows the quote)."""
        if not self.exists("summaries.json"):
            return {}
        try:
            data = self.cached("summaries", ("summaries.json",), lambda: self._json("summaries.json"))
        except DataUnavailable:
            return {}
        return data.get("summaries", {}) if isinstance(data, dict) else {}

    def eval_report(self) -> str:
        return self.cached("eval", ("eval_latest.txt",),
                            lambda: self.path("eval_latest.txt").read_text(encoding="utf-8"))
