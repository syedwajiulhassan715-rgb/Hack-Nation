# FRONTEND_PLAN.md — Rental Housing Law Navigator

Build plan for `web/`. Rules in CLAUDE.md apply here too, especially:
no law text in components, render only API fields, "Not legal advice" and as_of on
every screen. Backend contract: BACKEND_PLAN.md section 3.

Anchor: **Pick any building and get its rights label: six plain answers, every one
traced to the exact sentence of law, with what's coming next.**

Demo ideal: one input (a building), one action (drag the date), one clear result
(the label and the city change). Understandable in under 10 seconds.

---

## 1. Stack

| Need | Choice |
|---|---|
| App | Vite + React + TypeScript |
| Styling | Tailwind CSS with the tokens in section 3 (CSS variables) |
| Map | MapLibre GL JS via `react-map-gl/maplibre` |
| Tiles | OpenFreeMap vector tiles (free, no key). Load a light OpenFreeMap style JSON and recolor its layers to the night palette at load time |
| Geometry helpers | `@turf/circle`, `@turf/centroid`, `@turf/distance` |
| Animation | `motion` (Framer Motion) |
| Icons | `lucide-react` |
| API types | `openapi-typescript` generated from FastAPI `/openapi.json` into `src/api/types.ts` |
| Data fetching | plain `fetch` + a small cache; no global state library unless needed (Zustand is fine) |
| Deploy | Vercel |

Do not add: chart libraries, deck.gl, Cesium, Mapbox, component kits with their own
visual identity, a chat box.

---

## 2. Data rules (non-negotiable)

1. Every law fact on screen comes from an API response or the bundled copies of
   `outputs/*.json`. No statute text, citation, date, threshold or rule name in any
   component, constant or i18n file.
2. UI copy that is allowed in code: navigation, buttons, empty states, status labels
   ("Applies", "Unknown", ...), the six category questions only if the API does not
   provide them (prefer `category.question` from the API).
3. If a field is missing, render the documented empty state, never a placeholder that
   looks like law ("Lorem ipsum", "Up to 10%", sample citations).
4. During development before the backend is ready, use fixtures built from the team's
   `eval/gold_rules.json` and `eval/gold_addresses.json` (real corpus quotes and real
   address ids, hand-verified; the pack has no dev answer key).
   Store them in `web/fixtures/` marked `"_fixture": true`. The app shows a visible
   "Fixture data" badge when it renders them.
5. **Static fallback:** at build time copy `outputs/lookups.json`, `rules_internal.json`,
   `snapshots.json`, `parcels.json`, `timeline.json`, `changes.json`,
   `summaries.json` into `web/public/data/`. If the API is unreachable, the app reads
   these and disables only the features that need the API (user-entered facts, ingest).
   A small "Offline data" indicator appears in the footer.
6. User-entered facts are always shown as user-entered ("Using your input: built 1975"),
   never merged silently with source data.

---

## 3. Design direction: "Printed civic document over a night city"

The Rights Label is a bright printed object floating over a dark, quiet 3D city.
That contrast is the screenshot people remember. Commit to it everywhere.

### Tokens (CSS variables in `src/styles/tokens.css`)

```
/* Paper (label, drawers) */
--paper:        #F6F2E9;
--paper-2:      #ECE6D8;   /* row hover, input bg */
--ink:          #111111;   /* text, heavy rules */
--ink-2:        #4A4A45;   /* secondary text */
--ink-3:        #8A877E;   /* captions */

/* Night map */
--night-0:      #0B0E13;   /* background / land */
--night-1:      #121820;   /* water */
--night-2:      #1F252E;   /* roads */
--night-3:      #2A3039;   /* buildings */
--night-label:  #6B7380;   /* map labels */

/* Status (shared by label and beacons) */
--applies:      #4F7CFF;   /* the one accent */
--superseded:   #F2A33A;   /* amber */
--low-conf:     #F2A33A;   /* amber, dotted underline variant */
--conflict:     #E5484D;   /* red, only for conflicts */
--unknown:      #8A8F98;   /* gray, always dashed */
--not-yet:      #A78BFA;   /* violet, with countdown */
--pending:      rgba(79,124,255,0.35);  /* ghost of applies */
--none:         #2A3039;   /* no rule: same as buildings */
--highlight:    rgba(255,224,102,0.65); /* highlighter stroke on quoted span */

/* Law-stack slabs */
--slab-state:   rgba(79,124,255,0.22);
--slab-city:    rgba(45,212,191,0.26);
```

### Type
- Label and UI: **Archivo** (Google Fonts). Label title 900, row questions 700,
  body 400. Tabular numbers on (`font-variant-numeric: tabular-nums`).
- Statute text in the source drawer: **Source Serif 4**, 18px, line-height 1.6.
- Citations, dates, ids: **IBM Plex Mono**, 12 to 13px.
- Projector rule: label body text never below 15px; row questions 17px; title 34px.

### Shape and rules
- Label: square corners, 3px ink border, 10px ink rule under the header, 1px ink rules
  between rows, 5px ink rule above the footer. No shadows on paper except one soft
  drop shadow separating the label from the map (`0 24px 60px rgba(0,0,0,0.45)`).
- Everything on the map side: no borders, no cards. Floating chips use
  `rgba(11,14,19,0.72)` with 8px radius and 12px backdrop blur.

### Motion (meaningful only)
| Event | Motion | Duration |
|---|---|---|
| Building click | camera flyTo (pitch 60, zoom ~17.5); slabs rise one after another | 900 ms camera, slabs staggered 120 ms |
| Label open | slides in from right, rows fade in top to bottom | 350 ms, 40 ms stagger |
| Date crosses an effective date | affected rows flip on X axis and change status; beacons recolor | 300 ms |
| Unknown resolved by user input | dashed border animates to solid; value types in | 400 ms |
| New law ingested | ring ripple from the new law's city outward; affected beacons pulse | 1.6 s |
| Citation click | drawer slides up; highlight stroke draws left to right across the span | 300 ms + 600 ms |
Respect `prefers-reduced-motion`: replace motion with instant state changes.

### Copy
Sentence case. Plain words. No exclamation marks. Buttons are verbs ("Show source",
"Add a new law"). Status words are fixed: Applies, Unknown, Superseded, Starts later,
Proposed, Conflict, No rule found.

---

## 4. Screens and components

```
web/src/
  api/            client.ts, types.ts (generated), fallback.ts
  map/            CityMap.tsx, beacons.ts, slabs.ts, nightStyle.ts, ripple.ts
  label/          RightsLabel.tsx, LabelRow.tsx, RowDetail.tsx, FactInput.tsx,
                  ProposedSection.tsx, NotesSection.tsx, StatusChip.tsx
  source/         SourceDrawer.tsx, HighlightedText.tsx, AuditTrail.tsx
  timeline/       DateSlider.tsx
  search/         SearchBox.tsx, CityChips.tsx
  ingest/         IngestPanel.tsx
  changes/        ChangesPage.tsx
  layout/         AppShell.tsx, Footer.tsx
  styles/         tokens.css
```

### 4.1 AppShell
- Full-screen map. Top-left: SearchBox + CityChips. Bottom: DateSlider. Right: RightsLabel
  (hidden until a building is selected). Top-right: category filter chips and
  "Add a new law".
- **Footer strip (always visible):** `As of <date> · Not legal advice · Sources: official
  statute and ordinance text · How this works`. Styled in paper colors as a thin printed
  strip, not as a warning banner.

### 4.2 First screen (the 10-second test)
- Map at a national-to-city overview with all sample beacons lit.
- Centered over the map, a paper card with one line:
  **"Pick any building. See which housing laws apply, and what's about to change."**
  Below it: SearchBox ("123 Main St, Hoboken, NJ") and a **Random building** button.
- The card disappears on first interaction.

### 4.3 SearchBox and CityChips
- Input accepts address text or ZIP. `GET /search?q=`.
- A ZIP result only moves the camera to the ZIP area and lists sample buildings there.
  It never shows a jurisdiction or rules by itself.
- CityChips: the 9 cities with sample addresses. Click = flyTo city.
- Random building = pick a random `address_id`, flyTo, select.

### 4.4 CityMap
- Night style: load an OpenFreeMap style, then set paint properties: background and
  land `--night-0`, water `--night-1`, roads `--night-2`, labels `--night-label`.
- 3D buildings: `fill-extrusion` on the `building` source-layer, color `--night-3`,
  height from `render_height`, base from `render_min_height`, opacity 0.9.
- **Beacons (sample addresses):** GeoJSON source from `parcels.json` (500 rows). Each address becomes a
  12 m radius circle polygon (`@turf/circle`) extruded 6 m above ground, colored by the
  status of the currently selected category at the current slider date (data-driven
  `fill-extrusion-color` from a `status` property). Add a soft circle layer under each
  beacon for visibility at low zoom.
- Category filter chips (top right): All protections / Rent increase / Eviction /
  Deposit / Fees / Screening / Rent-setting software. "All" colors by count of
  applying rules (ink-to-accent ramp); a single category colors by its status.
- **Click a beacon:** select the address, `GET /lookup?address_id=&as_of=&role=`.
  Also `queryRenderedFeatures` at the address point on the building layer; if a footprint
  exists, copy it into a `selected-building` source and extrude it in `--applies`.
- **Click any other building:** take its centroid, `GET /resolve?lat=&lng=`. If a sample
  address is within 30 m, select it. Otherwise `POST /lookup` with no facts:
  the label shows jurisdiction-level rules, and building-dependent rows show Unknown
  with fact inputs.
- **Law-stack slabs** (`slabs.ts`): the pack has two rule levels, state and city
  (CONTRACT.md 8). When a building is selected, add two extruded layers using the building
  footprint (or the beacon circle), each 4 m thick, at building height + 18 m (state) and
  + 36 m (city). Animate base and height from 0 with requestAnimationFrame. Colors
  `--slab-state`, `--slab-city`. Each slab gets an HTML chip anchored above the building:
  "California · 4 rules", "Los Angeles · 3 rules" (counts from the lookup response).
  Clicking a chip filters the label to that level. If the city could not be resolved,
  show only the state slab and a chip "City not confirmed" in amber.

### 4.5 RightsLabel (the core component)
Layout, top to bottom:
1. Title "Locus" with the Locus mark (Archivo 900, 34px; renamed from "Rights label") + Tenant | Owner toggle.
2. Building line: `<units or units range> units · built <year or "year unknown"> · <address>`.
   When units come from `use_description` (CONTRACT.md 7), show the range with a small
   "from assessor use code" tag, e.g. "7-30 units". If legal city ≠ postal city, show
   "Mailing city: Dorchester · Legal city: Boston"; it explains itself and is a trust moment.
3. Jurisdiction breadcrumb from `jurisdiction_stack`.
4. Heavy rule. Column header: `As of <date>` left, `Source` right.
5. Six rows, fixed order, one per category (always all six, even when empty).
6. Heavy rule, then **Proposed, not law** section (pending rules, ghost style).
7. **Notes** section (from `notes`: laws that did not become law, e.g. a struck ballot
   question, shown struck through with the date).
8. Footer: "Not legal advice. Tap a citation to see the exact sentence in the law."

Each `LabelRow` shows: the question (tenant or owner wording from API), the answer
(`answer` field, or the start of `quoted_span` in quotes if `answer` is null), a status
chip, and the citation on the right in mono, underlined.

Row states (the five `result` values from CONTRACT.md 3, plus UI-only states):
| State | Visual |
|---|---|
| Applies | solid row; chip "Applies" in `--applies` |
| Unknown | dashed 1px border around the row; chip "Unknown"; line "Depends on: year built" + FactInput |
| Superseded | collapsed under the rule that supersedes it: "State rule steps aside: <superseded_by citation>"; amber chip |
| Starts later | violet chip with countdown "Starts in 271 days" (computed from `effective_date` and as_of in the client) |
| Proposed | 35% opacity, moved to the Proposed section |
| Conflict | red 2px left border; chip "Conflict"; line "Two laws disagree. A court would decide."; links to both citations |
| Low confidence | amber dotted underline on the answer; tooltip lists `confidence_reasons`; "Needs human review" tag |
| Open question | when `conflict_note` reports two sources with different dates (Berkeley ch. 13.63, LA RSO formula): small "Sources disagree on the date" line with both dates and both sources |
| Derived from year built | fine print under the answer: "Based on year built, not the certificate of occupancy date" |
| No rule found | row present, text "No rule found in our sources for this level", gray |

A row can hold more than one rule (state + city). Show the winning rule first; the
others collapse below with their status.

`RowDetail` (expand on row click):
- "What this means for you" (or "What you must do" in owner mode): `answer`.
- "Who decides": level of the winning rule, plus why if superseded or conflicting.
- "Effective": `effective_date`. "Key value": `key_value` if present.
- "Why": the row's `explanation` (deterministic, from lookups.json).
- "Show source" button opens SourceDrawer.

`FactInput` (Unknown rows):
- Numeric input for the named missing fact, with validation (year 1800 to current year,
  units 1 to 2000). Inline error text if invalid.
- On submit: `POST /lookup` with `{lat, lng, facts, as_of, role}`. Only that row and any
  rows depending on the same fact re-render. Show "Using your input" chip.
- Disabled with a short note in offline fallback mode.

### 4.6 SourceDrawer
- Slides up over the lower half of the screen, paper background.
- Header in mono: citation, `source_url` (link "Open official text"), `retrieved_at`,
  `effective_date`, status.
- Body: `GET /rule/{id}` text window in Source Serif 4, with the quoted span wrapped in
  a highlighter stroke (`--highlight`) using `span_start`/`span_end`. Auto-scroll to it.
- Side note: confidence score and reasons; "Audit trail" expands `GET /audit?team_rule_id=`
  as a short list (extracted by model X at time T, span verified exact/tolerant,
  date check passed, ...).
- **Reasoning boundary** block (stretch goal in the brief, cheap and high trust): two short
  lists from the row's `checked` and `not_checked` fields, titled "What we checked" and
  "What we couldn't check". Example: checked "City from Census address match",
  "Built 1962", "Effective date before Oct 1, 2026"; couldn't check "Owner type",
  "Certificate of occupancy date". Always shown, never collapsed to zero items.

### 4.7 DateSlider
- Range 2024-01-01 to 2028-12-31, default as_of from the API (2026-10-01).
- Tick marks: global key dates from `snapshots.json` dates; when a building is
  selected, add its `timeline` dates with small labels on hover.
- Snap to tick when within 10 days. Big date readout above the thumb.
- While dragging: recolor beacons from `snapshots.json` (no API calls, no stutter).
  On release: refetch the selected building's lookup for that as_of.
- Buttons: "Today" (resets to default as_of), and play (animates through tick dates,
  1.2 s each). Play is the demo shortcut for the magic moment.

### 4.8 IngestPanel ("Add a new law")
- Drop zone for a text file in the corpus format (two-line `SOURCE:` / `RETRIEVED:`
  header). Demo use: re-run a real corpus document live with the cache off (the guide
  says the demo should show the extraction pipeline), or a document for one new
  jurisdiction (stretch goal).
  `POST /ingest`, read the streamed progress events.
- Steps shown as a vertical checklist with live counts:
  Reading document → Extracting rules (n found) → Verifying quotes (n verified, n rejected)
  → Recomputing buildings → n buildings affected.
- On completion: ripple from the city of the new law, affected beacons pulse, and a
  result card: new rule(s) with citation, status, effective date, "Show source".
- If the API errors, show the error plainly and a "Try again" button. No fake success.

### 4.9 ChangesPage (`/changes`, for the videos and judges)
- One row per supplied test (T1 to T5) from `GET /changes`: name,
  expected behavior (from the test case file), our result (status before/after,
  affected count, conflict flags), pass/fail from `make eval`.
- Group results into four visibly separate kinds: enacted, not yet effective, pending,
  failed (T5). The brief lists this separation as a mark of a strong submission.
- A link to the latest `make eval` report (rendered as plain text), labeled as a
  self-evaluation (the pack has no official scoring script).
- "Show on map" sets the category filter, the slider date, and highlights the affected
  beacons.

---

## 5. Backend fields the frontend depends on

From BACKEND_PLAN.md section 3, plus:
- `GET /snapshots` (or `outputs/snapshots.json`): for a list of key dates, per address,
  per category: result. Powers the slider without API calls.
- `notes` array in LookupResult: non-law notes such as failed ballot measures, with
  date and source.
- `category.question` in tenant and owner wording.
- CORS enabled for the Vercel domain and localhost.

---

## 6. Build order

| # | Slice | Done when |
|---|---|---|
| 1 | Shell, tokens, fonts, footer, fixture loader with "Fixture data" badge | renders on fixtures |
| 2 | RightsLabel with all row states on fixtures (build a hidden `/states` page that shows every state at once) | every state looks right on a projector |
| 3 | SourceDrawer with highlighted span | highlight lands on the exact sentence |
| 4 | Map: night style, 3D buildings, beacons from the 500 addresses, click to select | click → label opens |
| 5 | Bind to real API; static fallback | works with API off |
| 6 | DateSlider with snapshots + play button | dragging recolors 500 beacons smoothly |
| 7 | Law-stack slabs + chips | rise animation on select |
| 8 | FactInput live re-evaluation | unknown resolves in under 1 s |
| 9 | IngestPanel + ripple | a corpus document re-runs end to end with the cache off |
| 10 | ChangesPage, Spanish toggle (stretch), polish | freeze at hour 20 |

If time runs short, cut in this order: Spanish, ChangesPage polish, slab chips,
ripple. Never cut: label states, source drawer, slider, footer.

---

## 7. Acceptance checks before submission

- A stranger understands the first screen in 10 seconds without narration.
- Building click gives visible feedback within 300 ms (camera starts moving immediately).
- Slider drag holds 50+ fps with all beacons recoloring.
- Every row's citation opens the drawer with the span highlighted, the retrieval date,
  the as-of date and the reasoning boundary (the brief's "strong submission" list asks
  for source document, quoted span, retrieval date and as-of date on every answer).
- Unknown, Superseded, Starts later, Proposed, Conflict, Notes all appear somewhere in
  real data. Pick demo buildings from the actual outputs, for example: an SF building
  built before 1979 for Superseded, a San Diego or Berkeley building for Unknown (no year
  built in the data), a Dorchester row for "mailing city ≠ legal city", Jersey City for
  Conflict after 2027-07-01, Boston or Cambridge for Proposed (MA bills). Hoboken and
  Jersey City conflicts depend on whether their ordinance texts become available
  (CONTRACT.md 6); check before you rehearse.
- "Not legal advice" and the as_of date visible on every screen, including the drawer
  and the changes page.
- `grep -rnE "§|Civ\. Code|G\.L\.|N\.J\.S\.A|Admin\. Code|P\.L\." web/src` returns nothing.
- Works on the projector resolution (1920x1080) and on a phone (label becomes a bottom
  sheet).
- Works with the API stopped (offline fallback).

---

## 8. Demo path the UI must support (90 seconds)

1. First screen, anchor sentence. Click **Random building** or type an SF address.
2. Camera flies in, slabs rise, label slides in. Point at the superseded rent row:
   "City law beats state law here, and it tells you so."
3. Tap the citation: the exact sentence lights up in the statute.
4. Choose "Rent-setting software" filter and press play on the slider: California beacons
   flip at 2026-01-01 (T1); at 2027-07-01 New Jersey lights up (T3) and any Jersey City
   or Hoboken addresses with a local ban turn red for conflict.
5. Jump to a San Diego building: "Unknown, depends on year built." Type a year; the row
   resolves.
6. A Dorchester address: "Mailing city Dorchester, legal city Boston." Proposed MA bills
   shown as ghosts (T4); no rent cap anywhere in Boston, with the failed ballot question
   as a note if it is in the data (T5).
7. Show the pipeline: drop a real corpus ordinance (e.g. the SF algorithmic-device page),
   cache off, watch extraction and quote verification run, see the city ripple.
8. End on the footer: as of date, not legal advice, every answer traced to its source.
