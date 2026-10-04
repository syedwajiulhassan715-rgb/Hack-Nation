"""LLM rule extraction (BACKEND_PLAN.md 2.3): chunks -> outputs/candidates.jsonl.

The only stage that asks the model about law. It returns candidates, not rules: verify
checks every quote against the source text, resolves dates and assigns team_rule_ids.
Source fields (doc id, url, retrieval date) are copied from the manifest here, never from
the model.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path
from typing import Any

from navigator import audit, settings
from navigator.extract import llm
from navigator.extract.chunk import Chunk, prompt_text, read_chunks
from navigator.ingest.corpus import Doc, read_docs
from navigator.schema import facts
from navigator.schema.models import Category

PROMPT_DIR = Path(__file__).parent / "prompts"
CATEGORIES = list(Category.__args__)
WORKERS = 6


def _nullable(t: str) -> dict[str, Any]:
    return {"type": [t, "null"]}


RULE_FIELDS: dict[str, Any] = {
    "jurisdiction": {"type": "string"},
    "level": {"type": "string", "enum": ["state", "city"]},
    "category": {"type": "string", "enum": CATEGORIES},
    "status_hint": {"type": "string", "enum": ["enacted", "bill_or_proposal", "failed"]},
    "title": {"type": "string"},
    "requirement": {"type": "string"},
    "key_value": _nullable("string"),
    "coverage_text": _nullable("string"),
    "predicates_json": _nullable("string"),
    "exemptions": _nullable("string"),
    "citation": {"type": "string"},
    "penalty": _nullable("string"),
    "quoted_span": {"type": "string"},
    "effective_date_phrase": _nullable("string"),
    "effective_date_anchor": _nullable("string"),
    "interaction_text": _nullable("string"),
}

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "rules": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": RULE_FIELDS,
                "required": list(RULE_FIELDS),
                "additionalProperties": False,
            },
        }
    },
    "required": ["rules"],
    "additionalProperties": False,
}


@lru_cache(maxsize=None)
def _template(version: str) -> str:
    return (PROMPT_DIR / f"{version}.md").read_text(encoding="utf-8")


def build_prompt(doc: Doc, chunk: Chunk, n_chunks: int) -> tuple[str, str]:
    """(system, user). The system part is identical for every chunk."""
    head, _, _ = _template(settings.load()["llm"]["prompt_version"]).partition("## Document")
    system = head.replace("{facts}", facts.describe()).rstrip() + "\n"
    part = f"excerpt {chunk.chunk_id.rsplit('-c', 1)[-1].lstrip('0') or '1'} of {n_chunks}"
    user = (
        "## Document\n\n"
        f"- document id: {doc.doc_id}\n"
        f"- document jurisdiction: {doc.jurisdiction} ({doc.level} level)\n"
        f"- source type: {doc.source_type}\n"
        f"- source url: {doc.url}\n"
        f"- this is {part}"
        + (f"; nearest heading: {chunk.heading}" if chunk.heading else "")
        + "\n\n<excerpt>\n" + prompt_text(doc, chunk) + "\n</excerpt>\n"
    )
    return system, user


def extract_chunk(doc: Doc, chunk: Chunk, n_chunks: int, use_cache: bool = True) -> list[dict[str, Any]]:
    system, user = build_prompt(doc, chunk, n_chunks)
    result = llm.call_json(
        system=system, user=user, schema=OUTPUT_SCHEMA, use_cache=use_cache, label=chunk.chunk_id,
        key_parts={"text_sha256": doc.text_sha256, "chunk_id": chunk.chunk_id,
                   "chunker_version": chunk.chunker_version,
                   "char_range": [chunk.char_start, chunk.char_end]},
    )
    out = []
    for i, rule in enumerate(result["data"].get("rules", [])):
        out.append({
            "candidate_id": f"{chunk.chunk_id}-r{i + 1:02d}",
            "source_doc_id": doc.doc_id,
            "source_url": doc.url,
            "retrieved_at": doc.retrieved_at,
            "doc_jurisdiction": doc.jurisdiction,
            "doc_level": doc.level,
            "source_type": doc.source_type,
            **rule,
            "provenance": {"chunk_id": chunk.chunk_id, "char_start": chunk.char_start,
                           "char_end": chunk.char_end, "cache_key": result["cache_key"],
                           "cached": result["cached"], "model": result["model"],
                           "served_model": result["served_model"],
                           "prompt_version": settings.load()["llm"]["prompt_version"]},
        })
    audit.log("extract", "chunk_extracted", chunk_id=chunk.chunk_id, doc_id=doc.doc_id,
              n_candidates=len(out), cached=result["cached"])
    return out


def run(docs: list[str] | None = None, no_cache: bool = False) -> None:
    all_docs = {d.doc_id: d for d in read_docs() if d.text_available}
    chunks = read_chunks()
    if docs:
        missing = sorted(set(docs) - set(all_docs))
        if missing:
            raise SystemExit(f"no text available for: {', '.join(missing)}")
        chunks = [c for c in chunks if c.doc_id in set(docs)]
    per_doc: dict[str, int] = {}
    for c in chunks:
        per_doc[c.doc_id] = per_doc.get(c.doc_id, 0) + 1

    print(f"extracting {len(chunks)} chunks from {len(per_doc)} documents "
          f"(model {llm.stage_settings('extract')['model']}, cache {'off' if no_cache else 'on'})", flush=True)
    results: dict[str, list[dict[str, Any]]] = {}
    failures: list[str] = []

    def work(c: Chunk) -> None:
        try:
            results[c.chunk_id] = extract_chunk(all_docs[c.doc_id], c, per_doc[c.doc_id], not no_cache)
            print(f"  {c.chunk_id}: {len(results[c.chunk_id])} candidate(s)", flush=True)
        except Exception as exc:  # one bad chunk must not stop the run; it is reported below
            failures.append(c.chunk_id)
            audit.log("extract", "chunk_failed", str(exc), chunk_id=c.chunk_id, doc_id=c.doc_id)
            print(f"  {c.chunk_id}: FAILED ({exc})", flush=True)

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        list(pool.map(work, chunks))

    out_path = settings.path("outputs") / "candidates.jsonl"
    # A partial run (--docs) replaces only those documents' candidates.
    kept: list[str] = []
    if docs and out_path.exists():
        kept = [line for line in out_path.read_text(encoding="utf-8").splitlines()
                if line.strip() and json.loads(line)["source_doc_id"] not in set(docs)]
    rows = [json.dumps(r, ensure_ascii=False) for c in chunks for r in results.get(c.chunk_id, [])]
    lines = sorted(kept + rows, key=lambda s: json.loads(s)["candidate_id"])
    out_path.write_text("".join(line + "\n" for line in lines), encoding="utf-8", newline="\n")

    print(f"{len(rows)} candidates from {len(chunks) - len(failures)}/{len(chunks)} chunks -> "
          f"{out_path.relative_to(settings.REPO_ROOT).as_posix()}")
    if failures:
        raise SystemExit(f"{len(failures)} chunk(s) failed: {', '.join(sorted(failures))} "
                         "(see outputs/audit.jsonl); rerun to retry them")
