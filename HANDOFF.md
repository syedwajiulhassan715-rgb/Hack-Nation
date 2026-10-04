# HANDOFF: where the project stands (2026-10-04, later session)

For the next Claude session or teammate. Read CLAUDE.md first, then this file, then NOTES.md.
Not legal advice.

## Done (on `main`, pushed to GitHub)
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
- USER TODO: in the ArcGIS key's Settings, confirm the referrer restriction
  (`https://rental-law-navigator.vercel.app`): on 2026-10-04 a request with no referrer still
  got tiles. Rotate the key after the hackathon (it was shared in a chat session).
- USER TODO: remove the 16 old agent worktrees in `.claude/worktrees/` (all branches merged
  into main). Their uncommitted drafts are archived in `../worktree-backup-2026-10-04.tar.gz`
  and their LLM cache entries were copied into `cache/llm/`. Command:
  `git worktree list` then `git worktree remove --force <path>` and `git branch -d <branch>`.
- Human review of `eval/gold/*.yaml` (set `reviewed_by`) and of the summaries (r-0034
  paraphrase); review `config/test_rule_map.yaml` (set `reviewed: true`).
- Screening-fee $ figure from a Berkeley page (D005) shown as a CA key_value (flag it).
- FAIR Act `interaction` empty in the rights label.
- No LICENSE file (team decision).
- A0352 Newark geocoder tie; 5 Boston rows without a house number.
- Demo: rehearse the 90-second path (FRONTEND_PLAN.md section 8) and `rerun-live`.
- Hour-20 rule: after the freeze, fixes only, no refactors.

## Tooling notes
- Windows; no `make`: use `python -m navigator <stage>` or `./run.ps1 <target>`.
- Browser checks: Node + Playwright scripts in `%TEMP%\livecheck` (`earth.mjs <url>` checks
  the map and orbit) with Chromium at
  `%LOCALAPPDATA%\ms-playwright\chromium-1234\chrome-win64\chrome.exe`.
- Logged in: GitHub (gh), Vercel CLI, Hugging Face CLI.
- Heredocs in Git Bash mangle `\n` inside Python strings; use the Write/Edit tools for code.
