# CLAUDE.md — Rental Housing Law Navigator

Read this file fully before any task. Then read, in this order:
1. `docs/CONTRACT.md` — exact formats and data facts from the starter pack (wins over everything)
2. `BACKEND_PLAN.md` — pipeline, engine, API, evaluation
3. `FRONTEND_PLAN.md` — for anything in `web/`
4. `data/starter/README.md` — the official participant guide

## What we are building

Hack-Nation Global Hackathon (RealPage challenge): Rental Housing Law Navigator (participant pack v5,
no scoring script, no hour-16 document). For any sample address: which housing rules
apply on the query date (default **2026-10-01**), and how the five supplied change cases
affect the answer. Every answer cites the source text.

Modules:
- **A, Rule extraction:** read each corpus document with text (54 of 87) and output one
  record per rule matching `schema/rule_record.schema.json`. Automated, not hand-coded.
  The demo must show the extraction pipeline running.
- **B, Address lookup:** resolve each of the 500 addresses to its legal state and city
  (postal city is not the legal city), test each rule's coverage, and report results:
  `applies`, `unknown`, `superseded`, `not_yet_effective`, `pending`. Leave out rules
  that don't apply.
- **C, Change tracking:** run T1 to T5 from `dev/change_tests.json`; list affected and
  conflict-flagged addresses; support any as-of date.

Minimum viable submission (guide section 2): A and B with accurate extraction,
jurisdiction resolution and citations. Then C and the plain-language view. Then stretch
goals (Spanish, confidence indicators, a new jurisdiction, audit view).

Scope: CA, NJ, MA; levels **state and city only**; 6 categories (`rent_increase_limits`,
`just_cause_eviction`, `security_deposits`, `application_screening_fees`,
`screening_restrictions`, `algorithmic_rent_setting`). Santa Ana rules are extracted but
there are no Santa Ana addresses.

Submission: `rules.json`, `lookups.json` (all 500 addresses), `changes.json` (T1 to T5),
live demo, one-page `METHOD.md`, GitHub repo with README.

Anchor: pick any building and get its rights label, every answer traced to the exact
sentence of law.

If organizers later hand out a scoring script, dev key or an extra test, add `make score`
and handle it, but never let it block the plan above.

## The contract always wins

`docs/CONTRACT.md` and the files in `data/starter/` are the source of truth for field
names, enums and formats. If a plan disagrees, follow the contract and fix the plan.
Never rename a schema field.

## Golden rules (never break these)

1. **No hand-written law.** No rule text, citation, threshold, date or jurisdiction fact
   is typed into code, config or the frontend. Everything comes from `outputs/rules.json`,
   produced by the pipeline from corpus text. Missing source text is never filled in by
   hand; it goes through the supplement path in CONTRACT.md 6 or stays a documented gap.
2. **Fail closed.** If a fact is missing, a check fails, or the model is unsure, the
   result is `unknown` (with the missing fact named) or the record is rejected. Never
   default to "does not apply" when coverage is uncertain.
3. **Every stored rule has a verified quote.** `quoted_span` (min 20 chars) must be found
   in the source document text. If not found: reject and log to `outputs/rejects.jsonl`.
   `source_doc_id` and `source_url` are always filled from the manifest.
4. **Deterministic around the AI.** The LLM is used only in `navigator/extract/` and
   `navigator/explain/` at build time. Dates, jurisdiction resolution, coverage,
   precedence, explanations in lookups.json and change tracking are plain Python with
   unit tests.
5. **No LLM in the user's click path.** The API serves precomputed JSON. Exceptions:
   `POST /ingest` and `make rerun-live` (live demo of extraction), which can run with the
   cache disabled.
6. **One contract.** Pydantic models in `navigator/schema/` match the schema exactly.
   Internal-only fields (offsets, retrieval date, date basis, reasoning boundary) live in
   an internal model and are stripped when writing submission files.
7. **Numbers in plain-language text must come from the quote.** Any number, percentage,
   dollar amount or date in a summary must appear in its `quoted_span`, or the summary is
   discarded and the UI shows the quote.
8. **Never compute values the corpus does not contain** (e.g. a 2026 CPI figure or a
   screening-fee dollar amount). Show the formula from the law.
9. **Enacted, not yet effective, pending and failed are never mixed.** Pending bills are
   never in force. Failed measures (T5) are recorded with status `failed` if a citable
   span exists, never appear in lookups, and never produce a rent cap.
10. **Every answer shows an as-of date, the source citation and its retrieval date, and
    "Not legal advice."** API responses, CLI output and every UI screen. Never present
    output as legal advice or a compliance certification.
11. **Never write text that helps anyone avoid, structure around or evade a rule.**
    Owner-facing wording describes obligations only.
12. **No non-public data and no scraping against site terms.** Use the starter corpus.
    Census Geocoder and the guide's section 6 sources are allowed.
13. **Flag for human review:** conflicts (including two sources giving different
    effective dates) and low-confidence answers carry `conflict_flag` / `needs_review`
    with a reason.
14. **Metrics are generated, never hand-copied.** Numbers in README, METHOD.md or the demo
    come from `make eval` output files.
15. **State the reasoning boundary.** Every answer lists what was checked and what could
    not be checked (owner type, certificate of occupancy date, rent amount, ...).

## Commands

```
make setup        # install deps
make ingest       # manifest + text files -> outputs/docs.jsonl
make extract      # LLM extraction (cached) -> outputs/candidates.jsonl
make verify       # gates + date resolution -> outputs/rules.json, rules_internal.json, rejects.jsonl
make geocode      # addresses -> outputs/parcels.json
make lookups      # engine -> outputs/lookups.json (all 500) + timeline + snapshots
make changes      # T1..T5 -> outputs/changes.json
make all          # everything above, in order
make eval         # our evaluation harness -> scores/eval_latest.txt, scores/history.jsonl
make test         # pytest
make smoke        # fail-closed smoke tests (no network, no LLM)
make api          # FastAPI on :8000
make ingest-doc DOC=path   # incremental run for new document(s)
make rerun-live DOC=path   # same with LLM cache disabled and visible progress (demo)
```

## Workflow rules for Claude Code

- Before changing extraction, prompts, verify gates or the engine: run `make eval` and note
  the numbers. After the change: run it again. If a metric dropped, revert or fix before
  moving on. Report before/after numbers in your summary.
- Work in vertical slices. Get 3 documents fully through extract > verify > lookup > eval
  before scaling to all 54 text documents.
- LLM calls: temperature 0, cached on disk by (doc sha256, chunk id, prompt version,
  model). Never delete the cache to "retry"; bump the prompt version instead.
- Every LLM call, verify decision and change-tracking run is appended to
  `outputs/audit.jsonl`.
- Do not add vector stores, RAG, Obsidian, agent frameworks, LangChain or retrieval at
  question time. JSON files + Python + FastAPI is the whole stack.
- Do not refactor working code after hour 20. Fixes only.
- Do not invent test expectations. Change-test expectations come from
  `dev/change_tests.json`. The human-verified gold set (`eval/`) is written by the team
  from the corpus, is used only for evaluation, and is never read by the pipeline.
- If something in the data is ambiguous, write it to `NOTES.md` under "Open questions"
  and pick the fail-closed option.

## Definition of done for any task

- `make test` and `make smoke` pass.
- `make eval` metrics are not lower than before.
- No new hardcoded law facts:
  `grep -rnE "§|Civ\. Code|G\.L\.|N\.J\.S\.A|Admin\. Code|P\.L\." navigator web config`
  must only hit test fixtures and `eval/`.
- Output files validate against the schema and the formats in CONTRACT.md 2 to 4.
