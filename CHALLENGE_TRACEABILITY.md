# CHALLENGE TRACEABILITY

This file maps each requirement in the official participant guide (`data/starter/README.md`,
pack v5) to where it is met, with a status and a way to check it.

Status: **done**, **partial** (some of it works; the gap is named), **gap** (not done).

Measured results are not typed here. For rule counts, accuracy, lookup rows and change-test
pass/fail, see the generated block in [README.md](README.md) or [METHOD.md](METHOD.md),
`scores/eval_latest.txt`, `scores/changes_report.txt`, or `GET /eval`.

Common commands (from the repo root):
- `python -m navigator all` runs the pipeline. LLM and geocoder caches are committed, so it
  runs offline.
- `python -m navigator eval` runs the self-evaluation and writes `scores/eval_latest.txt`.
- `python -m pytest -q` runs the tests; `-m smoke` runs the fail-closed checks only (no
  network, no LLM).
- `python -m navigator api` starts the API; OpenAPI docs are at `http://127.0.0.1:8000/docs`.
- `cd web && npm run dev` starts the UI.

## Section 1: the task

| Requirement | Status | Where | How to verify |
|---|---|---|---|
| Answer which housing rules apply at each sample address on the query date | done | `navigator/engine/lookup.py`; `outputs/lookups.json`; `GET /lookup` | `GET /lookup?address_id=A0001` |
| Default query date 2026-10-01 | done | `config/settings.yaml` (`default_as_of`) | `outputs/lookups.json` field `as_of` |
| Other query dates ("some tests ask for other dates") | done | `navigator/engine/status.py`, `dates.status_on()`; precomputed key dates in `outputs/timeline.json` and `snapshots.json` | `GET /lookup?address_id=A0001&as_of=2027-07-02`; date slider in the UI (`web/src/timeline/DateSlider.tsx`) |
| Module A: corpus to structured rule records | done | `navigator/extract/`, `navigator/verify/gates.py` | `outputs/rules.json`; eval item [1] |
| Module B: resolve state and city, test coverage | done | `navigator/geo/`, `navigator/engine/coverage.py` | `outputs/parcels.json`; `tests/test_geo.py`, `tests/test_engine.py` |
| Module C: which addresses each change case affects | done (with text gaps, see section 7) | `navigator/changes/` | `outputs/changes.json`; `GET /changes` |
| Every answer cites the source text | done | `quoted_span`, `citation`, `source_url`, `retrieved_at` on every row (`_row_out()` in `navigator/api/service.py`); source drawer `web/src/source/SourceDrawer.tsx` | `GET /rule/{team_rule_id}` returns the text window and highlight offsets; eval item [2] |

## Section 2: minimum viable submission

| Requirement | Status | Where | How to verify |
|---|---|---|---|
| Modules A and B on the sample addresses: accurate extraction, jurisdiction resolution, citations | done for format and grounding; accuracy not measured | as in section 1 | eval items [1], [2], [3] pass/fail. Extraction and lookup accuracy against a human gold set is **not measured**: no gold set exists yet (eval item [4], "not measured yet") |
| Module C | done (text gaps in section 7) | `navigator/changes/tracker.py` | `scores/changes_report.txt` |
| Plain-language view | done | `navigator/explain/plain.py` (build time, guarded); rights label `web/src/label/RightsLabel.tsx` | UI; `outputs/summaries.json`; `answer` field in `GET /lookup` |
| Stretch: Spanish view | partial | Spanish answers are generated and guarded (`answer_tenant_es` / `answer_owner_es` in `outputs/summaries.json`), and the API serves them with `GET /lookup?...&lang=es`. **The UI has no language toggle**: `web/src/api/client.ts` always requests `lang=en` | `GET /lookup?address_id=A0001&lang=es` |
| Stretch: confidence indicators | done | `navigator/engine/confidence.py` (0-1 score with named reasons); UI low-confidence marker with the reasons as a tooltip (`web/src/label/LabelRow.tsx`) | `confidence`, `confidence_reasons` in `GET /lookup` |
| Stretch: a new jurisdiction | partial | Path exists: `data/supplement/`, `python -m navigator ingest-doc`, `config/jurisdictions.yaml`. **No new jurisdiction has been added** (`data/supplement/` is empty). A city that appears only in the supplement would get no addresses until `manifest_jurisdictions()` and related readers include supplement rows (NOTES.md open question 13) | `tests/test_incremental.py` |
| Stretch (team): audit view | done | `GET /audit?team_rule_id=`; `web/src/source/AuditTrail.tsx` | open a rule's source drawer in the UI |

## Section 3: rules of the event

| Requirement | Status | Where | How to verify |
|---|---|---|---|
| Extraction is automated, not hand-coded | done | `navigator/extract/extract.py` (LLM, structured output), `navigator/verify/gates.py`. No rule text, citation, threshold or date is typed in code, config or UI | CLAUDE.md grep: `grep -rnE "§\|Civ\. Code\|G\.L\.\|N\.J\.S\.A\|Admin\. Code\|P\.L\." navigator web config` (expected hits: test fixtures only); `cd web && npm run check:no-law` |
| Show the extraction pipeline in the demo | done (not yet shown on a deployed site) | `python -m navigator rerun-live <file> --jurisdiction "City, ST"` (LLM cache off for that document, visible progress); `POST /ingest` streams NDJSON progress; UI panel `web/src/ingest/IngestPanel.tsx` | `tests/test_api.py::test_ingest_streams_progress_and_summary`; rehearse before the demo |
| Use the starter pack; no bulk scraping | done | inputs read from `data/starter/` (checksummed, read-only); only network call is the Census Geocoder (`navigator/geo/census.py`); no crawler in the repo | `tests/test_starter_pack.py`; SAFETY.md section 11 |
| No non-public data (customer, resident, pricing) | done | only the pack's public assessor sample and Census responses | DATA_CARD.md |
| "Unknown" is a valid answer; never guess | done | three-valued coverage (`navigator/engine/coverage.py`); `missing_facts` names the fact. One stated exception: `PRESUME_UNCHECKABLE_EXEMPTIONS_ABSENT` (SAFETY.md section 3) | `tests/test_engine.py::test_unknown_names_missing_fact` |
| "Not legal advice" on every interface | done | API envelope, CLI, UI footer and screens (SAFETY.md section 1) | any API response's `disclaimer`; UI footer |
| Logistics (team size, credits, submission method, licensing, contact) | TBD by organizers | none | none |

## Section 4.1: sample address facts (handled explicitly, as the guide asks)

| Requirement | Status | Where | How to verify |
|---|---|---|---|
| Postal city is not the legal city; resolve the jurisdiction | done | Census incorporated place containing the geocoded point; NJ and MA also check the county subdivision (`navigator/geo/geocode.py`, `navigator/geo/jurisdictions.py`, `config/jurisdictions.yaml`) | `tests/test_geo.py::test_legal_city_not_postal_city`; `parcels.json` fields `city`, `postal_city`, `jurisdiction_confidence` |
| Missing year built and unit counts | done | missing gives `unknown` with the fact named; unit ranges parsed from `use_description` with reviewed patterns only (`config/unit_parsers.yaml`, `navigator/geo/units.py`) | `tests/test_geo.py::test_parse_use_description`; user can enter facts (`POST /lookup`, `web/src/label/FactInput.tsx`) |
| Santa Ana: rules extracted, no addresses | done | Santa Ana rules are in `rules.json`; Santa Ana has no `config/jurisdictions.yaml` entry | coverage matrix in `scores/eval_latest.txt` |
| No owner names: owner-type tests unknown or explained | done | owner facts are "not in the data" (`navigator/engine/boundary.py`); see SAFETY.md section 3 for the exemption presumption | `not_checked` in `GET /lookup` |
| Year built is not certificate of occupancy; cutoff year gives unknown | done | `coverage.py` (cutoff from the rule's own predicate) | `tests/test_engine.py::test_certificate_of_occupancy_from_year_built` |

## Section 5: submission format

| Requirement | Status | Where | How to verify |
|---|---|---|---|
| `rules.json`: records matching `schema/rule_record.schema.json` | done | `navigator/schema/models.py`, `write_rules()` in `navigator/schema/writers.py` (refuses invalid records) | eval item [1]; `tests/test_output_format.py` |
| `lookups.json`: `{"as_of", "lookups"}` for all 500 addresses | done | `write_lookups()` refuses missing or unknown address ids | eval item [1] |
| `changes.json`: per test `affected_address_ids`, `conflict_flag_address_ids`, `notes` | done | `navigator/changes/tracker.py`, `write_changes()` | eval item [1]; `outputs/changes.json` |
| Each answer tied to a source document and retrieval date | done | `source_doc_id` and `source_url` from the manifest; `retrieved_at` in the internal model, API and UI (the official schema has no retrieval-date field) | eval item [2] |
| Reproducible for the live demo | done | committed caches `cache/llm/`, `cache/geocode/`; a cached run makes no API or network calls | `python -m navigator all` offline. Byte-identical determinism check: eval item [8] "not measured yet"; `tests/test_geo.py::test_output_is_deterministic_and_matches_committed` covers geocoding |
| `result` values `applies`, `unknown`, `superseded`, `not_yet_effective`, `pending` | done | `navigator/engine/lookup.py` | `tests/test_engine.py::test_status_selection_and_omission` |
| `superseded`: a stricter rule at another level governs | partial | `navigator/engine/precedence.py`: only where extracted text says the state rule defers to local rules. "Stricter" is not compared numerically; such rows list "whether the local limit is stricter" under `not_checked` | `tests/test_engine.py::test_superseded_when_state_text_defers_to_local` |
| Leave out rules that don't apply | done | coverage FALSE and `failed` rows are omitted (`_base_row()`) | eval: "no failed rule appears in lookups" |

## Section 7: change-tracking tests

Expected behavior comes only from `data/starter/dev/change_tests.json`. The matcher maps the
organizers' rule ids to ours in `config/test_rule_map.yaml`. That file is still
`reviewed: false` (gap: one human check is needed).

| Test | Status | Where | How to verify |
|---|---|---|---|
| T1: California AB 325 / SB 763, before vs after its effective date | done for AB 325 (D022); SB 763 has no text in the corpus | as_of tracker; the date comes from D022's own chaptering line plus the California default rule, flagged `needs_review` because the default is not stated in the text (`navigator/extract/dates.py`) | `scores/changes_report.txt` T1 checks; `GET /changes/T1` |
| T2: Hoboken vs Jersey City algorithmic bans, boundary | partial | **No ordinance text in the corpus** (Hoboken pages are `check-terms`; Jersey City pages are link-only). Nothing is invented: the rules are absent from `rules.json` and `lookups.json`. `changes.json` lists the addresses whose legal city is Hoboken or Jersey City as a boundary-only answer, with a "no source text" note | T2 checks marked N/A in `scores/changes_report.txt`; "no affected address outside the named cities" passes |
| T3: NJ FAIR Act, not yet effective now, applies later; flag conflict with JC/Hoboken | done for dates; partial for the conflict | date resolved from D069's relative phrase and approval anchor (`first_day_of_nth_month_after` in `dates.py`). Jersey City and Hoboken addresses are conflict-flagged for human review, but there is no city rule text to conflict with | `GET /changes/T3`; `tests/test_dates.py::test_first_day_of_twelfth_month_after_enactment` |
| T4: MA S.2983 and H.5222, pending; affected if passed | done | pending tracker: `pending` in lookups, affected = addresses the bills would cover if enacted | `GET /changes/T4` |
| T5: MA rent-control ballot question struck; affected empty; no rent cap in Boston/Cambridge | partial | affected set is empty, and no city or unenacted rent cap is reported (checked). **The ballot question (IP 25-21) is not recorded as `failed`**: the corpus has no citable text for it (D059 is link-only) | T5 checks in `scores/changes_report.txt` |
| Any as-of date | done | engine runs on any date | `GET /lookup?...&as_of=YYYY-MM-DD` |

## Section 8: responsible design

Details and file paths are in [SAFETY.md](SAFETY.md).

| Requirement | Status | Where | How to verify |
|---|---|---|---|
| Cite source text and retrieval date for every rule | done | rule rows and source drawer | eval item [2] ("rules behind 'applies' rows have span, citation, url, retrieval date") |
| Show an "as of" date on every answer | done | API envelope `as_of`; UI footer, label, drawer, changes page | any API response |
| Separate enacted law from pending law | done | `status_on()`, `check_lookups()` | `tests/test_output_format.py::test_write_lookups_refuses_status_mixing` |
| Say "unknown" instead of guessing | done (one stated presumption) | SAFETY.md section 3 | `tests/test_engine.py` |
| Flag conflicts for human review | done | `conflict_flag`, `conflict_note`, `needs_review`, `review_reasons` | `tests/test_engine.py::test_unresolved_interaction_flags_conflict_on_both_rows` |
| Keep an audit log | done (committed copy is stale) | `outputs/audit.jsonl`, `GET /audit` | `tests/test_api.py::test_audit_filters_stale_ids`. The committed log lacks the geocode and summaries runs |
| Don't present output as legal advice or compliance certification | done | disclaimer everywhere; footer says "not a compliance certification" | UI footer |
| Don't suggest ways to avoid a rule | done | evasion guard; owner text may not mention exemptions (`navigator/explain/guards.py`) | `tests/test_explain.py` |
| Don't invent rules or citations | done | quote verification; manifest-only source fields; no hand-written law | eval item [2]; CLAUDE.md grep |
| Don't use non-public data | done | see section 3 | DATA_CARD.md |

## Section 9: known open questions in the law

| Open question | Status | Where | How to verify |
|---|---|---|---|
| Berkeley ch. 13.63: two published effective dates | gap | D001 (ordinance) states no effective date; the second source (D002, law-firm alert) is link-only, so the two-date conflict can't be shown from supplied text. D001 also records only a first reading, so the rule is extracted as `pending`, which is what its text supports (NOTES.md open questions 1 and 6). The detector exists: two verified sources with different dates set `conflict_flag` (`build_rule()` in `navigator/verify/gates.py`). The Berkeley records carry no review flag that names the missing second date | Berkeley `algorithmic_rent_setting` rules in `outputs/rules.json` (`status`, `effective_date`); METHOD.md "Known gaps" |
| NJ FAIR Act may preempt Jersey City and Hoboken ordinances | partial | surfaced through T3: JC and Hoboken addresses are conflict-flagged for human review (`changes.json`). The FAIR Act's own rule record carries no extracted interaction text, and the city ordinances have no text, so the rights label does not show the preemption | `GET /changes/T3` |
| LA RSO formula: two published effective dates | gap | only the LAHD date is in the corpus (D041, D042); the landlord-association source is not supplied. No conflict is invented (NOTES.md open question 2) | none possible from supplied text |
| California screening-fee cap: no single official 2026 dollar figure | partial | No value is computed: the statute's formula is shown as written (D026). A separate state-level rule taken from a Berkeley Rent Board page (D005) shows a 2026 dollar figure that is published on that page. The two are not linked or conflict-flagged, so the label does not say that no single official figure exists | `outputs/rules.json`, CA `application_screening_fees` rules |

## Submission deliverables (guide section 5, BACKEND_PLAN.md section 8)

| Deliverable | Status | Where |
|---|---|---|
| `rules.json`, `lookups.json`, `changes.json` | done | `outputs/` |
| Live demo | gap (deployment pending) | API: `python -m navigator api` (set `NAVIGATOR_DISABLE_INGEST=1`, `NAVIGATOR_CORS_ORIGINS`); web: `web/vercel.json`, `npm run build` with `VITE_API_BASE`. Without an API, the UI falls back to bundled data and says "Offline data" |
| One-page `METHOD.md` | done | `METHOD.md` |
| GitHub repo with README | done | `README.md` (run commands, generated metrics block, architecture) |
| SAFETY.md, CHALLENGE_TRACEABILITY.md, DATA_CARD.md | done | repo root |
| Human-verified gold set (`eval/gold_rules.json`, `eval/gold_addresses.json`) | gap | not in the repo. Eval item [4] reports "not measured yet". Once written, it must be reviewed by a person before its numbers are quoted |

Not legal advice.
