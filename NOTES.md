# NOTES.md: decisions and open questions

## Verified facts (phase 0, checked against `data/starter/`)

- Both supplied zips are byte-identical; the pack is unpacked once to `data/starter/`
  (65 files). `data/STARTER_CHECKSUMS.sha256` + `tests/test_starter_pack.py` keep it read-only.
- Manifest: 87 rows = 54 with text + 23 link-only + 9 check-terms + D056 (empty, 403).
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
