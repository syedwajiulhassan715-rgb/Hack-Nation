// API client for navigator/api (BACKEND_PLAN.md section 3) with a read-only fallback to
// the bundled precomputed JSON. Every function returns the same shape in both modes.
import distance from '@turf/distance'
import {
  CATEGORIES,
  type AuditEntry,
  type CategoryBlock,
  type ChangesBundle,
  type LookupResult,
  type LookupRow,
  type Parcel,
  type ResolveResult,
  type Role,
  type RuleRecord,
  type RuleSource,
  type SearchHit,
} from './types'
import {
  buildLookupResult,
  normalizeSummaries,
  numbersGrounded,
  sortRows,
  addressLabel,
  verifiedSummaryIds,
} from './fallback'
import {
  loadDocText,
  loadMeta,
  loadParcels,
  loadRules,
  loadStaticChanges,
  loadStaticEval,
  loadStaticLookup,
  loadSummaries,
} from './static'
import { DISCLAIMER, QUESTIONS } from '../copy'

export type Mode = 'api' | 'offline'
export type Lang = 'en' | 'es'

const envBase = import.meta.env.VITE_API_BASE as string | undefined
export const API_BASE: string | null = envBase ? envBase.replace(/\/$/, '') : import.meta.env.DEV ? '/api' : null

let mode: Mode = 'offline'
let modeListeners: Array<(m: Mode) => void> = []
export const getMode = () => mode
export function onModeChange(fn: (m: Mode) => void) {
  modeListeners.push(fn)
  return () => {
    modeListeners = modeListeners.filter((f) => f !== fn)
  }
}
function setMode(m: Mode) {
  if (m !== mode) {
    mode = m
    modeListeners.forEach((f) => f(m))
  }
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function api<T>(path: string, init?: RequestInit, timeoutMs = 8000): Promise<T> {
  if (!API_BASE) throw new ApiError(0, 'No API configured')
  const ctrl = new AbortController()
  const t = setTimeout(() => ctrl.abort(), timeoutMs)
  try {
    const res = await fetch(API_BASE + path, { ...init, signal: ctrl.signal })
    if (!res.ok) {
      let msg = `${res.status} ${res.statusText}`
      try {
        const body = await res.json()
        if (body?.detail) msg = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
      } catch {
        /* not json */
      }
      throw new ApiError(res.status, msg)
    }
    if ((res.headers.get('content-type') ?? '').includes('text/html')) throw new ApiError(0, 'API not reachable')
    return (await res.json()) as T
  } finally {
    clearTimeout(t)
  }
}

/** Probe GET /health once at startup; afterwards a network failure flips to offline. */
export async function detectMode(): Promise<Mode> {
  if (!API_BASE) {
    setMode('offline')
    return mode
  }
  try {
    await api<unknown>('/health', undefined, 2500)
    setMode('api')
  } catch {
    setMode('offline')
    retryHealth()
  }
  return mode
}

// A hosted API may be cold-starting. Keep serving bundled data and probe again a few times;
// switch to the live API only once it answers.
let retrying = false
function retryHealth(delays = [4000, 12000, 30000, 60000]) {
  if (retrying || !API_BASE) return
  retrying = true
  const next = (i: number) => {
    if (i >= delays.length || mode === 'api') {
      retrying = false
      return
    }
    setTimeout(async () => {
      try {
        await api<unknown>('/health', undefined, 8000)
        setMode('api')
        retrying = false
      } catch {
        next(i + 1)
      }
    }, delays[i])
  }
  next(0)
}

function isNetworkError(e: unknown) {
  return !(e instanceof ApiError) || e.status === 0 || e.status >= 502
}

// ---------- shared static indexes ----------

export async function getDefaultAsOf(): Promise<string | null> {
  const [meta, rules] = await Promise.all([loadMeta(), loadRules().catch(() => null)])
  return meta?.as_of ?? rules?.as_of ?? null
}

export const getParcels = loadParcels
export const getRules = loadRules

// ---------- lookup ----------

function str(v: unknown): string | null {
  return typeof v === 'string' ? v : null
}
function groundedOrNull(answer: string | null, span: string): string | null {
  return answer && numbersGrounded(answer, span) ? answer : null
}
function arr(v: unknown): string[] {
  return Array.isArray(v) ? v.filter((x) => typeof x === 'string') : []
}

/** Fill any missing fields of an API LookupResult so the UI renders empty states, not crashes. */
export function normalizeLookup(raw: Record<string, unknown>, role: Role): LookupResult {
  const cats = Array.isArray(raw.categories) ? (raw.categories as Record<string, unknown>[]) : []
  const byCat = new Map(cats.map((c) => [c.category as string, c]))
  const categories: CategoryBlock[] = CATEGORIES.map((category) => {
    const c = byCat.get(category) ?? {}
    const rows: LookupRow[] = (Array.isArray(c.rows) ? (c.rows as Record<string, unknown>[]) : []).map((r) => ({
      team_rule_id: String(r.team_rule_id ?? ''),
      result: (r.result as LookupRow['result']) ?? 'unknown',
      level: (r.level as LookupRow['level']) ?? 'state',
      title: str(r.title) ?? '',
      // the API already checks source_quote_sha and numbers; re-check numbers here (fail closed)
      answer: groundedOrNull(str(r.answer), str(r.quoted_span) ?? ''),
      explanation: str(r.explanation) ?? '',
      key_value: str(r.key_value),
      quoted_span: str(r.quoted_span) ?? '',
      citation: str(r.citation) ?? '',
      source_doc_id: str(r.source_doc_id),
      source_url: str(r.source_url) ?? '',
      retrieved_at: str(r.retrieved_at),
      effective_date: str(r.effective_date),
      missing_facts: arr(r.missing_facts),
      superseded_by: str(r.superseded_by),
      superseded_by_citation: str(r.superseded_by_citation),
      review_reasons: arr(r.review_reasons),
      conflict_flag: !!r.conflict_flag,
      conflict_note: str(r.conflict_note),
      confidence: typeof r.confidence === 'number' ? r.confidence : null,
      confidence_reasons: arr(r.confidence_reasons),
      needs_review: !!r.needs_review,
      checked: arr(r.checked),
      not_checked: arr(r.not_checked),
    }))
    return {
      category,
      question: str(c.question) ?? QUESTIONS[category][role],
      rows: sortRows(rows),
      no_rule_note: str(c.no_rule_note),
    }
  })
  const facts = (raw.facts as LookupResult['facts']) ?? {}
  const userFacts =
    raw.user_facts && typeof raw.user_facts === 'object' && Object.keys(raw.user_facts).length
      ? (raw.user_facts as Record<string, number>)
      : undefined
  return {
    _postal_city: str(facts.postal_city),
    _jurisdiction_confidence: str(facts.jurisdiction_confidence),
    _user_facts: userFacts,
    _computed: str(raw.computed),
    address_id: str(raw.address_id),
    address: str(raw.address) ?? '',
    as_of: str(raw.as_of) ?? '',
    generated_at: str(raw.generated_at) ?? undefined,
    disclaimer: str(raw.disclaimer) ?? DISCLAIMER,
    jurisdiction_stack: Array.isArray(raw.jurisdiction_stack) ? (raw.jurisdiction_stack as LookupResult['jurisdiction_stack']) : [],
    facts,
    missing_facts: arr(raw.missing_facts),
    categories,
    notes: Array.isArray(raw.notes) ? (raw.notes as LookupResult['notes']) : [],
    _source: 'api',
  }
}

async function attachParcel(r: LookupResult): Promise<LookupResult> {
  if (!r.address_id) return r
  const parcels = await loadParcels().catch(() => [] as Parcel[])
  const p = parcels.find((x) => x.address_id === r.address_id)
  if (p) {
    r._postal_city = r._postal_city ?? p.postal_city
    r._jurisdiction_confidence = r._jurisdiction_confidence ?? p.jurisdiction_confidence ?? null
    if (!r.address) r.address = addressLabel(p)
  }
  return r
}

export async function offlineLookup(addressId: string, asOf: string, role: Role, lang: Lang = 'en'): Promise<LookupResult> {
  const [parcels, rules, summariesRaw, lookup, defaultAsOf] = await Promise.all([
    loadParcels(),
    loadRules(),
    loadSummaries(),
    loadStaticLookup(addressId),
    getDefaultAsOf(),
  ])
  const parcel = parcels.find((p) => p.address_id === addressId)
  if (!parcel) throw new Error(`Address ${addressId} is not in the bundled data`)
  if (!lookup) throw new Error(`No precomputed lookup for ${addressId} in the bundled data`)
  const summaries = normalizeSummaries(summariesRaw)
  const rowRules = lookup.rows.map((r) => rules.byId.get(r.team_rule_id)).filter((r): r is RuleRecord => !!r)
  return buildLookupResult({
    parcel,
    rows: lookup.rows,
    timeline: lookup.timeline,
    rulesById: rules.byId,
    summaries,
    verifiedSummaries: await verifiedSummaryIds(summaries, rowRules),
    asOf,
    defaultAsOf: lookup.as_of ?? defaultAsOf ?? asOf,
    role,
    lang,
  })
}

export async function getLookup(addressId: string, asOf: string, role: Role, lang: Lang = 'en'): Promise<LookupResult> {
  if (mode === 'api') {
    try {
      const raw = await api<Record<string, unknown>>(
        `/lookup?address_id=${encodeURIComponent(addressId)}&as_of=${asOf}&role=${role}&lang=${lang}`,
      )
      return attachParcel(normalizeLookup(raw, role))
    } catch (e) {
      if (!isNetworkError(e)) throw e
      setMode('offline')
    }
  }
  return offlineLookup(addressId, asOf, role, lang)
}

/** POST /lookup: live engine run with user-entered facts. API only. */
export async function postLookup(body: {
  lat: number
  lng: number
  facts: Record<string, number>
  as_of: string
  role: Role
  lang?: Lang
  address_id?: string | null
}): Promise<LookupResult> {
  if (mode !== 'api') throw new ApiError(0, 'Live lookups need the API; the app is running on bundled data.')
  const raw = await api<Record<string, unknown>>('/lookup', {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  })
  const r = normalizeLookup(raw, body.role)
  if (!r._user_facts && Object.keys(body.facts).length) r._user_facts = body.facts
  if (!r.address_id && body.address_id) r.address_id = body.address_id
  return attachParcel(r)
}

// ---------- search / resolve ----------

export async function search(q: string): Promise<SearchHit[]> {
  const query = q.trim()
  if (!query) return []
  if (mode === 'api') {
    try {
      const raw = await api<unknown>(`/search?q=${encodeURIComponent(query)}`)
      const list = Array.isArray(raw) ? raw : ((raw as { results?: unknown[] })?.results ?? [])
      const isZip = (raw as { match?: string })?.match === 'zip' || /^\d{5}$/.test(query)
      return (list as Record<string, unknown>[]).map((h) => ({
        address_id: String(h.address_id ?? ''),
        label: str(h.address) ?? str(h.label) ?? [h.street_address, h.postal_city, h.state].filter(Boolean).join(', '),
        lat: typeof h.lat === 'number' ? h.lat : null,
        lng: typeof h.lng === 'number' ? h.lng : null,
        kind: isZip ? 'zip' : 'address',
      }))
    } catch (e) {
      if (!isNetworkError(e)) throw e
      setMode('offline')
    }
  }
  const parcels = await loadParcels()
  if (/^\d{5}$/.test(query)) {
    return parcels
      .filter((p) => p.zip === query)
      .slice(0, 25)
      .map((p) => ({ address_id: p.address_id, label: addressLabel(p), lat: p.lat, lng: p.lng, kind: 'zip' as const }))
  }
  const tokens = query.toUpperCase().split(/[\s,]+/).filter(Boolean)
  return parcels
    .filter((p) => {
      const hay = `${p.address_id} ${addressLabel(p)} ${p.city ?? ''}`.toUpperCase()
      return tokens.every((t) => hay.includes(t))
    })
    .slice(0, 12)
    .map((p) => ({ address_id: p.address_id, label: addressLabel(p), lat: p.lat, lng: p.lng, kind: 'address' as const }))
}

export async function resolvePoint(lat: number, lng: number): Promise<ResolveResult> {
  if (mode === 'api') {
    try {
      return await api<ResolveResult>(`/resolve?lat=${lat}&lng=${lng}`)
    } catch (e) {
      if (!isNetworkError(e)) throw e
      setMode('offline')
    }
  }
  // Offline: only the nearest sample address within 30 m; jurisdiction is not resolved.
  const parcels = await loadParcels()
  let best: Parcel | null = null
  let bestD = Infinity
  for (const p of parcels) {
    if (p.lat == null || p.lng == null) continue
    const d = distance([lng, lat], [p.lng, p.lat], { units: 'meters' })
    if (d < bestD) {
      bestD = d
      best = p
    }
  }
  return {
    state: null,
    city: null,
    nearest_address_id: best && bestD <= 30 ? best.address_id : null,
  }
}

// ---------- rule source / audit ----------

function locate(text: string, quote: string, start: number | null, end: number | null) {
  if (start != null && end != null && text.slice(start, end) === quote) return { start, end }
  if (!quote) return null
  // Offsets may count code points (Python) rather than UTF-16 units; search near them.
  const near = start != null ? Math.max(0, start - 200) : 0
  let i = text.indexOf(quote, near)
  if (i < 0) i = text.indexOf(quote)
  return i >= 0 ? { start: i, end: i + quote.length } : null
}

const WINDOW = 2400

export async function getRuleSource(id: string, asOf: string): Promise<RuleSource> {
  if (mode === 'api') {
    try {
      const raw = await api<Record<string, unknown>>(`/rule/${encodeURIComponent(id)}`)
      const rule = ((raw.rule ?? raw.record ?? raw) as RuleRecord) ?? null
      // navigator/api RuleDetail: text_window = {text, offsets, offsets_utf16{span_start_in_window,...}}
      const tw = (raw.text_window && typeof raw.text_window === 'object' ? raw.text_window : null) as Record<string, unknown> | null
      const text = tw ? str(tw.text) : (str(raw.text_window) ?? str(raw.window) ?? str(raw.text))
      const off = (tw?.offsets_utf16 ?? tw?.offsets ?? null) as Record<string, number> | null
      const s = off?.span_start_in_window ?? null
      const e = off?.span_end_in_window ?? null
      const loc = text ? locate(text, rule.quoted_span, s, e) : null
      return {
        rule,
        text,
        span_start: loc?.start ?? null,
        span_end: loc?.end ?? null,
        source_url: str(raw.source_url) ?? rule.source_url,
        retrieved_at: str(raw.retrieved_at) ?? rule.retrieved_at ?? null,
        as_of: str(raw.as_of) ?? asOf,
      }
    } catch (e) {
      if (!isNetworkError(e)) throw e
      setMode('offline')
    }
  }
  const rules = await loadRules()
  const rule = rules.byId.get(id)
  if (!rule) throw new Error(`Rule ${id} is not in the bundled data`)
  const full = rule.source_doc_id ? await loadDocText(rule.source_doc_id) : null
  if (!full) {
    return { rule, text: null, span_start: null, span_end: null, source_url: rule.source_url, retrieved_at: rule.retrieved_at ?? null, as_of: asOf }
  }
  const loc = locate(full, rule.quoted_span, rule.span_start ?? null, rule.span_end ?? null)
  if (!loc) {
    return { rule, text: null, span_start: null, span_end: null, source_url: rule.source_url, retrieved_at: rule.retrieved_at ?? null, as_of: asOf }
  }
  const from = Math.max(0, loc.start - WINDOW)
  const to = Math.min(full.length, loc.end + WINDOW)
  return {
    rule,
    text: (from > 0 ? '…' : '') + full.slice(from, to) + (to < full.length ? '…' : ''),
    span_start: loc.start - from + (from > 0 ? 1 : 0),
    span_end: loc.end - from + (from > 0 ? 1 : 0),
    source_url: rule.source_url,
    retrieved_at: rule.retrieved_at ?? null,
    as_of: asOf,
  }
}

/** Audit trail: GET /audit, or the rule's own provenance from rules_internal.json offline. */
export async function getAudit(rule: RuleRecord): Promise<{ entries: AuditEntry[]; source: Mode }> {
  if (mode === 'api') {
    try {
      const raw = await api<unknown>(`/audit?team_rule_id=${encodeURIComponent(rule.team_rule_id)}`)
      const list = Array.isArray(raw) ? raw : ((raw as { entries?: unknown[] })?.entries ?? [])
      return { entries: list as AuditEntry[], source: 'api' }
    } catch (e) {
      if (!isNetworkError(e)) throw e
      setMode('offline')
    }
  }
  const entries: AuditEntry[] = []
  for (const p of rule.provenance ?? []) {
    entries.push({
      stage: 'extract',
      decision: p.cached ? 'extracted (cached LLM call)' : 'extracted',
      model: str(p.served_model) ?? str(p.model) ?? undefined,
      prompt_version: str(p.prompt_version) ?? undefined,
      reason: `candidate ${String(p.candidate_id ?? '')} from ${String(p.chunk_id ?? '')}`,
    })
  }
  if (rule.span_match) entries.push({ stage: 'verify', decision: `quote verified (${rule.span_match} match)` })
  if (rule.effective_date_method)
    entries.push({ stage: 'dates', decision: `effective date rule: ${rule.effective_date_method}` })
  for (const r of rule.review_reasons ?? []) entries.push({ stage: 'review', decision: 'needs human review', reason: r })
  return { entries, source: 'offline' }
}

// ---------- changes / eval / ingest ----------

export async function getChanges(): Promise<ChangesBundle> {
  const [stat, defaultAsOf] = await Promise.all([loadStaticChanges(), getDefaultAsOf()])
  let outputs = stat.outputs
  if (mode === 'api') {
    try {
      const raw = await api<Record<string, unknown>>('/changes')
      const picked: Record<string, ChangesBundle['outputs'][string]> = {}
      if (Array.isArray(raw.tests)) {
        // navigator/api ChangesResponse: tests = [{test_id, affected_address_ids, ..., checks, notes_list}]
        for (const t of raw.tests as Record<string, unknown>[]) {
          const id = String(t.test_id)
          picked[id] = {
            affected_address_ids: arr(t.affected_address_ids),
            conflict_flag_address_ids: arr(t.conflict_flag_address_ids),
            notes: str(t.notes) ?? '',
          }
          const prev = stat.internal[id] ?? {}
          stat.internal[id] = {
            ...prev,
            title: str(t.title) ?? prev.title,
            type: str(t.type) ?? prev.type,
            expected_behavior: str(t.expected_behavior) ?? prev.expected_behavior,
            checks: Array.isArray(t.checks) ? (t.checks as never) : prev.checks,
            notes: Array.isArray(t.notes_list) && t.notes_list.length ? arr(t.notes_list) : prev.notes,
          }
        }
      } else {
        for (const [k, v] of Object.entries(raw)) if (/^T\d+$/.test(k) && v && typeof v === 'object') picked[k] = v as never
      }
      if (Object.keys(picked).length) outputs = picked
    } catch (e) {
      if (!isNetworkError(e)) throw e
      setMode('offline')
    }
  }
  return { outputs, internal: stat.internal, tests: stat.tests, as_of: defaultAsOf }
}

export async function getEvalReport(): Promise<string | null> {
  if (mode === 'api') {
    try {
      if (!API_BASE) throw new ApiError(0, 'no api')
      const res = await fetch(API_BASE + '/eval')
      if (res.ok) {
        const ct = res.headers.get('content-type') ?? ''
        if (ct.includes('json')) {
          const j = await res.json()
          return typeof j === 'string' ? j : (j.report ?? j.text ?? JSON.stringify(j, null, 2))
        }
        if (!ct.includes('html')) return await res.text()
      }
    } catch {
      /* fall through to the bundled copy */
    }
  }
  return loadStaticEval()
}

export interface IngestSummary {
  doc_id?: string
  jurisdiction?: string
  source_url?: string
  retrieved_at?: string
  live?: boolean
  n_chunks?: number
  n_candidates?: number
  rules_new?: string[]
  rules_changed?: string[]
  rules_removed?: string[]
  rules_unchanged?: number
  rules_from_doc?: string[]
  as_of?: string
  [k: string]: unknown
}

export interface IngestEvent {
  step?: string
  index?: number
  total?: number
  status?: string
  message?: string
  reason?: string
  summary?: IngestSummary
  [k: string]: unknown
}

/**
 * POST /ingest {text, jurisdiction?, live?}; reads the application/x-ndjson progress stream:
 * {step, index, total, status: start|done|error, message} lines, then a final
 * {status: "finished", summary} or {status: "failed", step, reason}.
 */
export async function ingest(
  file: File,
  onEvent: (e: IngestEvent) => void,
  opts: { live: boolean; jurisdiction?: string | null },
) {
  if (!API_BASE || mode !== 'api') throw new ApiError(0, 'Adding a law needs the API; the app is running on bundled data.')
  const text = (await file.text()).replace(/\r\n/g, '\n')
  const body: Record<string, unknown> = { text, live: opts.live }
  if (opts.jurisdiction?.trim()) body.jurisdiction = opts.jurisdiction.trim()
  const res = await fetch(`${API_BASE}/ingest`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    let msg = `${res.status} ${res.statusText}`
    try {
      const b = await res.json()
      if (b?.detail) msg = typeof b.detail === 'string' ? b.detail : JSON.stringify(b.detail)
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, msg)
  }
  if (!res.body) {
    onEvent((await res.json()) as IngestEvent)
    return
  }
  const reader = res.body.getReader()
  const dec = new TextDecoder()
  let buf = ''
  const flush = (line: string) => {
    const t = line.replace(/^data:\s*/, '').trim()
    if (!t || t.startsWith(':') || t.startsWith('event:')) return
    try {
      onEvent(JSON.parse(t) as IngestEvent)
    } catch {
      onEvent({ message: t })
    }
  }
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buf += dec.decode(value, { stream: true })
    const lines = buf.split('\n')
    buf = lines.pop() ?? ''
    lines.forEach(flush)
  }
  if (buf) flush(buf)
}
