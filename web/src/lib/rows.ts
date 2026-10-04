// Presentation helpers for lookup rows. They only read fields; they never decide law.
import type { CategoryBlock, LookupResult, LookupRow } from '../api/types'

export const LOW_CONFIDENCE = 0.6

export function isLowConfidence(row: LookupRow): boolean {
  return row.needs_review || (row.confidence != null && row.confidence < LOW_CONFIDENCE)
}

/** The engine notes in confidence reasons when a coverage fact was derived from year built. */
export function derivedFromYearBuilt(row: LookupRow): boolean {
  return row.confidence_reasons.some((r) => /year built/i.test(r))
}

/** Answer text: the plain-language `answer`, or the start of the quote when it is null. */
export function answerText(row: LookupRow, max = 180): { text: string; isQuote: boolean } {
  if (row.answer) return { text: row.answer, isQuote: false }
  const q = row.quoted_span.replace(/\s+/g, ' ').trim()
  return { text: q.length > max ? `${q.slice(0, max).trimEnd()}…` : q, isQuote: true }
}

export interface CategoryView {
  block: CategoryBlock
  winner: LookupRow | null
  others: LookupRow[]
  superseded: LookupRow[]
}

/** Split a category into the winning row, superseded rows and the rest. Pending rows go to "Proposed". */
export function categoryView(block: CategoryBlock, level: 'state' | 'city' | null): CategoryView {
  const rows = block.rows.filter((r) => r.result !== 'pending' && (!level || r.level === level))
  const superseded = rows.filter((r) => r.result === 'superseded')
  const rest = rows.filter((r) => r.result !== 'superseded')
  const winner = rest[0] ?? superseded[0] ?? null
  return {
    block,
    winner,
    others: rest.slice(1),
    superseded: winner && winner.result === 'superseded' ? superseded.slice(1) : superseded,
  }
}

export function pendingRows(lookup: LookupResult, level: 'state' | 'city' | null): Array<LookupRow & { category: string }> {
  const out: Array<LookupRow & { category: string }> = []
  for (const b of lookup.categories)
    for (const r of b.rows) if (r.result === 'pending' && (!level || r.level === level)) out.push({ ...r, category: b.category })
  return out
}

export function levelCounts(lookup: LookupResult): Record<'state' | 'city', number> {
  const c = { state: 0, city: 0 }
  for (const b of lookup.categories) for (const r of b.rows) if (r.result !== 'pending') c[r.level] += 1
  return c
}

/** Unique dates on which this building's results change (from the API timeline or row dates). */
export function rowDates(lookup: LookupResult | null): string[] {
  if (!lookup) return []
  const s = new Set<string>()
  for (const b of lookup.categories)
    for (const r of b.rows) if (r.effective_date && /^\d{4}-\d{2}-\d{2}$/.test(r.effective_date)) s.add(r.effective_date)
  return [...s].sort()
}
