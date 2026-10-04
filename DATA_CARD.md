# DATA CARD

This file describes the data the Rental Housing Law Navigator reads, what it derives from
it, and the known problems with that data. Input counts below were computed from the files
in `data/starter/`. Measured results (rule counts, lookup rows, accuracy, change-test
results) are not typed here. See the generated block in [README.md](README.md) or
[METHOD.md](METHOD.md), `scores/eval_latest.txt`, or `GET /eval`.

## 1. Source: the participant pack

- Hack-Nation Global Hackathon (RealPage challenge), participant pack v5 (no scoring script, no hour-16
  document). It is unpacked once to `data/starter/` and treated as read-only:
  `data/STARTER_CHECKSUMS.sha256` lists all 65 files, and
  `tests/test_starter_pack.py::test_starter_pack_unchanged` fails if any byte changes.
- `.gitattributes` marks `data/starter/**` as `-text`, so line endings are never
  converted. Span offsets refer to the exact stored bytes.
- The official guide is `data/starter/README.md`. The pack also contains the schema, the
  submission templates and `dev/change_tests.json` (T1 to T5).

## 2. The corpus

`data/starter/corpus/corpus_manifest.csv` has **87 rows**. Columns: `doc_id, jurisdictions,
url, source_type, capture, retrieved_at, sha256, text_file, status`.

| Group | Rows | `capture` | `source_type` | Text supplied |
|---|---|---|---|---|
| Text documents | 54 | `yes` | 53 `official`, 1 `official city-linked policy` | yes, `corpus/text/<doc_id>.txt` |
| Link-only | 23 | `link-only` | `secondary (law firm / news / mirror)` | no |
| Check-terms | 9 | `check-terms` | `code publisher` (D032-D034 Hoboken, D038 Los Angeles, D070-D072 Newark, D074-D075 San Diego) | no |
| D056 (MA CORI housing regulation) | 1 | `yes` | `official` | no: capture failed with HTTP 403. The row has an empty `text_file`, and there is no `D056.txt` |

- `corpus/links_only.csv` has 33 rows: exactly the 33 manifest rows without text.
- Rows by `jurisdictions`: MA 15, CA 14, NJ 10, Berkeley 9, Los Angeles 7, San Francisco 6,
  Boston 5, San Diego 5, Santa Ana 4, Cambridge 3, Hoboken 3, Jersey City 3, Newark 3.
- Every text file starts with `SOURCE: <url>`, `RETRIEVED: YYYY-MM-DD HH:MM UTC` and a blank
  line. The ingest stage checks the header against the manifest (`navigator/ingest/corpus.py`).
  All 54 match. The manifest's `retrieved_at` is the canonical retrieval date.
- Only the 54 text documents are extracted. Rows without text are recorded as unavailable
  in `outputs/docs.jsonl`, with the reason.

**Text gaps that affect answers** (from `docs/CONTRACT.md` section 6 and NOTES.md):

| Needed for | Corpus status |
|---|---|
| Hoboken algorithmic-pricing ban (T2) | D032-D034 `check-terms`, no text |
| Jersey City algorithmic-pricing ban (T2) | D035, D037 link-only. D036 has text but does not mention the ban |
| MA rent-control ballot question IP 25-21 (T5) | D059 link-only |
| Santa Ana algorithmic ban | D086 link-only |
| Hoboken, Newark, San Diego, Los Angeles municipal codes | `check-terms`. LA housing department pages D040-D043 have text |
| Second effective dates for Berkeley ch. 13.63 and the LA RSO formula (guide section 9) | D002 and the landlord-association source are not supplied as text |
| SB 763 (named in T1's title) | no text |

## 3. The address file

`data/starter/data/sample_addresses.csv` has **500 rows**. Columns: `address_id,
street_address, postal_city, state, zip, year_built, units, use_code, use_description,
source_dataset, retrieved_at`. All rows are retrieved 2026-10-01. The file has no owner
names, residents, rents or prices.

Missing facts by state:

| State | Rows | Missing `year_built` | Missing `units` |
|---|---|---|---|
| CA | 250 | 98 | 43 |
| NJ | 140 | 106 | 139 |
| MA | 110 | 8 | 60 |
| **Total** | **500** | **212** | **242** |

Missing facts by source data set:

| `source_dataset` | Rows | Missing year built | Missing units | Missing ZIP |
|---|---|---|---|---|
| LA County eGIS parcels | 80 | 6 | 3 | 0 |
| DataSF wv5m-vpq2 (2025 roll) | 80 | 2 | 0 | 80 |
| SANDAG/SanGIS parcels | 50 | 50 | 0 | 0 |
| Alameda County parcels (Berkeley) | 40 | 40 | 40 | 0 |
| NJOGIS Parcels & MOD-IV Composite | 140 | 106 | 139 | 0 |
| Boston Property Assessment FY2026 | 60 | 8 | 60 | 0 |
| Cambridge Property Database FY2026 (waa7-ibdu) | 50 | 0 | 0 | 50 |

NJ by postal city: Jersey City 50 rows (22 missing year built, 50 missing units), Hoboken 40
(36, 39), Newark 50 (48, 50).

Other input facts:
- **Postal city is not the legal city.** 38 rows have a postal city that is not one of the
  nine cities: 37 Boston neighborhoods (Dorchester 13, Roxbury 7, East Boston 6,
  Brighton 4, Allston 3, and one each of South Boston, Jamaica Plain, Hyde Park and
  Mattapan) and 1 San Ysidro (San Diego). Legal city comes from the Census Geocoder (section 5).
- **No house number:** A0098, A0128, A0295, A0376, A0380 (Boston neighborhoods) and A0346
  (San Diego).
- **Built in a certificate-of-occupancy cutoff year:** A0107 and A0432 (both Los Angeles,
  1978). These are `unknown` where the cutoff applies.
- Every row has a `use_description`. Where `units` is empty, it is parsed into
  `units_min` / `units_max` with reviewed patterns only (`config/unit_parsers.yaml`,
  `navigator/geo/units.py`). Anything unmatched gives no range.
- No Santa Ana addresses (guide 4.1). Santa Ana rules are extracted but never looked up.

## 4. Supplement path

Pages the pack doesn't supply as text can be added only through `data/supplement/` (see
`data/supplement/README.md` and `docs/CONTRACT.md` section 6):
- `manifest.csv` uses the starter columns, with `source_type` = `official`, `capture` =
  `manual`, and `sha256` of the stored text. Each `text/<doc_id>.txt` is stored byte for
  byte with the same two-line header.
- Pages are added one at a time with `python -m navigator ingest-doc <file> --jurisdiction
  "City, ST"` (or `rerun-live`, or `POST /ingest`), then run through the same extraction,
  verify, lookup and change stages. Nothing is hand-coded.
- Only official pages whose site terms allow capture may be added. Never bulk-scrape.
- **Current state: `data/supplement/` contains no documents.** All rules come from the
  starter corpus. The organizers have not answered whether `check-terms` texts will be
  released (NOTES.md open question 3).

## 5. External sources used

| Source | Used for | Where | Stored |
|---|---|---|---|
| US Census Geocoder (`geocoding.geo.census.gov`), benchmark `Public_AR_Current`, vintage `Current_Current` | address to coordinates; coordinates to state, county, incorporated place and (NJ, MA) county subdivision | `navigator/geo/census.py` (batch, `geographies/coordinates`, and `locations/onelineaddress` retries) | `cache/geocode/` (raw responses keyed by request content), `outputs/parcels.json` |
| Anthropic API (Claude) | build-time rule extraction and plain-language summaries. A processor, not a data source: it receives corpus text and extracted rule fields only | `navigator/extract/llm.py`, `navigator/explain/plain.py` | `cache/llm/` |

No other external source is used. LegiScan, Open States, TIGER/Line and code-publisher
sites (all allowed by guide section 6) are not called. The address strings sent to the
Census Geocoder come from the pack's public assessor data.

`config/jurisdictions.yaml` maps Census place GEOIDs to the corpus jurisdiction names for
the nine cities. It is a place-name table, not law, and each run re-checks it against the
manifest and the Census name.

## 6. Derived files

Pipeline outputs in `outputs/` (committed):

| File | Stage | Contents |
|---|---|---|
| `docs.jsonl` | ingest | one line per manifest row: full stored text, body offset, `text_sha256`, manifest `sha256` (as `source_sha256`), url, retrieval date, source type, and why text is unavailable |
| `chunks.jsonl` | chunk | chunk id, character range, heading, chunker version, overlap, dropped navigation lines |
| `candidates.jsonl` | extract | model candidates per chunk, with manifest source fields and provenance (cache key, model, chunk) |
| `rejects.jsonl` | verify | candidates rejected by a gate, with the reason |
| `rules.json` | verify | **submission.** `{"rules": [...]}`, schema fields only |
| `rules_internal.json` | verify | rules plus span offsets and match level, retrieval date, penalty, effective-date phrase, anchor and method, coverage predicates, `needs_review`, `review_reasons`, notes, provenance |
| `parcels.json` | geocode | per address: legal state and city, Census GEOIDs, coordinates, jurisdiction confidence and source, units (exact or range, and its source), year built, missing facts, review reasons |
| `lookups.json` | lookups | **submission.** `{"as_of", "lookups"}` for all 500 addresses |
| `lookups_internal.json` | lookups | rows plus `checked`, `not_checked`, `missing_facts`, `superseded_by`, confidence and reasons |
| `timeline.json`, `snapshots.json` | lookups | results across key dates (per address; per address and category), for the date slider |
| `changes.json` | changes | **submission.** T1 to T5: affected ids, conflict-flagged ids, notes |
| `changes_internal.json` | changes | per-test checks, notes list, `mapping_reviewed` |
| `summaries.json` | summaries | plain-language tenant and owner answers (English, Spanish) that passed the guards, with dropped reasons and `source_quote_sha` |
| `audit.jsonl` | all | append-only decision log (`navigator/audit.py`) |
| `STUB` | stubs | marker present only when outputs are contract-valid placeholders. The API then returns 503 |

Also: `scores/eval_latest.txt`, `scores/history.jsonl` and `scores/changes_report.txt`
(self-evaluation), `config/test_rule_map.yaml` (generated change-test id mapping,
`reviewed: false`), and `web/public/data/` (copies of outputs for the static UI fallback,
written by `web/scripts/sync-data.mjs` and not committed).

## 7. LLM cache and reproducibility

- Every LLM call is cached on disk in `cache/llm/<sha256>.json` (committed). Each entry
  stores its key parts, model, served model, request id, token usage, stop reason and the
  response.
- Extraction key: `text_sha256`, `chunk_id`, `chunker_version`, chunk character range,
  `prompt_version` and model (`navigator/extract/extract.py`, `navigator/extract/llm.py`).
  Summaries key: task, rule content sha, prompt version, prompt-file sha and model
  (`navigator/explain/plain.py`). Any change to the text, chunking, prompt or model
  misses the cache. A stale answer can't be reused.
- Models and prompt versions are set in `config/settings.yaml` (extraction stage model and
  `prompt_version`). The summary prompt is `summary_v1`.
- These models reject a `temperature` parameter, so determinism comes from the cache, not
  from sampling settings (NOTES.md, "Determinism"). A cached run makes no API call. To
  re-extract, bump the prompt version; never delete the cache.
- The geocoder cache works the same way (`cache/geocode/`). `offline=True` turns a cache
  miss into an error (`tests/test_geo.py::test_cache_miss_offline`).
- Reproduce: `python -m navigator all` (no API key or network needed with the committed
  caches), then `python -m navigator summaries` and `python -m navigator eval`. A new
  extraction needs `ANTHROPIC_API_KEY` (`.env.example`).
- Not yet measured: the eval's byte-identical two-run determinism check (item [8], "not
  measured yet"). `tests/test_geo.py::test_output_is_deterministic_and_matches_committed`
  covers geocoding.

## 8. Known data issues (from NOTES.md)

- The manifest `sha256` matches none of the 54 text files. It most likely hashes the
  original HTML or PDF. It is kept as informational `source_sha256`, and integrity and cache
  keys use our own `text_sha256`.
- D056 has no text (403 on capture).
- Some documents are web pages with navigation text. Chunking drops only repeated short
  menu lines (`navigator/extract/chunk.py`).
- Some documents are official summaries that quote statutes (for example D067). Rules taken
  from them cite the statute and set `source_doc_id` to the summary.
- D069 (NJ FAIR Act): the approval date is far from the effective-date sentence, so date
  anchors are searched across the whole document.
- D022 (CA AB 325) states no effective date. It comes from the bill's chaptering line plus
  the California default rule and is flagged `needs_review`.
- D001 (Berkeley ch. 13.63) records only a first reading, and is extracted as `pending`.
- Title-only bill pages (D045, D046) give one record whose quote is the bill title.
- D084 contains two characters beyond U+FFFF. The API returns both code-point and UTF-16
  offsets so the UI highlight lands exactly.
- Input ZIPs are unreliable (for example 11219 on a Newark row), and SF and Cambridge rows
  have no ZIP. Geocoder matches are accepted on the house number, not the ZIP.
- NJ MOD-IV unit codes: glued forms like `3SB2UG` give no range. `5B-64U/5B-64U-G` sums to
  128 and may be one building listed twice (NOTES.md open questions 4 and 8).
- Boston rows with no house number stay state-only (`city: null`, `needs_review`).
- `docs/hack-nation-event-brief.pdf` (the event brief) differs from the pack's v5 guide. The
  pack wins.
- The repo root also contains a second copy of the pack
  (`participant-final-no-hour16 3-20261003T223411Z-1-001/`). Its CSV files differ from
  `data/starter/` only in line endings. The pipeline reads only `data/starter/`.

## 9. Licensing and terms

- Code and data licensing: **TBD by organizers** (guide section 3, "Logistics"). The repo
  has no LICENSE file yet.
- Corpus texts are copies of public official pages supplied by the organizers. Their reuse
  terms follow each source site. `check-terms` pages were withheld by the organizers
  pending terms review, and we don't fetch them.
- Addresses come from public assessor data sets named in `source_dataset`. Their terms
  follow each publisher.
- Census Geocoder: a public US government service, used within its documented API.
- Outputs are a prototype for the hackathon. They are not a legal database and not a
  compliance product.

Not legal advice.
