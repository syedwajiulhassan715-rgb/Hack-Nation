"""Command-line entry point: `python -m navigator <stage>`.

Each stage maps to a function in its module. Stages that are not built yet
raise NotImplementedError naming the phase that builds them; the CLI reports
that and exits non-zero instead of pretending to succeed.
"""
from __future__ import annotations

import argparse
import importlib
import sys

from navigator import settings

# stage name -> (module, function, help, phase that implements it)
STAGES: dict[str, tuple[str, str, str, int]] = {
    "stubs": ("navigator.stubs", "run", "write empty, contract-valid stub outputs (marks outputs/STUB)", 1),
    "ingest": ("navigator.ingest.corpus", "run", "manifest + text files -> outputs/docs.jsonl", 2),
    "chunk": ("navigator.extract.chunk", "run", "docs.jsonl -> outputs/chunks.jsonl (deterministic)", 2),
    "extract": ("navigator.extract.extract", "run", "LLM extraction (cached) -> outputs/candidates.jsonl", 3),
    "verify": ("navigator.verify.gates", "run", "gates + dates -> rules.json, rules_internal.json, rejects.jsonl", 3),
    "geocode": ("navigator.geo.geocode", "run", "addresses -> outputs/parcels.json", 4),
    "lookups": ("navigator.engine.lookup", "run", "engine -> lookups.json, timeline.json, snapshots.json", 5),
    "changes": ("navigator.changes.tracker", "run", "change tests -> outputs/changes.json", 6),
    "summaries": ("navigator.explain.plain", "run", "plain-language answers -> outputs/summaries.json", 8),
    "eval": ("eval.run_eval", "run", "self-evaluation -> scores/eval_latest.txt, scores/history.jsonl", 1),
}
PIPELINE = ["ingest", "chunk", "extract", "verify", "geocode", "lookups", "changes"]


def _run_stage(name: str, **kwargs) -> None:
    module_name, func_name, _, phase = STAGES[name]
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        # Only "the stage module does not exist yet" counts as unbuilt; a missing
        # third-party dependency inside a built module must surface as an error.
        if exc.name is None or not module_name.startswith(exc.name):
            raise
        raise NotImplementedError(f"stage '{name}' is built in phase {phase}") from exc
    func = getattr(module, func_name, None)
    if func is None:
        raise NotImplementedError(f"stage '{name}' is built in phase {phase}")
    func(**kwargs)


def main(argv: list[str] | None = None) -> int:
    # The corpus has non-cp1252 characters (e.g. emoji in D084); Windows consoles
    # default to cp1252 and would crash on print.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        prog="navigator",
        description="Rental Housing Law Navigator pipeline. Not legal advice.",
    )
    sub = parser.add_subparsers(dest="stage", required=True)
    for name, (_, _, help_text, _) in STAGES.items():
        p = sub.add_parser(name, help=help_text)
        if name == "extract":
            p.add_argument("--docs", nargs="+", metavar="DOC_ID",
                           help="only these documents (vertical slice); others' candidates are kept")
            p.add_argument("--no-cache", action="store_true", help="ignore the LLM cache (live demo)")
    sub.add_parser("all", help="run " + " > ".join(PIPELINE))

    for name, help_text in (
        ("ingest-doc", "incremental run for new document(s)"),
        ("rerun-live", "same as ingest-doc with the LLM cache disabled (demo)"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("doc", help="path to a text file in corpus format (SOURCE:/RETRIEVED: header)")

    api = sub.add_parser("api", help="FastAPI server (default :8000)")
    api.add_argument("--host", default="127.0.0.1")
    api.add_argument("--port", type=int, default=8000)

    args = parser.parse_args(argv)
    try:
        if args.stage == "all":
            for name in PIPELINE:
                _run_stage(name)
        elif args.stage in ("ingest-doc", "rerun-live"):
            raise NotImplementedError(f"'{args.stage}' is built in phase 3")
        elif args.stage == "api":
            import uvicorn

            try:
                importlib.import_module("navigator.api.main")
            except ModuleNotFoundError as exc:
                raise NotImplementedError("'api' is built in phase 7") from exc
            uvicorn.run("navigator.api.main:app", host=args.host, port=args.port)
        elif args.stage == "extract":
            _run_stage("extract", docs=args.docs, no_cache=args.no_cache)
        else:
            _run_stage(args.stage)
    except NotImplementedError as exc:
        print(f"navigator: not implemented yet: {exc}", file=sys.stderr)
        return 2
    print(f"done. as_of default {settings.load()['default_as_of']}. {settings.load()['disclaimer']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
