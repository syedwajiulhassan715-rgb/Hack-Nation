# CONTRACT.md — what the starter pack actually says

Written from the participant pack `participant-final-no-hour16` (files listed below).
This file beats BACKEND_PLAN.md and FRONTEND_PLAN.md wherever they differ.
Put it at `docs/CONTRACT.md` and the pack at `data/starter/`.

---

## 1. Which brief applies

The pack is the **RealPage v5 participant version**:
- no dev answer key, no score.py, no held-out key
- **five** change tests T1 to T5, no hour-16 document
- participant guide = `README.md` in the pack

So `make eval` (BACKEND_PLAN.md 4b) is our scoring loop. Ignore everything about
score.py, the dev key and T6 unless organizers hand them out later.

Pack contents:
```
README.md                              participant guide (read sections 1-9)
corpus/corpus_manifest.csv             87 rows
corpus/links_only.csv                  33 rows (sources with no text)
corpus/text/D0xx.txt                   54 text files
data/sample_addresses.csv              500 rows
schema/rule_record.schema.json         rule format
schema/sample_rule_record.json         worked example (NJ deposit rule)
submission_templates/{rules,lookups,changes}.json
dev/change_tests.json                  T1..T5
```

---

## 2. Rule record (`schema/rule_record.schema.json`)

Required: `team_rule_id, jurisdiction, level, category, status, title, requirement,
citation, source_url, quoted_span`.

| Field | Type / enum | Notes |
|---|---|---|
| `team_rule_id` | string | ours, e.g. `r-0001` |
| `jurisdiction` | string | `"CA"`, `"NJ"`, `"MA"` or `"City, ST"` e.g. `"San Francisco, CA"` |
| `level` | `state` \| `city` | **no county level** |
| `category` | `rent_increase_limits`, `just_cause_eviction`, `security_deposits`, `application_screening_fees`, `screening_restrictions`, `algorithmic_rent_setting` | |
| `status` | `in_force`, `not_yet_effective`, `pending`, `failed` | as of 2026-10-01. **`failed` is a valid rule status** (T5) |
| `title` | string | |
| `requirement` | string | 1-2 plain sentences |
| `key_value` | string \| null | headline number or formula, e.g. "1.5 months' rent" |
| `coverage_conditions` | string \| object \| null | we write an object (our predicate form) |
| `exemptions` | string \| null | |
| `overrides` | array of team_rule_ids | rules this one supersedes **or yields to** |
| `interaction` | string \| null | the direction, in words: "yields to r-0012 where local rent control applies" |
| `effective_date` | string \| null, `YYYY`, `YYYY-MM` or `YYYY-MM-DD` | |
| `citation` | string | official cite |
| `source_doc_id` | string \| null | `doc_id` from the manifest. **Always fill it** |
| `source_url` | string | copy from manifest, never from the model |
| `quoted_span` | string, **minLength 20** | exact text from the source document |
| `confidence` | number 0-1 \| null | |
| `conflict_flag` | boolean | |
| `conflict_note` | string \| null | |

There is **no retrieval-date field** in the schema. Retrieval date comes from the
manifest (`retrieved_at`) and the `RETRIEVED:` header of the text file, joined via
`source_doc_id`. Show it in the UI and API; keep it in our internal model.

Precedence goes in the schema's own fields: `overrides` (ids) + `interaction` (direction).
Our internal model may add `yields_to`/`supersedes` lists, but the submission uses
`overrides` + `interaction`.

`rules.json` shape (from the template): `{"rules": [ <rule record>, ... ]}`.

---

## 3. `lookups.json`

```json
{"as_of": "2026-10-01",
 "lookups": {
   "A0001": [
     {"team_rule_id": "r-0007", "result": "applies",
      "explanation": "Statewide NJ rule; building has 5+ units so the owner-occupied exemption cannot apply.",
      "conflict_flag": false}
   ]}}
```
- Keys are `address_id` values, **all 500**. An address with no rules gets `[]`.
- `result` ∈ `applies`, `unknown`, `superseded`, `not_yet_effective`, `pending`.
- **Leave out rules that don't apply.** `failed` rules never appear in lookups.
- `superseded` = covered, but a stricter rule at another level governs (guide's example:
  California's statewide cap where local rent control applies).
- `explanation`: one sentence, generated deterministically from the engine's reasoning
  (which facts decided it, which exemption, which rule superseded it). Not an LLM call.
- Rule status → lookup result: `in_force` → evaluate coverage; `not_yet_effective` on
  the query date → `not_yet_effective`; `pending` → `pending`; `failed` → omit.
  Status is recomputed from `effective_date` for other query dates (T1, T3).

## 4. `changes.json`

```json
{"T1": {"affected_address_ids": [...], "conflict_flag_address_ids": [...], "notes": "..."}}
```
One key per test T1 to T5. Include `conflict_flag_address_ids` on every test (empty list
if none). `notes`: which of our team_rule_ids matched the test's rule ids, the as-of
dates used, and any data limitation.

---

## 5. Change tests (`dev/change_tests.json`)

The tests name the organizers' rule ids (`CA-ALG-01` etc.), not ours. We map them with a
deterministic matcher (state/city + category + status from the test fields and id
pattern: `ALG` → algorithmic_rent_setting, `RENT` → rent_increase_limits, `P` → pending
or failed). Matcher output goes to `config/test_rule_map.yaml`; a human reviews it once.

| Test | Type | Our rule(s) | Expected (from the file) | Affected set |
|---|---|---|---|---|
| T1 | as_of 2025-12-31 → 2026-01-02 | CA state algorithmic rule (AB 325) | not_yet_effective before, applies after, **every CA address** | all 250 CA addresses |
| T2 | boundary, as_of 2026-10-01 | Hoboken and Jersey City algorithmic bans | HOB only Hoboken, JC only Jersey City, neither Newark | Hoboken + Jersey City addresses |
| T3 | as_of 2026-10-01 → 2027-07-02 | NJ FAIR Act | not_yet_effective, then applies for **every NJ address**; JC + Hoboken carry conflict flag | all 140 NJ; conflict = JC + Hoboken |
| T4 | pending | MA S.2983, H.5222 | pending for every Boston and Cambridge address; affected if enacted = **all MA addresses** | all 110 MA |
| T5 | negative | MA rent-control ballot question (IP 25-21) | no rent cap for any Boston/Cambridge address; **recorded as failed**; affected empty | empty |

---

## 6. Corpus facts

- Manifest columns: `doc_id, jurisdictions, url, source_type, capture, retrieved_at,
  sha256, text_file, status`. `text_file` is relative to `corpus/` (e.g. `text/D001.txt`).
- The manifest `sha256` matches **none** of the 54 text files (verified phase 0; it hashes
  the original capture). Treat it as informational only.
- Text files start with two header lines, then a blank line:
  ```
  SOURCE: <url>
  RETRIEVED: 2026-10-01 22:35 UTC
  ```
  Strip them from the extractable text but keep offsets relative to the full file so the
  UI highlight works on the stored file.
- **Only 54 of 87 documents have text.** 23 are `link-only` (law firms, news), 9 are
  `check-terms` code-publisher pages (ecode360, amlegal, gocodebook) with no text, and
  D056 (MA CORI regulation) is an empty file (403 on capture). Extract from the 54 only.
- Several documents are web pages with navigation junk; some are official summaries that
  quote statutes (e.g. D067, the NJ DCA Truth in Renting guide, 160 KB, contains
  N.J.S.A. 46:8-21.2 and 2A:18-61.1 text). Rules extracted from a summary cite the
  statute it quotes and set `source_doc_id` to the summary.

### Text gaps that hit the change tests (decide at kickoff)

| Needed for | Law | Corpus status |
|---|---|---|
| T2 | Hoboken algorithmic ban (ch. 158) | D032-D034 `check-terms`, no text |
| T2 | Jersey City algorithmic ban (§218-12) | D035, D037 link-only; D036 does not mention it |
| T5 | MA ballot question IP 25-21 (struck 2026-06-23) | D059 link-only, no text |
| extraction | Santa Ana algorithmic ban (NS-3090) | D086 link-only |
| extraction | Hoboken, Newark municipal code (rent control etc.) | D032-D034, D070-D072 `check-terms` |
| extraction | LA municipal code (RSO, JCO) | D038 `check-terms`; LAHD pages D040-D043 have text |

**Ask the organizers first:** will the `check-terms` texts be released, and may teams add
single official pages themselves? If yes, add them through a supplement:
`data/supplement/manifest.csv` (same columns, `source_type` = official, `capture` =
manual, terms checked) + text files with the same two-line header, captured one page at a
time from an official source (city site or legislature), never bulk-scraped. The same
pipeline extracts them; nothing is hand-coded.
If no: do **not** invent the rule. T2 is answered with what the corpus supports, and
`changes.json` notes say the source text was not supplied. T5 is still correct (empty set,
no rent cap: MA G.L. c.40P §4 in D048 bars local rent control), and the failed ballot
question is recorded only if a citable span exists. Say this openly in METHOD.md.

### Effective dates are often written relatively
- NJ FAIR Act (D069): "approved July 20, 2026" and "shall take effect on the first day of
  the twelfth month next following the date of enactment" → 2027-07-01.
- CA AB 325 (D022): chaptered 10/06/25; no explicit effective date in the text. California
  statutes take effect on January 1 of the following year unless stated otherwise.
- SF §37.10C (D081): "went into effect on October 14, 2024".

So extraction returns the **verbatim date phrase** and the **anchor date** (enactment,
approval or chaptering), and `navigator/extract/dates.py` computes the ISO date with
named, unit-tested rules (`first_day_of_nth_month_after`, `ca_default_jan1_next_year`,
`explicit_date`). The rule used is stored internally; any rule not stated in the corpus
text itself (e.g. the CA default) sets `confidence` lower and `needs_review` with reason.

### Known open questions the guide rewards surfacing (section 9)
- Berkeley ch. 13.63: two published effective dates (ordinance text vs a law-firm alert).
- NJ FAIR Act may preempt the Jersey City and Hoboken ordinances (D069 §6b:
  "A municipality shall be prohibited from enacting an ordinance that conflicts with this
  act").
- LA's new RSO formula: two published effective dates (LAHD vs a landlord association).
- California's screening-fee cap: no single official 2026 dollar figure. Show the formula,
  never compute a number.
Detect conflicting dates automatically: two verified sources giving different dates for
the same rule → `conflict_flag: true`, `conflict_note` with both dates and sources.

---

## 7. Address facts (`data/sample_addresses.csv`)

Columns: `address_id, street_address, postal_city, state, zip, year_built, units,
use_code, use_description, source_dataset, retrieved_at`.

| | Rows | Missing year built | Missing units |
|---|---|---|---|
| CA | 250 (LA 80, SF 80, SD 50, Berkeley 40) | 98 (all SD + Berkeley + few) | 43 (Berkeley + few) |
| NJ | 140 (JC 50, Hoboken 40, Newark 50) | 106 | 139 |
| MA | 110 (Boston 60, Cambridge 50) | 8 | 60 (Boston apartment rows) |

- `postal_city` is not the legal city: Boston rows include Dorchester, Roxbury, East
  Boston, Brighton, Allston, South Boston, Jamaica Plain, Hyde Park, Mattapan; San Diego
  has San Ysidro. Resolve with the Census Geocoder.
- **`use_description` carries unit ranges** and must be parsed into `units_min` /
  `units_max` when `units` is empty:
  - "Five or more apartments", "Alameda County use code (5+ units)",
    "SANDAG asr_landuse 14-16 (5+ units)" → min 5
  - "Apartment 5 to 14 Units" → 5-14; "Apartment 15 Units or more" → min 15;
    "TIC Bldg 4 units or less" → max 4
  - Boston "APT 7-30 UNITS" → 7-30; "SUBSD HOUSING S- 8", "LUXURY APARTMENT",
    "ELDERLY HOME" → no range
  - Cambridge "4-8-UNIT-APT" → 4-8; ">8-UNIT-APT" → min 9
  - NJ MOD-IV descriptions often contain `<n>U` ("3S-B-A-22U" → 22; "3B-7U/4B-24U-G" →
    sum 31). Use only clear `\d+U` tokens; otherwise no range.
  Store `units_source` = `units` | `use_description`. Coverage predicates on units use
  interval logic: a test like `units >= 3` is TRUE if `units_min >= 3`, FALSE if
  `units_max < 3`, else UNKNOWN.
- **Year built is not certificate of occupancy** (guide 4.1): cutoffs SF on or before
  1979-06-13, LA on or before 1978-10-01. Rule: built in a year **after** the cutoff year →
  condition FALSE; built in a year **before** the cutoff year → TRUE with
  `confidence` lowered and reason "derived from year built"; built **in** the cutoff year
  → UNKNOWN; missing → UNKNOWN. Only 2 rows are built in 1978 or 1979.
- No owner names: owner-type conditions (e.g. CA small-landlord deposit exception) are
  UNKNOWN unless another fact rules them out. The guide allows either "unknown" or
  explaining why the exception can't apply (e.g. a unit-count limit the building exceeds).
- No Santa Ana addresses. Santa Ana rules count for extraction only.

---

## 8. Jurisdiction stack

Two levels only: state (`"CA"`) and city (`"Los Angeles, CA"`). Counties are not
rule levels in this pack; keep county GEOIDs internally only for geocoding checks.
San Francisco is `"San Francisco, CA"`, level `city`.
The 9 cities with addresses: Los Angeles, San Francisco, San Diego, Berkeley (CA);
Jersey City, Hoboken, Newark (NJ); Boston, Cambridge (MA). Plus Santa Ana (rules only).
