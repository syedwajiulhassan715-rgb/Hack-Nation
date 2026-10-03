"""Ingest: manifest + text files -> outputs/docs.jsonl (BACKEND_PLAN.md 2.1).

One record per manifest row (all 87, plus any supplement rows). Text is kept as the
full stored file so every offset (body_offset, chunk and span offsets) refers to the
file on disk. Documents without usable text are recorded with text_available=false
and a reason; they are never extracted.

Fail closed: a text file whose two-line header is missing, or whose SOURCE url differs
from its manifest url, is treated as unavailable (we could not cite it correctly).
The manifest sha256 hashes the original capture, not the text (NOTES.md), so it is
kept as `source_sha256` only; `text_sha256` is ours.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from navigator import audit, settings

STATE_RE = re.compile(r"^[A-Z]{2}$")
CITY_RE = re.compile(r"^[^,]+, [A-Z]{2}$")


class Doc(BaseModel):
    doc_id: str
    jurisdiction: str
    level: Literal["state", "city"] | None
    url: str
    source_type: str
    capture: str
    manifest_status: str
    retrieved_at: str | None
    source_sha256: str | None
    origin: Literal["starter", "supplement"]
    text_file: str | None            # repo-relative path
    text_available: bool
    unavailable_reason: str | None = None
    text_sha256: str | None = None
    body_offset: int | None = None   # start of the body in `text` (after the header)
    n_chars: int | None = None
    warnings: list[str] = Field(default_factory=list)
    text: str | None = None          # full stored file, header included


def jurisdiction_level(jurisdiction: str) -> Literal["state", "city"] | None:
    if STATE_RE.fullmatch(jurisdiction):
        return "state"
    if CITY_RE.fullmatch(jurisdiction):
        return "city"
    return None


def parse_header(text: str) -> tuple[str, str, int] | None:
    """Return (source_url, retrieved, body_offset) or None if the header is malformed."""
    lines = text.split("\n", 3)
    if len(lines) < 4 or not lines[0].startswith("SOURCE: ") or not lines[1].startswith("RETRIEVED: ") or lines[2].strip():
        return None
    body_offset = len(lines[0]) + len(lines[1]) + len(lines[2]) + 3
    return lines[0][len("SOURCE: "):].strip(), lines[1][len("RETRIEVED: "):].strip(), body_offset


def _header_time_to_manifest(header: str) -> str:
    """'2026-10-01 22:35 UTC' -> '2026-10-01T22:35Z' (manifest format)."""
    return header.removesuffix(" UTC").replace(" ", "T") + "Z" if header.endswith(" UTC") else header


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(settings.REPO_ROOT).as_posix()
    except ValueError:  # outside the repo (e.g. a document dropped in for ingest-doc)
        return path.resolve().as_posix()


def load_doc(row: dict[str, str], base_dir: Path, origin: Literal["starter", "supplement"]) -> Doc:
    jurisdiction = row["jurisdictions"].strip()
    level = jurisdiction_level(jurisdiction)
    warnings: list[str] = []
    if level is None:
        warnings.append(f"jurisdiction {jurisdiction!r} is neither 'ST' nor 'City, ST'")
    rel = row.get("text_file", "").strip()
    path = base_dir / rel if rel else None
    doc = Doc(
        doc_id=row["doc_id"].strip(), jurisdiction=jurisdiction, level=level, url=row["url"].strip(),
        source_type=row["source_type"], capture=row["capture"], manifest_status=row["status"],
        retrieved_at=row.get("retrieved_at") or None, source_sha256=row.get("sha256") or None,
        origin=origin, text_file=_display_path(path) if path else None,
        text_available=False, warnings=warnings,
    )

    def unavailable(reason: str) -> Doc:
        doc.unavailable_reason = reason
        return doc

    if path is None:
        return unavailable(f"no text supplied ({row['capture']}, {row['status']})")
    if not path.is_file():
        return unavailable(f"text file not found: {rel}")
    raw = path.read_bytes()
    if not raw:
        return unavailable(f"empty text file ({row['status']})")
    if origin == "supplement" and row["source_type"] != "official":
        return unavailable("supplement documents must be official sources (CONTRACT.md 6)")
    text = raw.decode("utf-8")
    header = parse_header(text)
    if header is None:
        return unavailable("missing SOURCE:/RETRIEVED: header")
    source_url, retrieved, body_offset = header
    if source_url != doc.url:
        return unavailable(f"header SOURCE {source_url!r} differs from manifest url")
    if doc.retrieved_at is None:
        doc.retrieved_at = _header_time_to_manifest(retrieved)
        doc.warnings.append("retrieved_at taken from file header (manifest empty)")
    elif _header_time_to_manifest(retrieved) != doc.retrieved_at:
        doc.warnings.append(f"header RETRIEVED {retrieved!r} differs from manifest {doc.retrieved_at!r}; manifest used")
    if level is None:
        return unavailable("jurisdiction not resolvable to state or city level")
    doc.text_available = True
    doc.text = text
    doc.text_sha256 = hashlib.sha256(raw).hexdigest()
    doc.body_offset = body_offset
    doc.n_chars = len(text)
    return doc


def read_manifest(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def load_all() -> list[Doc]:
    sources: list[tuple[Path, Literal["starter", "supplement"]]] = [(settings.path("manifest"), "starter")]
    supplement = settings.path("supplement") / "manifest.csv"
    if supplement.is_file():
        sources.append((supplement, "supplement"))
    docs: dict[str, Doc] = {}
    for manifest_path, origin in sources:
        for row in read_manifest(manifest_path):
            doc = load_doc(row, manifest_path.parent, origin)
            if doc.doc_id in docs:
                raise ValueError(f"duplicate doc_id {doc.doc_id} in {manifest_path}")
            docs[doc.doc_id] = doc
    return [docs[k] for k in sorted(docs)]


def write_docs(docs: list[Doc], path: Path | None = None) -> Path:
    path = path or settings.path("outputs") / "docs.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for d in docs:
            fh.write(json.dumps(d.model_dump(mode="json"), ensure_ascii=False) + "\n")
    return path


def read_docs(path: Path | None = None) -> list[Doc]:
    path = path or settings.path("outputs") / "docs.jsonl"
    with path.open(encoding="utf-8") as fh:
        return [Doc.model_validate_json(line) for line in fh if line.strip()]


def run() -> None:
    docs = load_all()
    for d in docs:
        audit.log("ingest", "text" if d.text_available else "no_text",
                  d.unavailable_reason, doc_id=d.doc_id, text_sha256=d.text_sha256,
                  warnings=d.warnings or None)
    path = write_docs(docs)
    n_text = sum(d.text_available for d in docs)
    n_warn = sum(bool(d.warnings) for d in docs)
    print(f"ingested {len(docs)} documents: {n_text} with text, {len(docs) - n_text} without; "
          f"{n_warn} with warnings -> {path.relative_to(settings.REPO_ROOT).as_posix()}")
