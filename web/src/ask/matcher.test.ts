// Ask Locus matcher tests. Synthetic placeholders only (ids like r-A, "quoted text ..."),
// never real law text.
import { describe, expect, it } from 'vitest'
import { ask, matchIntent, quoteExcerpt, suggest } from './matcher'
import type { Category, CategoryBlock, LookupResult, LookupRow } from '../api/types'

const row = (id: string, over: Partial<LookupRow> = {}): LookupRow => ({
  team_rule_id: id,
  result: 'applies',
  level: 'state',
  title: `title ${id}`,
  answer: null,
  explanation: 'placeholder explanation',
  key_value: null,
  quoted_span: `quoted text for ${id} that is long enough to be a span`,
  citation: `cite ${id}`,
  source_doc_id: 'D000',
  source_url: 'https://example.test/doc',
  retrieved_at: '2026-01-01T00:00Z',
  effective_date: '2020-01-01',
  missing_facts: [],
  superseded_by: null,
  conflict_flag: false,
  conflict_note: null,
  confidence: 0.9,
  confidence_reasons: [],
  needs_review: false,
  checked: [],
  not_checked: [],
  ...over,
})

const block = (category: Category, rows: LookupRow[]): CategoryBlock => ({
  category,
  question: null,
  rows,
  no_rule_note: null,
})

const lookup = (categories: CategoryBlock[]): LookupResult => ({
  address_id: 'A-1',
  address: '1 Placeholder St',
  as_of: '2026-10-01',
  disclaimer: 'Not legal advice.',
  jurisdiction_stack: [
    { level: 'state', jurisdiction: 'XX', name: 'Statename' },
    { level: 'city', jurisdiction: 'XX-city', name: 'Cityname', confirmed: true },
  ],
  facts: {},
  missing_facts: [],
  categories,
  notes: [],
})

const LONG = 'word '.repeat(80) + 'end of the quoted span'

const L = lookup([
  block('security_deposits', [
    row('r-pen', { title: 'Penalty for withholding the deposit' }),
    row('r-max', { title: 'Maximum deposit amount', level: 'state', quoted_span: LONG }),
    row('r-pend', { result: 'pending', title: 'Proposed deposit change', effective_date: null }),
  ]),
  block('rent_increase_limits', [
    row('r-rent', { level: 'city', answer: 'plain answer A' }),
    row('r-unk', { result: 'unknown', missing_facts: ['year_built', 'owner_type', 'mystery_fact'] }),
    row('r-later', { result: 'not_yet_effective', effective_date: '2030-01-01' }),
  ]),
  block('just_cause_eviction', [row('r-evict', { conflict_flag: true, conflict_note: 'sources differ' })]),
  block('screening_restrictions', []),
])

describe('intent matching', () => {
  it('matches categories in English', () => {
    expect(matchIntent('How much can the deposit be?')).toMatchObject({ kind: 'category', category: 'security_deposits' })
    expect(matchIntent('Can my landlord evict me?').category).toBe('just_cause_eviction')
    expect(matchIntent('Is there a cap on rent increases?').category).toBe('rent_increase_limits')
    expect(matchIntent('Can they run a background check?').category).toBe('screening_restrictions')
    expect(matchIntent('What is the application fee?').category).toBe('application_screening_fees')
    expect(matchIntent('Is RealPage pricing software allowed?').category).toBe('algorithmic_rent_setting')
  })

  it('matches categories in Spanish', () => {
    expect(matchIntent('¿Cuánto puede ser la fianza?').category).toBe('security_deposits')
    expect(matchIntent('¿Me pueden desalojar?').category).toBe('just_cause_eviction')
    expect(matchIntent('¿Cuánto me pueden subir el alquiler?').category).toBe('rent_increase_limits')
    expect(matchIntent('¿Pueden revisar mis antecedentes penales?').category).toBe('screening_restrictions')
  })

  it('is accent- and case-insensitive', () => {
    const a = matchIntent('¿DEPÓSITO?')
    const b = matchIntent('deposito')
    expect(a.category).toBe('security_deposits')
    expect(b.category).toBe('security_deposits')
    expect(a.matched).toEqual(['depósito'])
  })

  it('recognises the other intents', () => {
    expect(matchIntent('Why are some answers unknown?').kind).toBe('why_unknown')
    expect(matchIntent('What changes next year?').kind).toBe('upcoming')
    expect(matchIntent('anything in 2031?').kind).toBe('upcoming')
    expect(matchIntent('Which city is this in?').kind).toBe('jurisdiction')
    expect(matchIntent('Do any laws disagree?').kind).toBe('conflict')
    expect(matchIntent('Give me a summary').kind).toBe('overview')
    expect(matchIntent('¿Por qué es desconocido?').kind).toBe('why_unknown')
  })

  it('narrows a non-category intent by a named category', () => {
    expect(matchIntent('why is the deposit unknown?')).toMatchObject({ kind: 'why_unknown', category: 'security_deposits' })
  })

  it('prefers the category on a tie', () => {
    expect(matchIntent('why can my rent go up?').kind).toBe('category')
  })
})

describe('ask', () => {
  it('fails closed with zero citations when nothing matches', () => {
    const a = ask({ question: 'What is the weather on Mars?', lookup: L, role: 'tenant', lang: 'en' })
    expect(a.intent.kind).toBe('no_match')
    expect(a.citations).toEqual([])
    expect(a.lead).toMatch(/^I can only answer from the laws Locus has/)
    expect(a.followUps.length).toBeGreaterThanOrEqual(4)
    const es = ask({ question: 'xyz', lookup: L, role: 'tenant', lang: 'es' })
    expect(es.citations).toEqual([])
    expect(es.lead).toMatch(/^Solo puedo responder/)
    expect(a.asOf).toBe('2026-10-01')
  })

  it('ranks a keyword-overlapping title first and excludes pending rows', () => {
    const a = ask({ question: 'How much can the deposit be?', lookup: L, role: 'tenant', lang: 'en' })
    expect(a.intent.category).toBe('security_deposits')
    expect(a.citations[0].row.team_rule_id).toBe('r-max')
    expect(a.citations.map((c) => c.row.team_rule_id)).not.toContain('r-pend')
    expect(a.lead).toContain('Cityname')
    expect(a.lead).toContain('cite r-max')
    expect(a.followUps.length).toBeGreaterThanOrEqual(2)
    expect(a.followUps.length).toBeLessThanOrEqual(3)
  })

  it('quotes are verbatim substrings of quoted_span', () => {
    const a = ask({ question: 'deposit maximum', lookup: L, role: 'owner', lang: 'en' })
    for (const c of a.citations) {
      const q = c.quote.endsWith('…') ? c.quote.slice(0, -1) : c.quote
      expect(c.row.quoted_span).toContain(q)
      expect(c.quote.length).toBeLessThanOrEqual(221)
    }
    expect(a.citations[0].quote.endsWith('…')).toBe(true)
    expect(quoteExcerpt('short quote')).toBe('short quote')
  })

  it('copies the plain-language answer, else null', () => {
    const a = ask({ question: 'can my rent go up', lookup: L, role: 'tenant', lang: 'en' })
    expect(a.citations[0].row.team_rule_id).toBe('r-rent') // applies, then city
    expect(a.citations[0].answer).toBe('plain answer A')
    expect(a.citations.find((c) => c.row.team_rule_id === 'r-unk')?.answer).toBeNull()
  })

  it('why_unknown lists the missing facts with labels', () => {
    const en = ask({ question: 'Why is this unknown?', lookup: L, role: 'tenant', lang: 'en' })
    expect(en.intent.kind).toBe('why_unknown')
    expect(en.missingFacts).toEqual(['year built', 'owner type', 'mystery fact'])
    expect(en.citations.map((c) => c.row.team_rule_id)).toEqual(['r-unk'])
    const es = ask({ question: '¿Qué datos faltan?', lookup: L, role: 'tenant', lang: 'es' })
    expect(es.missingFacts).toContain('año de construcción')
  })

  it('conflict intent shows flagged rows and never picks a winner', () => {
    const a = ask({ question: 'Do any rules conflict?', lookup: L, role: 'tenant', lang: 'en' })
    expect(a.intent.kind).toBe('conflict')
    expect(a.citations.map((c) => c.row.team_rule_id)).toEqual(['r-evict'])
    expect(a.lead).toMatch(/human reviewer should decide/)
  })

  it('upcoming lists not-yet-effective and pending rows with the date copied', () => {
    const a = ask({ question: 'What changes soon?', lookup: L, role: 'tenant', lang: 'en' })
    expect(a.intent.kind).toBe('upcoming')
    const ids = a.citations.map((c) => c.row.team_rule_id)
    expect(ids).toEqual(['r-later', 'r-pend'])
    expect(a.lead).toContain('2030-01-01')
  })

  it('jurisdiction names the state and city with counts per level', () => {
    const a = ask({ question: 'Which city is this?', lookup: L, role: 'tenant', lang: 'en' })
    expect(a.lead).toContain('Cityname, Statename')
    expect(a.lead).toContain('5 state rules and 1 city rule')
  })

  it('overview cites one row per category that has rows', () => {
    const a = ask({ question: 'summary please', lookup: L, role: 'tenant', lang: 'es' })
    expect(a.intent.kind).toBe('overview')
    expect(a.citations.length).toBe(3)
  })

  it('says when a category has no rows, with zero citations', () => {
    const a = ask({ question: 'background check?', lookup: L, role: 'tenant', lang: 'en' })
    expect(a.intent.category).toBe('screening_restrictions')
    expect(a.citations).toEqual([])
  })
})

describe('suggest', () => {
  it('builds chips from what the building has', () => {
    const s = suggest(L, 'tenant', 'en')
    expect(s.length).toBeGreaterThanOrEqual(4)
    expect(s.length).toBeLessThanOrEqual(6)
    expect(s).toContain('Why are some answers unknown?')
    expect(s).toContain('What changes soon?')
    // every chip routes to something other than no_match
    for (const q of s) expect(matchIntent(q).kind).not.toBe('no_match')
  })

  it('omits unknown and upcoming chips when the building has none, and speaks Spanish', () => {
    const plain = lookup([block('security_deposits', [row('r-1')])])
    const s = suggest(plain, 'owner', 'es')
    expect(s.some((q) => /desconocid/.test(q))).toBe(false)
    expect(s.some((q) => /cambia/.test(q))).toBe(false)
    expect(s).toContain('¿Qué reglas aplican al depósito de garantía que cobro?')
    for (const q of s) expect(matchIntent(q).kind).not.toBe('no_match')
  })
})
