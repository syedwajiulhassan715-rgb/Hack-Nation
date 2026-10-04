// Offline fallback: build a LookupResult in the browser from the bundled precomputed
// files, with the same shape as GET /lookup. Pure functions, unit tested.
// Nothing here decides law: results come from lookups_internal.json (precomputed engine
// output) and, for other dates, from timeline.json transitions.
import {
  CATEGORIES,
  type CategoryBlock,
  type LookupNote,
  type LookupResult,
  type LookupResultValue,
  type LookupRow,
  type Parcel,
  type Role,
  type RuleRecord,
} from './types'
import { DISCLAIMER, QUESTIONS, STATE_NAMES } from '../copy'

export interface InternalLookupRow {
  team_rule_id: string
  result: LookupResultValue
  explanation: string
  conflict_flag: boolean
  checked?: string[]
  not_checked?: string[]
  missing_facts?: string[]
  superseded_by?: string | null
  confidence?: number | null
  confidence_reasons?: string[]
}

export interface TimelineEntry {
  date: string
  changes: Array<{ team_rule_id: string; from: string; to: string }>
}

export interface Summary {
  tenant: string | null
  owner: string | null
  /** Spanish answers (answer_tenant_es / answer_owner_es); null -> the UI shows the quote */
  tenant_es?: string | null
  owner_es?: string | null
  /** sha256 of the quoted_span the summary was written from (summaries.json source_quote_sha) */
  sha: string | null
}

export async function sha256Hex(text: string): Promise<string> {
  const buf = await globalThis.crypto.subtle.digest('SHA-256', new TextEncoder().encode(text))
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, '0')).join('')
}

/** Rule ids whose summary was written from the rule's current quote (stale summaries are ignored). */
export async function verifiedSummaryIds(
  summaries: Map<string, Summary>,
  rules: Array<Pick<RuleRecord, 'team_rule_id' | 'quoted_span'>>,
): Promise<Set<string>> {
  const ok = new Set<string>()
  await Promise.all(
    rules.map(async (r) => {
      const s = summaries.get(r.team_rule_id)
      if (!s || !s.sha || (!s.tenant && !s.owner && !s.tenant_es && !s.owner_es)) return
      if ((await sha256Hex(r.quoted_span)) === s.sha) ok.add(r.team_rule_id)
    }),
  )
  return ok
}

/** Accepts the likely shapes of summaries.json; returns rule id -> answers. */
export function normalizeSummaries(raw: unknown): Map<string, Summary> {
  const out = new Map<string, Summary>()
  if (!raw || typeof raw !== 'object') return out
  let body: unknown = raw
  if (!Array.isArray(raw) && 'summaries' in (raw as Record<string, unknown>)) {
    body = (raw as Record<string, unknown>).summaries
  }
  const take = (id: string, v: unknown) => {
    if (!v || typeof v !== 'object') return
    const o = v as Record<string, unknown>
    const pick = (...keys: string[]) => {
      for (const k of keys) {
        const val = o[k]
        if (typeof val === 'string' && val.trim()) return val
        if (val && typeof val === 'object' && typeof (val as Record<string, unknown>).en === 'string')
          return (val as Record<string, string>).en
      }
      return null
    }
    out.set(id, {
      tenant: pick('answer_tenant', 'tenant', 'answer_tenant_en'),
      owner: pick('answer_owner', 'owner', 'answer_owner_en'),
      tenant_es: pick('answer_tenant_es'),
      owner_es: pick('answer_owner_es'),
      sha: typeof o.source_quote_sha === 'string' ? o.source_quote_sha : null,
    })
  }
  if (Array.isArray(body)) {
    for (const v of body) {
      const id = (v as Record<string, unknown>)?.team_rule_id
      if (typeof id === 'string') take(id, v)
    }
  } else if (body && typeof body === 'object') {
    for (const [id, v] of Object.entries(body as Record<string, unknown>)) take(id, v)
  }
  return out
}

const NUM = /\d[\d,]*(?:\.\d+)?/g

/**
 * Golden rule 7 (same check as the API): every number in a summary must appear in the quote
 * it was written from, or the summary is not shown and the UI falls back to the quote.
 */
export function numbersGrounded(answer: string, span: string): boolean {
  const flat = span.replace(/,/g, '')
  for (const raw of answer.match(NUM) ?? []) {
    const tok = raw.replace(/[,.]+$/, '')
    if (!span.includes(tok) && !flat.includes(tok.replace(/,/g, ''))) return false
  }
  return true
}

/** The summary for a role and language, only if it passes the number guard. */
export function pickAnswer(s: Summary | undefined, role: Role, lang: 'en' | 'es', span: string): string | null {
  if (!s) return null
  const text = lang === 'es' ? (role === 'owner' ? s.owner_es : s.tenant_es) : role === 'owner' ? s.owner : s.tenant
  if (!text || !text.trim()) return null
  return numbersGrounded(text, span) ? text : null
}

/**
 * Result of one rule on `asOf`, given its precomputed result on the default date and the
 * address's timeline transitions (exact: the timeline lists every date a result changes).
 */
export function resultAt(
  baseResult: LookupResultValue,
  changes: Array<{ date: string; from: string; to: string }>,
  asOf: string,
): LookupResultValue {
  if (!changes.length) return baseResult
  const sorted = [...changes].sort((a, b) => a.date.localeCompare(b.date))
  let r: string | null = null
  for (const c of sorted) if (c.date <= asOf) r = c.to
  if (r == null) r = sorted[0].from
  return r as LookupResultValue
}

const RANK: Record<LookupResultValue, number> = {
  applies: 0,
  unknown: 2,
  not_yet_effective: 3,
  superseded: 4,
  pending: 5,
}

/** Winning rule first: applies (city before state), then unknown, starts later, superseded, proposed. */
export function sortRows(rows: LookupRow[]): LookupRow[] {
  return [...rows].sort((a, b) => {
    const ra = RANK[a.result] + (a.result === 'applies' && a.level === 'state' ? 1 : 0)
    const rb = RANK[b.result] + (b.result === 'applies' && b.level === 'state' ? 1 : 0)
    if (ra !== rb) return ra - rb
    const ca = a.confidence ?? 0
    const cb = b.confidence ?? 0
    if (ca !== cb) return cb - ca
    return a.team_rule_id.localeCompare(b.team_rule_id)
  })
}

/** A rule record shown outside any building (e.g. a newly ingested rule) in the source drawer. */
export function ruleAsRow(rule: RuleRecord): LookupRow {
  return {
    team_rule_id: rule.team_rule_id,
    result: rule.status === 'pending' ? 'pending' : rule.status === 'not_yet_effective' ? 'not_yet_effective' : 'applies',
    level: rule.level,
    title: rule.title,
    answer: null,
    explanation: '',
    key_value: rule.key_value ?? null,
    quoted_span: rule.quoted_span,
    citation: rule.citation,
    source_doc_id: rule.source_doc_id ?? null,
    source_url: rule.source_url,
    retrieved_at: rule.retrieved_at ?? null,
    effective_date: rule.effective_date ?? null,
    missing_facts: [],
    superseded_by: null,
    conflict_flag: !!rule.conflict_flag,
    conflict_note: rule.conflict_note ?? null,
    confidence: rule.confidence ?? null,
    confidence_reasons: [],
    needs_review: !!rule.needs_review,
    review_reasons: rule.review_reasons ?? [],
    checked: [],
    not_checked: ['building coverage (this rule is shown on its own, not for a building)'],
  }
}

export function cityName(jurisdiction: string | null): string | null {
  if (!jurisdiction) return null
  return jurisdiction.split(',')[0].trim()
}

export function addressLabel(p: Parcel): string {
  return `${p.street_address}, ${p.postal_city}, ${p.state}${p.zip ? ` ${p.zip}` : ''}`
}

export interface BuildInput {
  parcel: Parcel
  rows: InternalLookupRow[]
  timeline: TimelineEntry[]
  rulesById: Map<string, RuleRecord>
  summaries: Map<string, Summary>
  /** rule ids whose summary matches the current quote (see verifiedSummaryIds) */
  verifiedSummaries: Set<string>
  asOf: string
  defaultAsOf: string
  role: Role
  /** answer language; English when omitted */
  lang?: 'en' | 'es'
}

export function buildLookupResult(input: BuildInput): LookupResult {
  const { parcel, rows, timeline, rulesById, summaries, verifiedSummaries, asOf, defaultAsOf, role } = input
  const lang = input.lang ?? 'en'
  const changesByRule = new Map<string, Array<{ date: string; from: string; to: string }>>()
  for (const e of timeline) {
    for (const c of e.changes) {
      const list = changesByRule.get(c.team_rule_id) ?? []
      list.push({ date: e.date, from: c.from, to: c.to })
      changesByRule.set(c.team_rule_id, list)
    }
  }
  const derived = asOf !== defaultAsOf

  const full: LookupRow[] = []
  for (const r of rows) {
    const rule = rulesById.get(r.team_rule_id)
    if (!rule) continue // fail closed: a row without its rule record cannot be cited
    const result = derived ? resultAt(r.result, changesByRule.get(r.team_rule_id) ?? [], asOf) : r.result
    const s = verifiedSummaries.has(r.team_rule_id) ? summaries.get(r.team_rule_id) : undefined
    full.push({
      team_rule_id: r.team_rule_id,
      result,
      level: rule.level,
      title: rule.title,
      answer: pickAnswer(s, role, lang, rule.quoted_span),
      explanation: r.explanation,
      key_value: rule.key_value ?? null,
      quoted_span: rule.quoted_span,
      citation: rule.citation,
      source_doc_id: rule.source_doc_id ?? null,
      source_url: rule.source_url,
      retrieved_at: rule.retrieved_at ?? null,
      effective_date: rule.effective_date ?? null,
      missing_facts: r.missing_facts ?? [],
      superseded_by: result === 'superseded' ? (r.superseded_by ?? null) : null,
      superseded_by_citation:
        result === 'superseded' && r.superseded_by ? (rulesById.get(r.superseded_by)?.citation ?? null) : null,
      review_reasons: rule.review_reasons ?? [],
      conflict_flag: !!r.conflict_flag,
      conflict_note: rule.conflict_note ?? null,
      confidence: r.confidence ?? rule.confidence ?? null,
      confidence_reasons: r.confidence_reasons ?? [],
      needs_review: !!rule.needs_review,
      checked: r.checked ?? [],
      not_checked: r.not_checked ?? [],
      derived_for_date: derived && result !== r.result ? true : undefined,
    })
  }

  const categories: CategoryBlock[] = CATEGORIES.map((category) => ({
    category,
    question: QUESTIONS[category][role],
    rows: sortRows(full.filter((row) => rulesById.get(row.team_rule_id)?.category === category)),
    no_rule_note: null,
  }))

  const stack: LookupResult['jurisdiction_stack'] = [
    { level: 'state', jurisdiction: parcel.state, name: STATE_NAMES[parcel.state] ?? parcel.state, confirmed: true },
  ]
  if (parcel.city)
    stack.push({
      level: 'city',
      jurisdiction: parcel.city,
      name: cityName(parcel.city) ?? parcel.city,
      // medium = Census match without review reasons; only low is unconfirmed
      confirmed: (parcel.jurisdiction_confidence ?? 'high') !== 'low',
    })

  const jurisdictions = new Set(stack.map((s) => s.jurisdiction))
  const notes: LookupNote[] = []
  for (const rule of rulesById.values()) {
    if (rule.status !== 'failed' || !jurisdictions.has(rule.jurisdiction)) continue
    notes.push({
      jurisdiction: rule.jurisdiction,
      text: rule.title,
      date: rule.effective_date ?? null,
      team_rule_id: rule.team_rule_id,
      source_url: rule.source_url,
      retrieved_at: rule.retrieved_at ?? null,
    })
  }

  const missing = new Set<string>(parcel.missing_facts ?? [])
  return {
    address_id: parcel.address_id,
    address: addressLabel(parcel),
    as_of: asOf,
    disclaimer: DISCLAIMER,
    jurisdiction_stack: stack,
    facts: {
      year_built: parcel.year_built,
      units: parcel.units,
      units_min: parcel.units_min,
      units_max: parcel.units_max,
      units_source: parcel.units_source,
    },
    missing_facts: [...missing],
    categories,
    notes,
    _source: 'offline',
    _postal_city: parcel.postal_city,
    _jurisdiction_confidence: parcel.jurisdiction_confidence ?? null,
  }
}
