# SAFETY: responsible design

This file describes what the Rental Housing Law Navigator does to avoid wrong or harmful
answers, and where it can still go wrong. Every claim names the file that implements it, so
you can check it. It follows the participant guide's section 8 ("Responsible design").

Measured numbers (rule counts, accuracy, lookup rows, change-test results) are not repeated
here. See the generated block in [README.md](README.md) or [METHOD.md](METHOD.md),
`scores/eval_latest.txt`, or `GET /eval`.

## 1. Not legal advice

The disclaimer string comes from one place, `config/settings.yaml` (`disclaimer`), and is
attached to every output:

| Where | How | Check |
|---|---|---|
| Every API response, including errors and the `POST /ingest` progress stream | `_envelope()` and `_error()` in `navigator/api/main.py`; `build_lookup()` and `rule_detail()` in `navigator/api/service.py` | `tests/test_api.py` (smoke); any response from `python -m navigator api` |
| CLI | parser description and the final `done.` line in `navigator/cli.py` | `python -m navigator --help` |
| `changes.json` notes, `scores/changes_report.txt`, `outputs/summaries.json`, `scores/eval_latest.txt` | `navigator/changes/tracker.py`, `navigator/explain/plain.py`, `eval/run_eval.py` | open the files |
| Web UI: footer, rights label, source drawer, changes page, states page, ingest panel | `web/src/layout/Footer.tsx` (also "not a compliance certification"), `web/src/label/RightsLabel.tsx`, `web/src/source/SourceDrawer.tsx`, `web/src/changes/ChangesPage.tsx`, `web/src/label/StatesPage.tsx`, `web/src/ingest/IngestPanel.tsx` | run the UI |

Every API answer also carries `as_of` and `generated_at`. Each rule row carries
`citation`, `source_url` and `retrieved_at` (`_row_out()` in `navigator/api/service.py`).

The submission files `rules.json` and `lookups.json` have no disclaimer field. The official
schema and templates define their shape, so we don't add one.

## 2. Enacted, not yet effective, pending and failed are kept separate

- A rule's status on any date is computed from its extracted status hint
  (`enacted` / `bill_or_proposal` / `failed`) and its resolved effective date.
  `dates.status_on()` in `navigator/extract/dates.py`, wrapped by `navigator/engine/status.py`.
  A pending bill never becomes `in_force` by date arithmetic.
- In the engine (`_base_row()` in `navigator/engine/lookup.py`), `failed` rules are left out
  of lookups. `pending` and `not_yet_effective` rules are reported as those results and are
  never `applies`.
- `navigator/schema/writers.py` (`check_lookups()`) refuses to write `lookups.json` if a
  failed rule appears or a pending rule is reported as anything other than `pending`.
  Tests: `test_write_lookups_refuses_status_mixing` in `tests/test_output_format.py` (smoke).
  `eval/run_eval.py` checks this again ("no failed rule appears in lookups").
- Plain-language answers for pending, not-yet-effective and failed rules must use status
  wording and must not read as current law (`form_guard()` in `navigator/explain/guards.py`).
  Failed rules get no plain-language answer at all (`navigator/explain/plain.py`).
- Two sources that disagree on whether a law is enacted, pending or failed set `needs_review`
  (`build_rule()` in `navigator/verify/gates.py`).

## 3. Fail closed: `unknown` names the missing fact

- Coverage uses three-valued logic: true, false or unknown (`navigator/engine/coverage.py`).
  A missing unit count, year built or land-use description gives `unknown`, and the
  `missing_facts` list on the row names the fact. Each row's `checked` / `not_checked` lists
  (`navigator/engine/boundary.py`) state the reasoning boundary. Owner type, owner occupancy,
  rent amount and certificate-of-occupancy date are listed as "not in the data".
- Year built is not treated as the certificate-of-occupancy date. A building built in the
  cutoff year is `unknown`. Earlier years are `true` with lower confidence and the reason
  "certificate-of-occupancy date estimated from year built" (`coverage.py`,
  `test_certificate_of_occupancy_from_year_built`).
- If the legal city is not confirmed, city rules are `unknown`, and state rules that defer
  to them become `unknown` ("may be superseded") rather than `applies`.
  `test_low_jurisdiction_confidence_makes_city_rules_unknown` in `tests/test_engine.py`.
- Malformed predicates never decide anything (`test_malformed_predicate_never_decides`).
- Unit counts parsed from `use_description` only use reviewed patterns
  (`config/unit_parsers.yaml`). Ambiguous NJ MOD-IV codes give no range.
- Missing or stub outputs, or a lookup row whose rule is missing, make the API return
  HTTP 503, never an empty "no rule applies" (`navigator/api/store.py`, `build_lookup()`;
  `test_missing_files_fail_closed`, `test_stub_outputs_fail_closed`,
  `test_out_of_sync_rule_fails_closed`). `navigator/engine/lookup.py` refuses to write
  lookups without `parcels.json`.

**Deliberate exception (stated plainly).** `PRESUME_UNCHECKABLE_EXEMPTIONS_ABSENT = True`
in `navigator/engine/coverage.py`. Some exemptions depend only on facts the data never has
(owner occupancy, subsidy, dormitory use, owner type). When one of those is the only thing
leaving coverage undecided, the engine presumes the exemption is absent. The result can then
be `applies`, with the exemption listed under `not_checked`, a "Not checked: ..." clause in
the explanation, and lower confidence. A positive condition on such a fact (for example
"owner is a natural person") is never presumed. The presumption can only turn `unknown` into
`applies`, never into "does not apply", so it never hides a rule. Set the switch to `False`
for strict mode. See NOTES.md, "Uncheckable exemptions".

A rule with no extracted coverage predicates covers its whole jurisdiction. It says so in the
explanation and in `not_checked` ("coverage conditions beyond the jurisdiction (none
extracted as checkable facts)"). This errs toward showing a rule, not hiding it.

## 4. Quote verification

- Every rule's `quoted_span` must be found in its source document, or the candidate is
  rejected and written to `outputs/rejects.jsonl` and `outputs/audit.jsonl`
  (`check_candidate()` in `navigator/verify/gates.py`, `find_span()` in
  `navigator/verify/spans.py`).
- Matching has three levels: exact; whitespace-normalized; and tolerant (curly quotes,
  dashes, soft hyphens, line-break hyphenation, spacing after a section sign). There is no
  fuzzy matching: a changed word means rejection (`test_changed_word_is_rejected` in
  `tests/test_verify.py`). The level used is stored as `span_match`, and a tolerant match
  lowers confidence. The stored `quoted_span` is cut from the document text, not taken from
  the model.
- The span must be at least 20 characters (the schema minimum). The file header
  (`SOURCE:` / `RETRIEVED:`) is never searched.
- `source_doc_id`, `source_url` and `retrieved_at` are copied from the manifest, never from
  the model (`navigator/extract/extract.py`). `write_rules()` in
  `navigator/schema/writers.py` refuses to write a rule whose `source_url` differs from the
  manifest.
- Numbers in a rule's `requirement` and `key_value` must appear near the quote. Numbers in
  coverage, exemptions and penalty must appear somewhere in the document. A failure sets
  `needs_review` (`numbers_supported()` in `spans.py`).
- `eval/run_eval.py` re-checks every quote against the raw corpus text, independently of
  the pipeline code.
- The UI highlights the exact span in the source text (`GET /rule/{id}` returns code-point
  and UTF-16 offsets; `web/src/source/HighlightedText.tsx`).

## 5. No LLM at answer time

- The LLM is called only in `navigator/extract/` (rule extraction) and
  `navigator/explain/plain.py` (plain-language summaries), at build time.
- The API (`navigator/api/main.py`, `service.py`, `store.py`) serves precomputed JSON. The
  only computation per request is the deterministic engine, used for an `as_of` date other
  than the precomputed one and for `POST /lookup` with user-entered facts.
- The one exception is `POST /ingest` (and the CLI `ingest-doc` / `rerun-live`). It adds a
  document and runs extraction for it. See section 10.
- Lookup explanations in `lookups.json` are templates filled by plain Python
  (`navigator/engine/explain_lookup.py`), not LLM text.

## 6. Number and evasion guards on summaries

Plain-language answers (`outputs/summaries.json`) are written at build time and checked by
deterministic guards in `navigator/explain/guards.py`. Any failure drops the answer (null),
and the UI shows the quote instead ("No plain-language summary passed our checks. The law
says: ...", `web/src/label/RowDetail.tsx`).

- **Number guard:** every number, percentage, dollar amount and month name in the answer
  must appear in the rule's `quoted_span`, including spelled-out numbers in English and
  Spanish. A percentage or dollar amount must appear with the same kind of unit.
- **Evasion guard:** wording such as "avoid", "get around", "loophole", "circumvent",
  "exempt yourself" or "qualify for an exemption" (and Spanish equivalents) drops the
  answer. Evasion failures are never sent back for repair; they are only dropped
  (`NOT_REPAIRABLE` in `plain.py`).
- **Form guard:** one sentence, at most 20 words, addressed to "you", with status wording
  for non-current rules.
- The API checks numbers a second time against the quote (`numbers_grounded()` in
  `navigator/api/service.py`). It also ignores a summary written for a different quote
  (`source_quote_sha`).
- Lookup explanations have their own number check and evasion pattern. If a check fails,
  the explanation falls back to "citation (jurisdiction): result"
  (`navigator/engine/explain_lookup.py`).
- Tests: `tests/test_explain.py` (smoke), `test_summaries_used_and_number_guarded` in
  `tests/test_api.py`.

Known weakness: the guards check form and numbers, not meaning. A summary can paraphrase a
quote loosely and still pass. Known false positives also exist (Spanish "evitar" in the sense
of "prevent"). The UI always shows the quote next to the summary. NOTES.md recommends one
human review pass of the summaries; it has not been done.

## 7. Owner wording describes obligations only

- Owner answers must use obligation wording ("must", "may not", "limited", ...) and may not
  mention exemptions or exceptions at all (`evasion_guard()` and `form_guard()` with
  `role="owner"` in `guards.py`; `test_owner_text_may_not_mention_exemptions`,
  `test_owner_text_must_state_an_obligation`).
- The summary model never sees the `exemptions` field (`INPUT_FIELDS` in
  `navigator/explain/plain.py`), so it can't turn an exemption into advice.
- The owner-view category questions are fixed UI wording ("What rules apply when ending a
  tenancy?"), not law (`QUESTIONS` in `navigator/api/service.py`).
- The source text, including any exemptions it lists, is shown as written in the source
  drawer. We don't rewrite exemptions into guidance.

## 8. Conflict and review flags

- **Rule level** (`navigator/verify/gates.py`). Two verified sources giving different
  effective dates for the same law set `conflict_flag` and a `conflict_note` naming both
  dates and documents. Sources disagreeing on enacted, pending or failed set `needs_review`.
  Each non-rejecting check failure (number not near the quote, effective date not stated,
  a date taken from a statutory default rather than the text, dropped predicates, ...) adds
  a `review_reasons` entry and lowers `confidence`.
- **Row level** (`navigator/engine/precedence.py`, `lookup.py`). Precedence comes only from
  extracted text. An interaction that the text states but the engine can't resolve flags
  both rows (`conflict_flag`) and does not pick a winner
  (`test_unresolved_interaction_flags_conflict_on_both_rows`).
- **Change tests** (`navigator/changes/tracker.py`). T3 flags the Jersey City and Hoboken
  addresses for human review as a possible preemption conflict, even though the city
  ordinances have no text in the corpus. We can't rule the conflict out, so we flag it.
- **Addresses** (`navigator/geo/geocode.py`). These set `needs_review` on the parcel and
  lower jurisdiction confidence: no geocoder match, matches in different jurisdictions, a
  Census state different from the address state, or a county subdivision that disagrees
  with the incorporated place (NJ, MA). A non-exact match also lowers confidence below
  "high". City rules are decided only at "high" confidence (`Facts.city_confirmed` in
  `navigator/engine/facts.py`).
- **UI.** Conflict chips, "Two laws may disagree; this needs human review", the review
  reasons in the source drawer, and low-confidence markers
  (`web/src/label/LabelRow.tsx`, `RowDetail.tsx`, `web/src/source/SourceDrawer.tsx`).
- The change-test id mapping `config/test_rule_map.yaml` is written with `reviewed: false`.
  The API exposes this as `mapping_reviewed`.

## 9. Audit log

- `outputs/audit.jsonl` is append-only, with one JSON line per decision
  (`navigator/audit.py`). Lines are written by ingest (text found or not), extraction
  (each LLM call or cache hit, with cache key, model, served model and request id),
  verify (every accept and reject with its reason), geocode, summaries (kept or dropped,
  with guard reasons), change tests (with the result of each check), and incremental ingest.
- `GET /audit?team_rule_id=` returns the trail for one rule. The web UI shows it in the
  source drawer (`web/src/source/AuditTrail.tsx`).
- Gap: the committed `outputs/audit.jsonl` was last committed at the change-tracking phase.
  It does not yet contain the geocode and summaries runs. Commit the current log before
  submission.

## 10. Ingest disable switch for public deploys

`POST /ingest` is the only request path that can call the LLM, and it rewrites every output.
- Setting `NAVIGATOR_DISABLE_INGEST=1` makes it return HTTP 403 (`navigator/api/main.py`;
  `test_ingest_one_at_a_time_and_can_be_disabled`).
- When enabled, the header (`SOURCE:` / `RETRIEVED:` / blank line) is validated before
  anything is written (400 on failure). Only one run is allowed at a time (409).
- The jurisdiction comes from the request or a matching manifest row, never inferred
  (`navigator/ingest/incremental.py`).
- The system can't verify that an uploaded page is really official or that its site terms
  allow capture. Whoever runs the ingest asserts that. Keep ingest disabled on any public
  deployment, and use it only for a supervised live demo.
- CORS allows localhost by default. Deployed origins must be listed in
  `NAVIGATOR_CORS_ORIGINS`.

## 11. No non-public data and no scraping

- Inputs are the starter pack in `data/starter/` (kept read-only:
  `data/STARTER_CHECKSUMS.sha256`, `test_starter_pack_unchanged`) and, optionally, single
  official pages added through `data/supplement/`. That folder is empty at the time of
  writing.
- The only network service the pipeline calls is the public US Census Geocoder
  (`navigator/geo/census.py`, `https://geocoding.geo.census.gov/geocoder`). Responses are
  cached in `cache/geocode/`, so a rerun makes no network calls. No other module fetches
  URLs (`navigator/` has no other HTTP client).
- No crawler or scraper exists in the repo. Code-publisher pages (`check-terms` rows) and
  link-only sources are not fetched. They stay as documented gaps (see DATA_CARD.md).
- The address file has no owner names, residents or prices, and we add none. The only
  user-entered facts are year built and unit count (`POST /lookup`). They are used for that
  request only, are not stored, and are shown back as user input (`user_facts`).
- The LLM receives corpus text (extraction) and extracted rule fields (summaries) only, never
  address data.

## 12. Limitations and misuse risks

Limitations:
- **Fixed corpus.** Answers reflect the starter corpus as retrieved on the date in each
  document's header. Later changes in the law are not seen.
- **Text gaps.** The Jersey City and Hoboken algorithmic-pricing ordinances and the
  Massachusetts rent-control ballot question have no text in the corpus. They are absent
  from `rules.json` and `lookups.json`, and T2/T5 note this. Many city code pages are
  `check-terms` (no text). A missing rule means "not in our sources", not "no such law".
  The UI says "No rule found in our sources for this level."
- **Two-date conflicts the guide names** (Berkeley's algorithmic ban, LA's RSO formula)
  can't be shown, because the second date is only in a link-only source.
- **Address data** is often missing year built or unit count, so many results are
  `unknown`. Year built is only an estimate of the certificate-of-occupancy date. Legal
  city comes from the Census incorporated place; non-exact matches leave the city
  unconfirmed.
- **Extraction can miss rules or misread coverage.** Quote verification proves the quote
  exists, not that the model summarized it correctly or found every rule. The team gold set
  that would measure this is not built yet (`scores/eval_latest.txt`, item 4).
- **Precedence** is applied only where the text states it. Local-vs-state "stricter" limits
  are not compared numerically.
- **Map clicks** resolve only to a sample address within 30 m. There is no live geocoding
  at request time.

Misuse risks:
- **Reading the label as compliance certification or legal advice.** It is neither. An
  `applies` row means the rule's extracted coverage conditions are met by the data we have.
- **Reading absence as permission.** A category with no rule is a gap in our sources.
- **Using exemption text to plan around a rule.** Owner summaries never mention
  exemptions, but the source text is shown as written. We don't offer guidance on it.
- **Injecting a fake source** through `POST /ingest` on an open deployment. Keep it
  disabled (section 10).
- **Over-trusting confidence numbers.** They are heuristic penalties
  (`navigator/engine/confidence.py`), not probabilities.

Not legal advice.
