#!/usr/bin/env node
// Copies the pipeline's precomputed outputs into web/public/data so the app can run
// read-only without the API (FRONTEND_PLAN.md 2.5). Nothing here creates law content:
// every file is a copy or a lossless re-shaping of ../outputs and the starter corpus.
//
// Usage: node scripts/sync-data.mjs   (env OUTPUTS_DIR / REPO_ROOT override the paths)
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const webDir = path.resolve(here, '..')
const repoRoot = path.resolve(process.env.REPO_ROOT ?? path.join(webDir, '..'))
const outputsDir = path.resolve(process.env.OUTPUTS_DIR ?? path.join(repoRoot, 'outputs'))
const dest = path.join(webDir, 'public', 'data')

// Result codes shared with src/api/snapshots.ts. Keep in sync.
const RESULTS = ['none', 'applies', 'unknown', 'superseded', 'not_yet_effective', 'pending']
const CATEGORIES = [
  'rent_increase_limits',
  'just_cause_eviction',
  'security_deposits',
  'application_screening_fees',
  'screening_restrictions',
  'algorithmic_rent_setting',
]

function readJson(p) {
  return JSON.parse(fs.readFileSync(p, 'utf8'))
}
function writeJson(p, data) {
  fs.mkdirSync(path.dirname(p), { recursive: true })
  fs.writeFileSync(p, JSON.stringify(data))
}
function exists(p) {
  return fs.existsSync(p)
}

function parseCsv(text) {
  const rows = []
  let row = []
  let field = ''
  let quoted = false
  for (let i = 0; i < text.length; i++) {
    const c = text[i]
    if (quoted) {
      if (c === '"' && text[i + 1] === '"') {
        field += '"'
        i++
      } else if (c === '"') quoted = false
      else field += c
    } else if (c === '"') quoted = true
    else if (c === ',') {
      row.push(field)
      field = ''
    } else if (c === '\n' || c === '\r') {
      if (c === '\r' && text[i + 1] === '\n') i++
      row.push(field)
      field = ''
      if (row.some((f) => f !== '')) rows.push(row)
      row = []
    } else field += c
  }
  if (field !== '' || row.length) {
    row.push(field)
    rows.push(row)
  }
  return rows
}

const present = {}
const missing = []

function main() {
  if (!exists(outputsDir)) {
    console.error(`[sync-data] outputs directory not found: ${outputsDir}`)
    process.exit(exists(path.join(dest, 'meta.json')) ? 0 : 1)
  }
  fs.rmSync(dest, { recursive: true, force: true })
  fs.mkdirSync(dest, { recursive: true })

  // 1. Plain copies (small files).
  for (const name of ['rules_internal', 'parcels', 'changes', 'changes_internal', 'summaries']) {
    const src = path.join(outputsDir, `${name}.json`)
    if (exists(src)) {
      fs.copyFileSync(src, path.join(dest, `${name}.json`))
      present[name] = true
    } else {
      present[name] = false
      missing.push(`${name}.json`)
    }
  }

  // 1b. Join the ZIP from the starter address file onto parcels (search by ZIP offline).
  const csvPath = path.join(repoRoot, 'data', 'starter', 'data', 'sample_addresses.csv')
  if (present.parcels && exists(csvPath)) {
    const rows = parseCsv(fs.readFileSync(csvPath, 'utf8'))
    const header = rows.shift() ?? []
    const iId = header.indexOf('address_id')
    const iZip = header.indexOf('zip')
    if (iId >= 0 && iZip >= 0) {
      const zipById = new Map(rows.map((r) => [r[iId], r[iZip]]))
      const p = readJson(path.join(dest, 'parcels.json'))
      for (const parcel of p.parcels ?? []) {
        if (parcel.zip == null && zipById.has(parcel.address_id)) parcel.zip = zipById.get(parcel.address_id)
      }
      writeJson(path.join(dest, 'parcels.json'), p)
    }
  }

  // 2. Lookups: split lookups_internal (+ timeline) per address so the browser only
  //    downloads the selected building.
  const lookupsPath = exists(path.join(outputsDir, 'lookups_internal.json'))
    ? path.join(outputsDir, 'lookups_internal.json')
    : path.join(outputsDir, 'lookups.json')
  let lookupsAsOf = null
  if (exists(lookupsPath)) {
    const lk = readJson(lookupsPath)
    lookupsAsOf = lk.as_of
    const timeline = exists(path.join(outputsDir, 'timeline.json'))
      ? readJson(path.join(outputsDir, 'timeline.json'))
      : null
    present.timeline = !!timeline
    if (!timeline) missing.push('timeline.json')
    for (const [id, rows] of Object.entries(lk.lookups)) {
      writeJson(path.join(dest, 'lookups', `${id}.json`), {
        address_id: id,
        as_of: lk.as_of,
        internal: lookupsPath.endsWith('lookups_internal.json'),
        rows,
        timeline: timeline?.timeline?.[id] ?? [],
      })
    }
    present.lookups = path.basename(lookupsPath)
    if (timeline) writeJson(path.join(dest, 'timeline_dates.json'), { dates: timeline.dates ?? [] })
  } else {
    present.lookups = false
    missing.push('lookups_internal.json')
  }

  // 3. Snapshots: compact per-date strings, one char per (address, category).
  //    char = 'a' + resultIndex * 2 + conflictFlag
  const snapPath = path.join(outputsDir, 'snapshots.json')
  if (exists(snapPath)) {
    const snap = readJson(snapPath)
    const ids = new Set()
    for (const byAddr of Object.values(snap.snapshots)) for (const id of Object.keys(byAddr)) ids.add(id)
    const addressIds = [...ids].sort()
    const codes = {}
    for (const [date, byAddr] of Object.entries(snap.snapshots)) {
      let s = ''
      for (const id of addressIds) {
        const cats = byAddr[id] ?? {}
        for (const cat of CATEGORIES) {
          const v = cats[cat]
          let idx = v ? RESULTS.indexOf(v.result) : 0
          if (idx < 0) idx = 0
          s += String.fromCharCode(97 + idx * 2 + (v?.conflict_flag ? 1 : 0))
        }
      }
      codes[date] = s
    }
    writeJson(path.join(dest, 'snapshots.compact.json'), {
      dates: snap.dates ?? Object.keys(snap.snapshots).sort(),
      categories: CATEGORIES,
      results: RESULTS,
      address_ids: addressIds,
      codes,
    })
    present.snapshots = true
  } else {
    present.snapshots = false
    missing.push('snapshots.json')
  }

  // 4. Source documents referenced by rules (for the highlight drawer offline).
  const docDirs = [
    path.join(repoRoot, 'data', 'starter', 'corpus', 'text'),
    path.join(repoRoot, 'data', 'supplement', 'text'),
    path.join(repoRoot, 'data', 'supplement'),
  ]
  let docCount = 0
  if (present.rules_internal) {
    const rules = readJson(path.join(dest, 'rules_internal.json')).rules ?? []
    const docIds = new Set(rules.map((r) => r.source_doc_id).filter(Boolean))
    for (const id of docIds) {
      const src = docDirs.map((d) => path.join(d, `${id}.txt`)).find(exists)
      if (!src) {
        missing.push(`text for ${id}`)
        continue
      }
      fs.mkdirSync(path.join(dest, 'docs'), { recursive: true })
      fs.copyFileSync(src, path.join(dest, 'docs', `${id}.txt`))
      docCount++
    }
  }
  present.docs = docCount

  // 5. Change test definitions and the latest self-evaluation report.
  const testsPath = path.join(repoRoot, 'data', 'starter', 'dev', 'change_tests.json')
  if (exists(testsPath)) {
    fs.copyFileSync(testsPath, path.join(dest, 'change_tests.json'))
    present.change_tests = true
  } else missing.push('change_tests.json')
  const evalPath = path.join(repoRoot, 'scores', 'eval_latest.txt')
  if (exists(evalPath)) {
    fs.copyFileSync(evalPath, path.join(dest, 'eval_latest.txt'))
    present.eval_report = true
  } else missing.push('eval_latest.txt')

  writeJson(path.join(dest, 'meta.json'), {
    as_of: lookupsAsOf,
    synced_at: new Date().toISOString(),
    present,
    missing,
  })
  console.log(`[sync-data] wrote ${dest}`)
  console.log(`[sync-data] present: ${JSON.stringify(present)}`)
  if (missing.length) console.log(`[sync-data] missing (handled as empty states): ${missing.join(', ')}`)
}

main()
