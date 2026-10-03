"""Pydantic models for the three submission files (docs/CONTRACT.md 2-4).

`RuleRecord`, `LookupRow` and `ChangeResult` match the official formats exactly;
tests/test_output_format.py checks them against schema/rule_record.schema.json.
Internal-only fields live in the `*Internal` subclasses and are stripped by the
writers (CLAUDE.md golden rule 6). Never rename a field here.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, RootModel

Level = Literal["state", "city"]
Category = Literal[
    "rent_increase_limits",
    "just_cause_eviction",
    "security_deposits",
    "application_screening_fees",
    "screening_restrictions",
    "algorithmic_rent_setting",
]
Status = Literal["in_force", "not_yet_effective", "pending", "failed"]
Result = Literal["applies", "unknown", "superseded", "not_yet_effective", "pending"]

PARTIAL_DATE = r"^\d{4}(-\d{2}(-\d{2})?)?$"
ISO_DATE = r"^\d{4}-\d{2}-\d{2}$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------- rules.json


class RuleRecord(_Strict):
    """One rule; fields and types exactly as schema/rule_record.schema.json."""

    team_rule_id: str
    jurisdiction: str
    level: Level
    category: Category
    status: Status
    title: str
    requirement: str
    key_value: str | None = None
    coverage_conditions: str | dict[str, Any] | None = None
    exemptions: str | None = None
    overrides: list[str] = Field(default_factory=list)
    interaction: str | None = None
    effective_date: str | None = Field(default=None, pattern=PARTIAL_DATE)
    citation: str
    source_doc_id: str | None = None
    source_url: str
    quoted_span: str = Field(min_length=20)
    confidence: float | None = Field(default=None, ge=0, le=1)
    conflict_flag: bool = False
    conflict_note: str | None = None


class RuleInternal(RuleRecord):
    """RuleRecord plus pipeline fields that never go into rules.json."""

    span_start: int | None = None          # offsets into the full stored file
    span_end: int | None = None
    span_match: Literal["exact", "normalized", "tolerant"] | None = None
    retrieved_at: str | None = None        # from the manifest, joined via source_doc_id
    penalty: str | None = None             # the brief asks for it; the schema has no field
    effective_date_phrase: str | None = None
    effective_date_anchor: str | None = None
    effective_date_method: str | None = None
    predicates: dict[str, Any] | None = None
    needs_review: bool = False
    review_reasons: list[str] = Field(default_factory=list)
    provenance: list[dict[str, Any]] = Field(default_factory=list)

    def to_record(self) -> RuleRecord:
        return RuleRecord.model_validate(self.model_dump(include=set(RuleRecord.model_fields)))


class RulesFile(_Strict):
    rules: list[RuleRecord]


# -------------------------------------------------------------- lookups.json


class LookupRow(_Strict):
    team_rule_id: str
    result: Result
    explanation: str = Field(min_length=1)
    conflict_flag: bool = False


class LookupRowInternal(LookupRow):
    checked: list[str] = Field(default_factory=list)
    not_checked: list[str] = Field(default_factory=list)
    missing_facts: list[str] = Field(default_factory=list)
    superseded_by: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    confidence_reasons: list[str] = Field(default_factory=list)

    def to_row(self) -> LookupRow:
        return LookupRow.model_validate(self.model_dump(include=set(LookupRow.model_fields)))


class LookupsFile(_Strict):
    as_of: str = Field(pattern=ISO_DATE)
    lookups: dict[str, list[LookupRow]]


# -------------------------------------------------------------- changes.json


class ChangeResult(_Strict):
    affected_address_ids: list[str]
    # Required here although the template omits it on T1: CONTRACT.md 4 says always include.
    conflict_flag_address_ids: list[str]
    notes: str


class ChangesFile(RootModel[dict[str, ChangeResult]]):
    pass
