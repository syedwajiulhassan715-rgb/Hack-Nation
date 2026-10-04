// Presentation helpers for lookup rows. They only read fields; they never decide law.
import type { Category, CategoryBlock, LookupResult, LookupRow } from '../api/types'

export const LOW_CONFIDENCE = 0.6

export function isLowConfidence(row: LookupRow): boolean {
  return row.needs_review || (row.confidence != null && row.confidence < LOW_CONFIDENCE)
}

/** The engine notes in confidence reasons when a coverage fact was derived from year built. */
export function derivedFromYearBuilt(row: LookupRow): boolean {
  return row.confidence_reasons.some((r) => /year built/i.test(r))
}

/** The quoted sentence reads as an exemption ("... are exempt", "shall not apply"). Wording check only. */
const EXEMPTION_QUOTE = /\bexempt(?:ed|ion|ions|s)?\b|\b(?:does|do|shall|will) not apply\b/i

export type AnswerKind = 'answer' | 'quote' | 'explanation'

/**
 * Headline text for a row:
 * - `answer`: the plain-language summary;
 * - `explanation`: the engine's deterministic explanation, used when the row applies, has no summary
 *   and its quote reads as an exemption (showing that sentence alone would read as "exempt");
 *   the quote stays in the row detail;
 * - `quote`: otherwise the start of the quote.
 */
export function answerText(row: LookupRow, max = 180): { text: string; isQuote: boolean; kind: AnswerKind } {
  if (row.answer) return { text: row.answer, isQuote: false, kind: 'answer' }
  const q = row.quoted_span.replace(/\s+/g, ' ').trim()
  const expl = (row.explanation ?? '').replace(/\s+/g, ' ').trim()
  if (row.result === 'applies' && expl && EXEMPTION_QUOTE.test(q))
    return { text: expl, isQuote: false, kind: 'explanation' }
  return { text: q.length > max ? `${q.slice(0, max).trimEnd()}…` : q, isQuote: true, kind: 'quote' }
}

export interface CategoryView {
  block: CategoryBlock
  winner: LookupRow | null
  others: LookupRow[]
  superseded: LookupRow[]
}

/**
 * UI vocabulary for what each category's headline question asks. It only ranks rows for display
 * (which one is shown first); it never changes a result or hides a row. Plain words, no law:
 * no citations, thresholds, amounts or dates.
 * - strong / weak: words that signal the row answers the question (strong counts double, a title
 *   match counts three times a match in the key value or answer);
 * - demote: words in a title that signal a side rule (penalties, notices, transfers, ...).
 */
const HEADLINE_WORDS: Record<Category, { strong: string[]; weak: string[]; demote: string[] }> = {
  rent_increase_limits: {
    strong: ['rent control', 'rent stabilization', 'cap', 'maximum', 'allowable', 'annual', 'general adjustment', 'percent', 'consumer price', 'cpi'],
    weak: ['limit', 'increase', 'increases'],
    demote: ['notice', 'condominium', 'conversion', 'capital improvement', 'additional occupant', 'utilities', 'petition', 'petitions', 'exemption'],
  },
  just_cause_eviction: {
    strong: ['just cause', 'good cause', 'without cause', 'reason', 'reasons'],
    weak: ['evict', 'eviction', 'evictions', 'terminate', 'termination'],
    demote: ['notice', 'relocation', 'foreclosure', 'public housing', 'rooming', 'after eviction', 'penalty'],
  },
  security_deposits: {
    strong: ['maximum', 'cap', 'limit', 'exceed', "month's rent", "months' rent", 'return'],
    weak: ['amount', 'deposit', 'within'],
    demote: ['penalty', 'interest', 'notice', 'transfer', 'sale', 'successor', 'damages', 'photograph', 'photographs', 'inspection', 'records', 'receipt', 'pet', 'displacement', 'service members'],
  },
  application_screening_fees: {
    strong: ['maximum', 'cap', 'limit', 'exceed', 'screening fee', 'application fee'],
    weak: ['fee', 'fees', 'charge'],
    demote: ['receipt', 'credit report', 'refund', 'broker', 'notification', 'existing tenancies'],
  },
  screening_restrictions: {
    strong: ['criminal', 'fair chance', 'source of income', 'credit', 'inquiry', 'inquiries', 'screening', 'tenant selection'],
    weak: ['income', 'applicant', 'applicants', 'application'],
    demote: ['advertisements', 'posting', 'notice', 'withdrawal', 'copy of'],
  },
  algorithmic_rent_setting: {
    strong: ['algorithm', 'algorithmic', 'pricing', 'software', 'rent-setting'],
    weak: ['set rents', 'rents'],
    demote: ['coercion'],
  },
}

// Curly apostrophes and the replacement character (seen in extracted text) read as a plain apostrophe.
const norm = (s: string | null | undefined) => (s ?? '').toLowerCase().replace(/[\u2018\u2019\u02bc\ufffd`]/g, "'")
const escapeRe = (w: string) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
const hasWord = (text: string, w: string) => new RegExp(`(^|[^a-z0-9])${escapeRe(w)}($|[^a-z0-9])`).test(text)

/** How well a row's own wording (title, key value, answer) matches its category's headline question. */
export function headlineScore(row: LookupRow, category: Category): number {
  const words = HEADLINE_WORDS[category]
  if (!words) return 0
  const title = norm(row.title)
  const body = `${norm(row.key_value)} ${norm(row.answer)}`
  let score = 0
  const add = (list: string[], weight: number) => {
    for (const w of list) score += hasWord(title, w) ? 3 * weight : hasWord(body, w) ? weight : 0
  }
  add(words.strong, 2)
  add(words.weak, 1)
  if (words.demote.some((w) => hasWord(title, w))) score -= 8
  return score
}

const TIER: Partial<Record<LookupRow['result'], number>> = { applies: 0, unknown: 1, not_yet_effective: 2 }

/** Order used to pick the headline: result tier, relevance, has key value and answer, city before state, id. */
function headlineCompare(category: Category) {
  return (a: LookupRow, b: LookupRow): number => {
    const ta = TIER[a.result] ?? 9
    const tb = TIER[b.result] ?? 9
    if (ta !== tb) return ta - tb
    const sa = headlineScore(a, category)
    const sb = headlineScore(b, category)
    if (sa !== sb) return sb - sa
    const ca = (a.key_value ? 1 : 0) + (a.answer ? 1 : 0)
    const cb = (b.key_value ? 1 : 0) + (b.answer ? 1 : 0)
    if (ca !== cb) return cb - ca
    if (a.level !== b.level) return a.level === 'city' ? -1 : 1
    return a.team_rule_id.localeCompare(b.team_rule_id)
  }
}

/**
 * Split a category into the headline row, superseded rows and the rest. Pending rows go to "Proposed".
 * The headline is a display choice among rows with the best result; every other row stays listed.
 */
export function categoryView(block: CategoryBlock, level: 'state' | 'city' | null): CategoryView {
  const rows = block.rows.filter((r) => r.result !== 'pending' && (!level || r.level === level))
  const superseded = rows.filter((r) => r.result === 'superseded')
  const rest = rows.filter((r) => r.result !== 'superseded')
  const best = rest.length ? [...rest].sort(headlineCompare(block.category))[0] : null
  const winner = best ?? superseded[0] ?? null
  return {
    block,
    winner,
    others: rest.filter((r) => r !== winner),
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
