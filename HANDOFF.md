# HANDOFF: where the project stands (2026-10-04, submitted)

For the next Claude session or teammate. Read CLAUDE.md first, then this file, then NOTES.md.
Not legal advice.

## Done (on `main`, pushed to GitHub)
- Product name is **Locus** (team Locus): the panel title, tab title and favicon/logo
  (`web/public/favicon.svg`, `assets/locus-*`). README rewritten with logo, badges, mermaid
  diagram and screenshots from the live site (`assets/screens/`).
- Phases 0–8: ingest, chunk, extract (Opus, cached, prompt `extract_v6`), verify, geocode,
  engine/lookups, change tracking T1–T5, API (FastAPI), plain-language summaries (EN+ES),
  incremental `ingest-doc` / `rerun-live` / `POST /ingest`.
- Coverage conditions as predicates (SF pre-1979, Berkeley pre-1980, CA cap and San Diego
  15-year rolling exemption, LA JCO vs RSO, section operative dates) and `fix/medium-city`
  (medium Census matches confirm the legal city), plus "subject to local rent control"
  derived per address from the city's own extracted rent-limit rules.
- Current numbers: see the generated metrics block in README.md / METHOD.md and
  `scores/eval_latest.txt` (never copy them by hand).
- Frontend `web/`: satellite globe (MapLibre globe + terrain + sky), colorful 3D buildings,
  360° bird's-eye orbit after choosing a building (stops on click/scroll/touch/key, "Orbit
  building" restarts it, off under reduced motion), premium depth/motion pass, EN/ES toggle,
  offline fallback on bundled data.
- **Ask Locus** (2026-10-04, `4d9c9a9`, `web/src/ask/`): a question box in the building panel
  with an animated mascot, "Loci" (`Mascot.tsx`; idle/thinking/answer/unsure moods, off under
  reduced motion). `matcher.ts` + `lexicon.ts` map an EN/ES question to a category or to
  why-unknown / upcoming / conflict / jurisdiction / overview, then assemble the answer only from
  that building's lookup rows: verbatim quote excerpt, citation (opens the source drawer),
  retrieval date, as-of date, "Not legal advice". No LLM, works offline; a question nothing
  covers gets "I can only answer from the laws Locus has…" plus suggestions (fail closed).
  Contract in `types.ts`; 18 tests in `matcher.test.ts`.
- **Panel headline fix** (`web/src/lib/rows.ts`): each category's headline row is the best
  result tier, then relevance to the category question (`headlineScore`, UI words only), so e.g.
  the deposit question leads with the maximum-deposit rule, not a penalty rule. Rows are never
  hidden or reordered across tiers. An `applies` row with no plain answer whose quote is an
  exemption sentence shows "Why it applies here:" + the engine explanation (`answerText` kind
  `explanation`).
- Engine explanation grammar: "meets" for one item (`navigator/engine/explain_lookup.py`);
  outputs differ only in that text. Eval unchanged (hard checks PASS, gold 119/132).
- **Demo video**: `assets/demo/locus-demo.mp4` (57 s, 1440×900, voice-over). Recorded with a
  Playwright script on Edge against the local API + dev server; title/tech/outro cards read their
  numbers from `scores/eval_latest.txt` and real `extract --docs D001` + `verify` output.
  Voice: Kokoro TTS (local, Apache-2.0, voice `af_heart`, speed 1.08), mixed with ffmpeg. The
  build scripts were in a session scratchpad (not in the repo); the TTS venv is at
  `C:\Users\syedw\kvenv` (can be deleted). Re-recording needs the scripts rewritten.
  The README no longer links the video; DEMO.md names it as the Plan B backup.
- **Submission prep (2026-10-04)**, submitted to the Hack-Nation global submission:
  - Event name is "Hack-Nation Global Hackathon (RealPage challenge)" in README (disclaimer box
    and footer), CLAUDE.md, DATA_CARD.md and `deploy/hf-space/README.md`. The organizers' own
    pack (`data/starter/`, PDF) still says "MIT AI Hackathon" and stays unchanged (read-only).
  - README screenshots retaken from the live site and renamed `assets/screens/*-v2.*` (same
    names were served from GitHub's cache); new `06-ask-locus-v2.jpg` in the tour.
  - DEMO.md: new Beat 1b "Ask Locus" (0:40–0:55; other beats tightened, still 2:00), checklist
    item, Judge Q&A "Is Ask Locus a chatbot?", Plan B rows.
  - GitHub repo renamed to **syedwajiulhassan715-rgb/Locus** (old `Hack-Nation` URL
    redirects); use the new URL in submissions.
  - Verified: fresh clone from GitHub with no API key/.env reruns `python -m navigator all`
    offline, 328 tests pass, rules/lookups/changes.json byte-identical; local determinism PASS;
    scripted walk of every DEMO.md click on the live site + API 38/38 (after the final Vercel
    redeploy too). `/ingest` on Render returns 403 for a valid request (422 only for a
    malformed body).

## Live deployment
- Frontend LIVE: https://rental-law-navigator.vercel.app (Vercel account hassan12go, project
  `rental-law-navigator`, linked in `web/.vercel`). Uses the Render API; falls back to bundled
  data ("Offline data" in the footer) while the API sleeps or is down.
  - Redeploy: `cd web && vercel build --prod && vercel deploy --prebuilt --prod --yes`
    (builds locally because the build reads ../outputs). Env for the build: see
    `web/.env.example` (`VITE_API_BASE`, `VITE_ESRI_API_KEY`).
- Imagery: Esri World Imagery (zoom 19) is LIVE, key in `web/.env.local` (git-ignored, with
  `VITE_API_BASE`; `vercel build` reads it). Without the key the build falls back to USGS
  orthoimagery (public domain, zoom 16). Esri's terms require an ArcGIS account, so only the
  keyed ArcGIS Location Platform endpoint is used, never the keyless one.
- API LIVE on Render (free): https://rental-law-navigator-api.onrender.com (Blueprint from
  `render.yaml`, auto-deploys from main, `NAVIGATOR_CORS_ORIGINS` set to the Vercel URL,
  `NAVIGATOR_DISABLE_INGEST=1`). The frontend is built with
  `VITE_API_BASE=https://rental-law-navigator-api.onrender.com`; keep that in every rebuild.
  Free Render sleeps after ~15 min idle (first request ~30-60 s): open `/health` before a demo.
  Show live extraction locally: `python -m navigator rerun-live <file> --jurisdiction "City, ST"`.

## Open items
- `.github/workflows/keep-api-awake.yml` pings the Render API `/health` every 10 minutes so the
  live demo never sleeps during judging. Disable it after judging (Actions tab > Keep API awake
  > Disable workflow).
- USER TODO: in the ArcGIS key's Settings, confirm the referrer restriction
  (`https://rental-law-navigator.vercel.app`): on 2026-10-04 a request with no referrer still
  got tiles. Rotate the key after the hackathon (it was shared in a chat session).
- Old agent worktrees removed (2026-10-04): all 16 worktrees and their 17 merged branches
  (incl. `fix/medium-city`) are gone. Their 696 LLM cache entries were verified byte-identical
  in `cache/llm/`; other uncommitted drafts remain in `../worktree-backup-2026-10-04.tar.gz`.
- Human review of `eval/gold/*.yaml` (set `reviewed_by`) and of the summaries (r-0034
  paraphrase); review `config/test_rule_map.yaml` (set `reviewed: true`). Use
  `eval/REVIEW_CHECKLIST.md` (regenerate: `python -m eval.review_checklist`): each gold rule
  next to its anchor in the source text, each address with a Census Geocoder link.
- Screening-fee $ figure from a Berkeley page (D005) shown as a CA key_value (flag it).
- FAIR Act `interaction` empty in the Locus panel.
- A0352 Newark geocoder tie; 5 Boston rows without a house number.
- Demo: rehearse the 2-minute path in DEMO.md (now with Ask Locus) and `rerun-live`.
- Do not rotate the ArcGIS key until judging ends (imagery would fall back to USGS zoom 16).
- Ask Locus polish: the unsure "?" is slightly clipped in the small pill mascot; long replies
  scroll inside the thread (max 440px) inside the scrolling panel.
- Remaining weak headlines: 234 of 3,000 category headlines are still a notice/penalty-type row,
  because it is the only row in the best result tier (e.g. Newark application fees).
- Hour-20 rule: after the freeze, fixes only, no refactors.

## Tooling notes
- Windows; no `make`: use `python -m navigator <stage>` or `./run.ps1 <target>`.
- Browser checks: Node + Playwright scripts in `%TEMP%\livecheck` (`earth.mjs <url>` checks
  the map and orbit) with Chromium at
  `%LOCALAPPDATA%\ms-playwright\chromium-1234\chrome-win64\chrome.exe`. Playwright MCP needs
  Chrome, which is not installed; scripts with `chromium.launch({ channel: 'msedge' })` work.
- Long pip paths fail on this machine (no long-path support): make venvs at short paths.
- ffmpeg 9 is installed (winget); it takes `-/filter_complex <file>`, not `-filter_complex_script`.
- Logged in: GitHub (gh), Vercel CLI, Hugging Face CLI.
- Heredocs in Git Bash mangle `\n` inside Python strings; use the Write/Edit tools for code.
