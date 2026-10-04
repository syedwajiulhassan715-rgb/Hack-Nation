# NOTES.md: decisions and open questions

## Verified facts (phase 0, checked against `data/starter/`)

- Both supplied zips are byte-identical; the pack is unpacked once to `data/starter/`
  (65 files). `data/STARTER_CHECKSUMS.sha256` + `tests/test_starter_pack.py` keep it read-only.
- Manifest: 87 rows = 54 with text + 23 link-only + 9 check-terms + D056 (no text: capture failed with HTTP 403).
- Every text file starts `SOURCE:` / `RETRIEVED:` / blank line.
- Addresses: CA 250, NJ 140, MA 110; missing year built 98/106/8; missing units 43/139/60.
  Only A0107 and A0432 (both Los Angeles) are built in 1978; none in 1979.
- CA code docs: D023 §1946.2, D024 §1947.12, D025 §1950.5, D026 §1950.6, D027 Gov §12955.
- "algorithm" appears only in D001, D022, D039, D045, D046, D047, D069, D076, D081:
  no Jersey City or Hoboken ban text anywhere in the corpus (T2 gap confirmed).
- No IP 25-21 text in the corpus; the only "ballot" hit is Berkeley Measure BB (D006).
- `docs/hack-nation-event-brief.pdf` (the event brief) differs from the pack's v5 brief: it
  names scoring weights, a T6 hour-16 Cambridge ordinance, a dev key, score.py and three
  videos. The pack wins (CLAUDE.md); we keep `ingest-doc` and the change runner data-driven
  so a T6 entry needs no code.

## Decisions

- **Manifest `sha256` does not match the text files (54 of 54).** Tested raw bytes, body
  without header, stripped, CRLF; none match. It most likely hashes the original HTML/PDF.
  Decision: keep it as `source_sha256` (informational), compute our own `text_sha256`
  for integrity and LLM cache keys. Never reject a document on this mismatch.
- **Document-level date anchors.** D069's "approved July 20, 2026" (line 19) is far from its
  effective-date sentence (line 213). Approval/chaptering anchors are searched across the
  whole document, not only within 1,000 chars of the span.
- **Retrieval date.** Manifest `retrieved_at` (`2026-10-01T22:44Z`) is canonical; the file
  header (`2026-10-01 22:44 UTC`) is a cross-check, mismatches logged to the audit log.
- **No `make` on the dev machine.** Every stage is `python -m navigator <stage>`; the
  Makefile and `run.ps1` are thin wrappers with the same target names.
- **Penalty** (phase 1). The brief asks extraction to capture penalties, but the schema has no
  field for it. Kept as internal `RuleInternal.penalty`, shown in UI/API, stripped from rules.json.
- **Stub outputs** (phase 1). `python -m navigator stubs` writes contract-valid empty files
  and an `outputs/STUB` marker; the eval report's first line then says STUB OUTPUTS. Empty
  lookups mean "not computed", never "no rule applies". Real stages remove the marker.
- **Ingest checks** (phase 2). All 54 header SOURCE urls equal the manifest url and all 54
  RETRIEVED times equal manifest `retrieved_at`; no CR line endings, no BOM. A future file
  with a missing header or a different url is ingested as unavailable (fail closed).
- **Character offsets are Python code points.** Only D084 has characters beyond U+FFFF
  (2 emoji), where JS UTF-16 offsets would drift. Phase 7: the API also returns UTF-16
  offsets (or the UI highlights by substring) so the highlight lands exactly.
- **Chunking** (phase 2). Docs up to 24k chars are one chunk; 54 docs -> 70 chunks. Cuts
  prefer a heading, then a blank line, then a numbered item, then a line break; weaker cuts
  overlap ~2k chars. Navigation junk is only dropped from prompts when a short digit-free
  line repeats 3+ times inside a block of 4+ short lines: a looser rule dropped SF rate-table
  headers and wrapped sentence fragments. Now drops 1,847 chars, all menus/forms.
- **LLM cache key** (phase 3) must include `chunker_version` and the chunk's char range as
  well as text_sha256, chunk_id, prompt_version and model, so a chunking change can never
  reuse a stale answer.
- **changes.json** always includes `conflict_flag_address_ids` (CONTRACT.md 4), even though
  the template omits it on T1.

- **Model per stage** (phase 3). Default LLM model is `claude-sonnet-5-5` (half Opus's
  per-token price); `llm.stages.<stage>` overrides it. Extraction stays on `claude-opus-5-5`
  because the full-corpus run is cached on it (model is in the cache key, so switching
  re-calls all 70 chunks). Trial (2026-10-04, prompt extract_v2, docs D001 D024 D045 D046
  D069 D081, both models through the real verify gates): Opus 7/7 candidates; Sonnet missed
  the CA rent cap (D024) entirely and left the NJ FAIR Act date unresolved (missed the
  "approved" anchor, which T3 depends on). Extraction stays on Opus.
- **Determinism** (phase 3). Effort `high`, structured JSON output
  (`output_config.format`). These models reject `temperature`, so the
  CLAUDE.md "temperature 0" cannot be sent; determinism comes from the disk cache in
  `cache/llm/` (commit it). A cached run never calls the API.
- **Predicates as a JSON string** (phase 3). Structured output gets `predicates_json` as a
  string because the predicate tree is recursive; verify parses it and checks it against the
  fact vocabulary in `navigator/schema/facts.py`. Bad predicates are dropped and the rule is
  marked `needs_review` (coverage then falls back to the text).
- **Allowed jurisdictions** are derived from the manifest (each document's jurisdiction and
  its state), never listed in code. A model-proposed county or unknown city is rejected.
- **Merge policy** (phase 3). Same document: merge only overlapping spans with the same
  (jurisdiction, category, citation key), i.e. chunk-overlap repeats. Across documents: merge
  only one-to-one matches on that key; ambiguous cases stay separate rather than collapse
  distinct obligations. Kept record: official source first, then exact span, then longest.
- **Number check** (phase 3). `requirement`/`key_value` numbers must appear within 1,500
  chars of the span; `coverage`/`exemptions`/`penalty` numbers anywhere in the document
  (statutes put exemptions in other subdivisions). Failures flag review, they don't reject.
- **Enacted with no stated date** is `in_force` with `needs_review` ("effective date not
  stated in source text"), per open question 1; status never comes from an invented date.
- **STUB marker** stays until `lookups` writes real results: rules.json alone being real does
  not make the empty lookups meaningful.

- **Legal city** (phase 4). The Census incorporated place containing the geocoded point
  (coordinates lookup, Public_AR_Current / Current_Current). In NJ and MA the county
  subdivision must agree, else the row is flagged. `postal_city` is used only as a
  low-confidence fallback when geocoding fails, and only if it is a corpus city.
- **Geocoder match acceptance** (phase 4). A match is kept only if its house number falls
  inside the input's house number or range; input ZIPs are unreliable (e.g. 11219 for Newark).
- **NJ MOD-IV unit tokens** (phase 4, resolves open question 4). A standalone `<n>U` token is
  a unit count; "/"-separated buildings are summed. Glued `<n>UG` forms, "1OU" and bare style
  codes give no range (fail closed) until a MOD-IV data dictionary defines them. Column vs
  description disagreement widens the range to cover both and flags review.
- **Uncheckable exemptions** (phase 5). Exemptions that depend only on facts the data never
  has (owner occupancy, subsidy, dormitory, owner type) are presumed absent when that is the
  only thing leaving coverage undecided; they are listed under not_checked and lower
  confidence. Switch: `PRESUME_UNCHECKABLE_EXEMPTIONS_ABSENT` in `navigator/engine/coverage.py`.
- **Precedence is text-driven only** (phase 5, `navigator/engine/precedence.py`). Unresolvable
  interactions set conflict_flag on both rows rather than choosing a winner.
- **Low jurisdiction confidence** (phase 5). City rules are `unknown`, and state rules that
  defer to them are `unknown` ("may be superseded") rather than `applies`.

- **Chaptering line as a date anchor** (phase 6). The prompt asks for an anchor only with a
  relative phrase, so AB 325 (D022) came out `in_force` with no date and T1 could not be shown.
  Verify now takes the document's own bill-history line (`10/06/25 - Chaptered`, verbatim,
  exactly one dated line) when the model gave no phrase and no anchor; `dates.resolve` still
  decides whether a statutory default applies (CA state only). r-0001/r-0002 -> 2026-01-01,
  `needs_review`. No re-extraction (deterministic, verify only).
- **Change-test matcher** (phase 6). `config/test_rule_map.yaml` is generated with
  `reviewed: false`; set `reviewed: true` after one human check and it is used as-is. City
  prefixes resolve against manifest cities (initials or name start, must be unique).
  MA-ALG-P1/P2 match {r-0038, r-0039} as a set: the pairing is not decidable from the ids.
- **Test ids with no source text but a resolvable city** (phase 6, T2/T3). Fail closed means
  "cannot rule out", not "does not apply": T2 affected = addresses whose legal city is Hoboken
  or Jersey City (boundary only, rules absent from rules.json/lookups.json); T3 conflict ids =
  those addresses covered by the FAIR Act on 2027-07-02, flagged for human review. Notes say
  so on every entry. Unresolved-city addresses are added only if their postal city names the city.
- **T5 and M.G.L. c.40P** (phase 6). r-0041 (category rent_increase_limits) applies to all MA
  addresses; its text bars local rent control and is not a cap. The T5 check fails on a city
  rent rule or an unenacted measure reported as applying; r-0041 is listed in the notes for review.
  IP 25-21 has no text, so it is not recorded as failed (needs a citable span).

- **API serves precomputed files** (phase 7). Only the deterministic engine runs per request
  (non-default `as_of`, POST /lookup with user facts). Missing or STUB outputs, or lookup rows
  whose rule is missing from rules_internal.json, give 503, never an empty answer.
- **Span offsets** (phase 7, resolves the "Character offsets" item). `/rule/{id}` returns both
  code-point and UTF-16 offsets for the span and the text window.
- **Summary answers in the API** (phase 7) are shown only if every number in them appears in
  the quote (second guard after the summaries stage); otherwise `answer` is null and the UI
  shows the quote.
- **Audit lookup by provenance** (phase 7). Rule ids are reassigned on each verify run, so
  `/audit` matches verify lines by the rule's provenance candidate ids, extract lines by chunk
  id, ingest lines by document id.
- **Category questions** ("How much can my rent go up?") are UI wording in
  `navigator/api/service.py`, not law; owner wording describes obligations only.
- **CORS**: localhost/127.0.0.1/[::1] on any port; deployed origins via `NAVIGATOR_CORS_ORIGINS`
  (comma-separated). Put this in the README.
- **Engine precedence cache** (phase 7). `_REL_CACHE` keyed on `id()` returned stale relations
  when ids were reused (flaky smoke test); the entry now holds the rule list alive.

- **Incremental path** (`ingest-doc` / `rerun-live` / `POST /ingest`). A supplement document is
  registered in `data/supplement/` (exact bytes; manifest row `official`, `manual`, sha256 of
  the stored text), then ingest, chunk, extract of that document only, verify, lookups and
  changes run; geocode is not repeated. Jurisdiction comes from `--jurisdiction` or a manifest
  row with the same URL, never inferred. Supplement docs are append-only per URL. The API
  streams NDJSON progress, validates the header before writing (400), runs one at a time
  (409), and is switched off with `NAVIGATOR_DISABLE_INGEST=1` (403) on public deployments.
- **Stable rule ids across incremental runs.** Verify numbers by sort order, so the incremental
  path maps ids back by candidate set: unaffected rules keep id and bytes; new rules get ids
  after the old maximum. A full `verify` from scratch still renumbers by sort order (the
  reviewed `config/test_rule_map.yaml` and summaries.json are keyed by id; summaries also carry
  `source_quote_sha` and the API ignores a summary whose quote no longer matches).
- **Summaries** (phase 8). `claude-sonnet-5-5`, prompt `summary_v1` (English, repair and
  translation sections). Cache key: task, rule content sha, prompt version, prompt-file sha,
  model. The model sees jurisdiction, level, category, status, title, requirement, key_value,
  coverage_conditions and quoted_span; never exemptions (owner text must not describe them)
  or effective dates (dates may only come from the quote). Failed rules get no call.
- **Guard-driven repair** (phase 8). Up to 2 rewrite calls for fixable guard failures
  (length, form); evasion wording is never repaired, only dropped. Kept counts are generated:
  see the "Plain-language answers kept" row in the METHOD.md metrics block (`python -m navigator eval`).
- **Guards check form and numbers, not meaning.** Known false positives: Spanish "evitar"
  (prevent) and "exención" (rent waiver) are dropped; "one" counts as a number. A spot check
  found r-0034's tenant answer paraphrasing the quote loosely; summaries are UI text shown
  next to the quote, but deserve one human review pass.

## Open questions

1. **Berkeley ch. 13.63 effective date.** D001 contains no effective date; the second
   source (D002 law-firm alert) is link-only. Default: `effective_date: null`,
   `needs_review` with reason "effective date not stated in source text"; the guide's
   two-date conflict cannot be surfaced from the supplied text. Say so in METHOD.md.
2. **LA RSO formula date.** Only "February 2, 2026" (D041, D042) is in the corpus; the
   landlord-association date is not. Same handling: no invented conflict.
3. **Organizer kickoff questions (CONTRACT.md 6):** will check-terms texts be released, may
   we add single official pages via `data/supplement/`? Until answered, T2 reports that the
   source text was not supplied, and T3 conflict flags have no city rule to conflict with.
4. **Ambiguous NJ MOD-IV unit tokens** such as `3SB2UG`, `3SF3UG`, `3SB1UG` (digits + `U`
   glued to a trailing `G`). Decide in phase 4; fail-closed default is "no range" unless the
   pattern is listed and reviewed in `config/unit_parsers.yaml`.
5. **CA AB 325 effective date** comes only from the CA default (Jan 1 after chaptering
   10/06/25), which is not stated in the corpus text. Lower confidence + `needs_review`.
   Phase 6: now resolved to 2026-01-01 from D022's chaptering line (see Decisions). SB 763
   (named in T1's title) has no text in the corpus.
6. **Berkeley ch. 13.63 status** (phase 3). D001 (Ordinance 7,992-N.S.) only records the first
   reading ("passed to print", November 18, 2025); the adoption vote and the guide's March 1,
   2026 date are not in the supplied text. Extraction marks it `pending` (bill_or_proposal),
   which is what the text supports. Decide: keep `pending` (text-faithful), or treat the
   numbered ordinance as enacted with `effective_date: null` + `needs_review`. Not overridden
   by hand either way (golden rule 1).
7. **MA H.5222 (D045) not extracted** (phase 3). Same page shape as S.2983 (D046, extracted):
   a bill page whose only substantive text is its title. The prompt does not say what to do
   with title-only bill pages, so the model was inconsistent. Fix needs prompt `extract_v2`,
   which re-extracts all 70 chunks (prompt version is in the cache key). Resolved: `extract_v2`
   adds a rule for title-only bill pages (one record, quote = verbatim title, nothing
   inferred); full re-extraction on Opus.
8. **"5B-64U/5B-64U-G" sums to 128** (phase 4). May be one 64-unit building listed twice;
   fail-closed alternative is the range 64-128.
9. **Boston neighborhood rows with no house number** (A0098, A0128, A0295, A0376, A0380).
   Could resolve to Boston from the postal neighborhood name, but that is a name-based rule;
   left as state-only (`city: null`, needs_review) for now.
10. **Conflict flags** (phase 5). 3,280 of 22,503 lookup rows are conflict-flagged on real
   parcels; the preemption patterns pair same-category rules broadly. Review after phase 6.
11. **T2/T3 boundary-only answers** (phase 6). If organizers want `affected_address_ids` to
   be empty when the rule text is missing, flip `track_boundary`/conflict handling; current
   choice lists the city's addresses with an explicit "no source text" note.
12. **Arbitrary map clicks** (phase 7). `/resolve` and POST /lookup only resolve sample
   addresses within 30 m (no network geocoding at request time). Decide whether the deployed
   API may call the Census geocoder there (allowed source, but adds a network call per click).
13. **Manifest-only checks after a supplement.** `precedence._doc_jurisdictions`,
   `geo.jurisdictions.manifest_jurisdictions`, `changes.matcher` and `eval/run_eval.py` read only
   the starter manifest, so a city that appears only in the supplement gets no addresses.
   Switch them to `ingest.corpus.manifest_rows()` if we add a new city live (stretch goal).
14. **`llm.call_json` prompt version.** It always uses `llm.prompt_version` (extract_v2), so
   summaries wraps the client itself. Cleaner: a `llm.stages.<stage>.prompt_version` override,
   keeping the current key layout so the cache still hits.
