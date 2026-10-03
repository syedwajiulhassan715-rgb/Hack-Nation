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
