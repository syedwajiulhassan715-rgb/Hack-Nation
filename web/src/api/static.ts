// Loaders for the bundled precomputed JSON in public/data (written by scripts/sync-data.mjs).
import type {
  ChangeTestDef,
  ChangeTestInternal,
  ChangeTestOutput,
  Parcel,
  RuleRecord,
} from './types'
import type { CompactSnapshots } from './snapshots'
import type { InternalLookupRow, TimelineEntry } from './fallback'

const BASE = `${import.meta.env.BASE_URL}data/`

const cache = new Map<string, Promise<unknown>>()

async function fetchJson<T>(name: string, optional = false): Promise<T | null> {
  const res = await fetch(BASE + name)
  if (!res.ok) {
    if (optional) return null
    throw new Error(`Bundled data file missing: ${name} (run npm run sync-data)`)
  }
  const ct = res.headers.get('content-type') ?? ''
  // Vite's dev server answers unknown paths with index.html; treat that as missing.
  if (ct.includes('text/html')) {
    if (optional) return null
    throw new Error(`Bundled data file missing: ${name} (run npm run sync-data)`)
  }
  return (await res.json()) as T
}

function once<T>(key: string, fn: () => Promise<T>): Promise<T> {
  if (!cache.has(key)) {
    const p = fn()
    p.catch(() => cache.delete(key))
    cache.set(key, p)
  }
  return cache.get(key) as Promise<T>
}

export interface Meta {
  as_of: string | null
  synced_at: string
  present: Record<string, unknown>
  missing: string[]
}

export const loadMeta = () => once('meta', () => fetchJson<Meta>('meta.json', true))

export const loadParcels = () =>
  once('parcels', async () => {
    const d = await fetchJson<{ parcels: Parcel[] }>('parcels.json')
    return d?.parcels ?? []
  })

export const loadRules = () =>
  once('rules', async () => {
    const d = await fetchJson<{ as_of: string; rules: RuleRecord[] }>('rules_internal.json')
    const byId = new Map<string, RuleRecord>()
    for (const r of d?.rules ?? []) byId.set(r.team_rule_id, r)
    return { as_of: d?.as_of ?? null, rules: d?.rules ?? [], byId }
  })

/** summaries.json may not exist yet (plain-language layer is optional). */
export const loadSummaries = () => once('summaries', () => fetchJson<unknown>('summaries.json', true))

export const loadSnapshots = () =>
  once('snapshots', () => fetchJson<CompactSnapshots>('snapshots.compact.json', true))

export interface StaticLookup {
  address_id: string
  as_of: string
  internal: boolean
  rows: InternalLookupRow[]
  timeline: TimelineEntry[]
}

export const loadStaticLookup = (addressId: string) =>
  once(`lookup:${addressId}`, () => fetchJson<StaticLookup>(`lookups/${addressId}.json`, true))

export const loadDocText = (docId: string) =>
  once(`doc:${docId}`, async () => {
    const res = await fetch(`${BASE}docs/${docId}.txt`)
    if (!res.ok) return null
    if ((res.headers.get('content-type') ?? '').includes('text/html')) return null
    return await res.text()
  })

export const loadStaticChanges = () =>
  once('changes', async () => {
    const [outputs, internal, tests] = await Promise.all([
      fetchJson<Record<string, ChangeTestOutput>>('changes.json', true),
      fetchJson<{ tests: Record<string, ChangeTestInternal> }>('changes_internal.json', true),
      fetchJson<ChangeTestDef[]>('change_tests.json', true),
    ])
    return { outputs: outputs ?? {}, internal: internal?.tests ?? {}, tests: tests ?? [] }
  })

export const loadStaticEval = () =>
  once('eval', async () => {
    const res = await fetch(`${BASE}eval_latest.txt`)
    if (!res.ok || (res.headers.get('content-type') ?? '').includes('text/html')) return null
    return await res.text()
  })

export const loadTimelineDates = () =>
  once('timeline_dates', async () => (await fetchJson<{ dates: string[] }>('timeline_dates.json', true))?.dates ?? [])
