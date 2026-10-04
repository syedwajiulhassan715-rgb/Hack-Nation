# Deploying the web app (Vercel)

The site is a static Vite build. It works in two modes:

- **Live API**: `VITE_API_BASE` points at the deployed FastAPI service (`python -m navigator api`).
  Lookups, typed-in facts (`POST /lookup`), `lang=es` answers and the audit trail come from the API.
- **Offline data**: if `VITE_API_BASE` is unset, or the API does not answer `/health`, the app
  reads the precomputed copies in `/data/*` that `scripts/sync-data.mjs` builds from `../outputs`.
  The footer shows "Offline data". Only typed-in facts and "Add a new law" are turned off.
  If the API was cold-starting, the app checks `/health` again after 4, 12, 30 and 60 seconds
  and switches to the API when it responds.

## Vercel project settings

| Setting | Value |
|---|---|
| Framework preset | Vite |
| Root Directory | `web` |
| Include files outside of the Root Directory in the Build Step | **On** (needed: the build reads `../outputs`, `../data/starter`, `../scores`) |
| Install Command | `npm ci` (also set in `vercel.json`) |
| Build Command | `npm run build` (runs `prebuild` = `node scripts/sync-data.mjs`, then `tsc -b && vite build`) |
| Output Directory | `dist` |
| Node.js version | 20.x or newer |

`web/vercel.json` already sets the install/build commands, the output directory, the SPA
rewrite (every path except `/data/*` and `/assets/*` serves `index.html`, so `/changes` works
on reload) and caching:

- `/assets/*`: hashed file names, `max-age=31536000, immutable`
- `/data/*`: `max-age=300, s-maxage=3600, stale-while-revalidate=86400` (file names do not change between deploys)
- `/data/meta.json` and HTML: `max-age=0, must-revalidate`

## Environment variables (Vercel > Settings > Environment Variables)

| Name | Example | Notes |
|---|---|---|
| `VITE_API_BASE` | `https://navigator-api.example.com` | Optional. No trailing slash. Must be **https** (an http API is blocked as mixed content and the app falls back to offline data). Read at build time, so redeploy after changing it. |
| `SYNC_ALLOW_MISSING` | `1` | Do not set for the public site. Lets the build pass without `../outputs`. |
| `OUTPUTS_DIR`, `REPO_ROOT` | | Only if the outputs live somewhere other than `../outputs`. |

## The data check

`npm run build` fails, with a message that names the missing file and these settings, when:

- `../outputs` does not exist (usually: "Include files outside of the Root Directory" is off), or
- `rules_internal.json`, `parcels.json`, `lookups_internal.json` (or `lookups.json`),
  `snapshots.json` or `changes.json` is missing, invalid or empty.

Missing optional files (`summaries.json`, `timeline.json`, `changes_internal.json`,
`../data/starter/dev/change_tests.json`, `../scores/eval_latest.txt`, corpus text) are listed in
the build log and shown as documented empty states. Without the corpus text the source drawer
shows only the verified quote.

## What the API deployment must provide

- `NAVIGATOR_CORS_ORIGINS=https://<your-project>.vercel.app` (comma-separated; add any custom
  domain and preview URLs you want to use). Localhost is always allowed.
- `NAVIGATOR_DISABLE_INGEST=1` on the public API. `POST /ingest` then answers 403 and the
  "Add a new law" panel explains that live extraction is shown in the recorded demo, or run
  locally with `python -m navigator rerun-live <file> --jurisdiction "City, ST"`.
- HTTPS, and `GET /health` answering within a few seconds.

## Check a build locally

```
cd web
npm ci
npm run build                                # offline-only build
VITE_API_BASE=http://127.0.0.1:8000 npm run build   # build against a local API
npx vite preview --port 4173
```

Then open http://localhost:4173, pick a building, open a citation, switch EN/ES, and stop the
API to confirm the "Offline data" fallback. `npm test`, `npm run typecheck`, `npm run lint` and
`npm run check:no-law` should all pass.

Not legal advice. No es asesoría legal.
