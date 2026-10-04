"""Pydantic response/request models: the frontend generates its types from /openapi.json.

Shapes follow BACKEND_PLAN.md 3 (`LookupResult`) and FRONTEND_PLAN.md 5. Every response
carries `as_of`, `generated_at` and `disclaimer` (golden rule 10).
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from navigator.schema.models import Category, Level, Result, RuleInternal, Status

Role = Literal["tenant", "owner"]


class Envelope(BaseModel):
    as_of: str = Field(description="query date YYYY-MM-DD")
    generated_at: str | None = Field(description="when the underlying data was computed (UTC)")
    disclaimer: str


class ErrorResponse(BaseModel):
    detail: str
    disclaimer: str


# ---------------------------------------------------------------- health


class HealthResponse(Envelope):
    status: Literal["ok", "degraded"]
    stub_outputs: bool
    files: dict[str, bool]
    rules: int | None = None
    addresses: int | None = None


# ---------------------------------------------------------------- resolve / search


class ResolveResponse(Envelope):
    lat: float
    lng: float
    state: str | None
    city: str | None
    nearest_address_id: str | None
    distance_m: float | None
    max_distance_m: float
    address: str | None = None
    note: str | None = None


class SearchHit(BaseModel):
    address_id: str
    address: str
    street_address: str
    postal_city: str | None
    state: str
    city: str | None
    zip: str | None
    lat: float | None
    lng: float | None


class SearchResponse(Envelope):
    query: str
    match: Literal["text", "zip"]
    note: str | None = None
    results: list[SearchHit]


# ---------------------------------------------------------------- lookup


class JurisdictionLevel(BaseModel):
    level: Level
    jurisdiction: str
    name: str
    confirmed: bool = True


class BuildingFacts(BaseModel):
    year_built: int | None = None
    units: int | None = None
    units_min: int | None = None
    units_max: int | None = None
    units_source: str | None = None
    use_description: str | None = None
    postal_city: str | None = None
    legal_city: str | None = None
    jurisdiction_confidence: str | None = None
    jurisdiction_source: str | None = None
    lat: float | None = None
    lng: float | None = None


class LookupRowOut(BaseModel):
    team_rule_id: str
    result: Result
    status: Status = Field(description="rule status on as_of (recomputed from effective_date)")
    level: Level
    jurisdiction: str
    category: Category
    title: str
    answer: str | None = Field(description="plain-language answer for the role; null -> show the quote")
    answer_lang: str | None = None
    explanation: str
    requirement: str
    key_value: str | None = None
    quoted_span: str
    citation: str
    source_doc_id: str | None = None
    source_url: str
    retrieved_at: str | None = None
    effective_date: str | None = None
    missing_facts: list[str] = Field(default_factory=list)
    superseded_by: str | None = None
    superseded_by_citation: str | None = None
    conflict_flag: bool = False
    conflict_note: str | None = None
    confidence: float | None = None
    confidence_reasons: list[str] = Field(default_factory=list)
    needs_review: bool = False
    review_reasons: list[str] = Field(default_factory=list)
    checked: list[str] = Field(default_factory=list)
    not_checked: list[str] = Field(default_factory=list)


class CategoryBlock(BaseModel):
    category: Category
    question: str
    question_tenant: str
    question_owner: str
    rows: list[LookupRowOut]
    no_rule_note: str | None = None


class NoteOut(BaseModel):
    jurisdiction: str
    text: str
    date: str | None = None
    team_rule_id: str | None = None
    citation: str | None = None
    quoted_span: str | None = None
    source_url: str | None = None
    retrieved_at: str | None = None


class LookupResult(Envelope):
    address_id: str
    address: str
    role: Role
    lang: str
    computed: Literal["precomputed", "live"]
    jurisdiction_stack: list[JurisdictionLevel]
    facts: BuildingFacts
    user_facts: dict[str, int] = Field(default_factory=dict)
    missing_facts: list[str] = Field(default_factory=list)
    categories: list[CategoryBlock]
    notes: list[NoteOut] = Field(default_factory=list)


class UserFacts(BaseModel):
    year_built: int | None = Field(default=None, ge=1800)
    units: int | None = Field(default=None, ge=1, le=2000)
    units_min: int | None = Field(default=None, ge=1, le=2000)
    units_max: int | None = Field(default=None, ge=1, le=2000)


class LookupRequest(BaseModel):
    address_id: str | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    facts: UserFacts = Field(default_factory=UserFacts)
    as_of: str | None = None
    role: Role = "tenant"
    lang: str = "en"


# ---------------------------------------------------------------- rule detail


class Offsets(BaseModel):
    span_start: int
    span_end: int
    window_start: int
    window_end: int
    span_start_in_window: int
    span_end_in_window: int


class TextWindow(BaseModel):
    doc_id: str
    text: str
    offsets: Offsets = Field(description="Python code-point offsets (file-relative and window-relative)")
    offsets_utf16: Offsets = Field(description="UTF-16 code-unit offsets for JavaScript string indexing")
    span_text: str = Field(description="file text between span_start and span_end")
    span_text_equals_quote: bool


class RuleDetail(Envelope):
    rule: RuleInternal
    status_on_as_of: Status
    source_url: str
    retrieved_at: str | None
    answer_tenant: str | None = None
    answer_owner: str | None = None
    text_window: TextWindow | None = None
    highlight: Literal["offsets", "substring", "none"]
    note: str | None = None


# ---------------------------------------------------------------- timeline / snapshots


class TimelineChange(BaseModel):
    team_rule_id: str
    from_: str | None = Field(default=None, alias="from")
    to: str | None = None

    model_config = {"populate_by_name": True, "serialize_by_alias": True}


class TimelineEntry(BaseModel):
    date: str
    changes: list[TimelineChange]


class TimelineResponse(Envelope):
    address_id: str
    dates: list[str] = Field(description="global key dates (all addresses)")
    timeline: list[TimelineEntry]


class SnapshotCell(BaseModel):
    result: Result
    conflict_flag: bool
    rules: int


class SnapshotsResponse(Envelope):
    dates: list[str]
    snapshots: dict[str, dict[str, dict[str, SnapshotCell]]] = Field(
        description="date -> address_id -> category -> winning result")


class SnapshotResponse(Envelope):
    date: str
    snapshot: dict[str, dict[str, SnapshotCell]]


# ---------------------------------------------------------------- changes


class ChangeCheck(BaseModel):
    name: str
    passed: bool | None
    detail: str | None = None


class ChangeTestOut(BaseModel):
    test_id: str
    title: str | None = None
    type: str | None = None
    expected_behavior: str | None = None
    affected_address_ids: list[str]
    conflict_flag_address_ids: list[str]
    affected_count: int
    conflict_count: int
    notes: str
    notes_list: list[str] = Field(default_factory=list)
    checks: list[ChangeCheck] = Field(default_factory=list)


class ChangesResponse(Envelope):
    mapping_reviewed: bool | None = None
    tests: list[ChangeTestOut]


class ChangeResponse(Envelope):
    mapping_reviewed: bool | None = None
    test: ChangeTestOut


# ---------------------------------------------------------------- audit / eval / ingest


class AuditResponse(Envelope):
    team_rule_id: str
    provenance: list[dict[str, Any]]
    entries: list[dict[str, Any]]
    note: str


class EvalResponse(Envelope):
    label: str
    report: str
