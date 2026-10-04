// Unit tests use synthetic placeholders (ids like r-A, text like "quoted text ..."),
// never real law text.
import { describe, expect, it } from 'vitest'
import {
  buildLookupResult,
  normalizeSummaries,
  resultAt,
  sha256Hex,
  sortRows,
  verifiedSummaryIds,
  type InternalLookupRow,
} from './fallback'
import type { LookupRow, Parcel, RuleRecord } from './types'

const rule = (id: string, over: Partial<RuleRecord> = {}): RuleRecord => ({
  team_rule_id: id,
  jurisdiction: 'XX',
  level: 'state',
  category: 'security_deposits',
  status: 'in_force',
  title: `title ${id}`,
  requirement: 'req',
  key_value: null,
  coverage_conditions: null,
  exemptions: null,
  overrides: [],
  interaction: null,
  effective_date: '2020-01-01',
  citation: `cite ${id}`,
  source_doc_id: 'D000',
  source_url: 'https://example.test/doc',
  quoted_span: `quoted text for ${id} that is long enough`,
  confidence: 0.8,
  conflict_flag: false,
  conflict_note: null,
  retrieved_at: '2026-01-01T00:00Z',
  ...over,
})

const parcel: Parcel = {
  address_id: 'A9999',
  street_address: '1 TEST ST',
  postal_city: 'Mailtown',
  state: 'XX',
  city: 'Legal City, XX',
  lat: 1,
  lng: 2,
  year_built: null,
  units: null,
  units_min: 5,
  units_max: null,
  units_source: 'use_description',
  jurisdiction_confidence: 'high',
}

const row = (id: string, result: InternalLookupRow['result'], over: Partial<InternalLookupRow> = {}): InternalLookupRow => ({
  team_rule_id: id,
  result,
  explanation: `why ${id}`,
  conflict_flag: false,
  checked: ['c'],
  not_checked: ['n'],
  missing_facts: [],
  superseded_by: null,
  confidence: 0.7,
  confidence_reasons: [],
  ...over,
})

describe('resultAt', () => {
  const changes = [{ date: '2026-01-01', from: 'not_yet_effective', to: 'applies' }]
  it('uses the base result when there are no transitions', () => {
    expect(resultAt('applies', [], '2020-01-01')).toBe('applies')
  })
  it('uses "from" before the first transition and "to" after', () => {
    expect(resultAt('applies', changes, '2025-12-31')).toBe('not_yet_effective')
    expect(resultAt('applies', changes, '2026-01-01')).toBe('applies')
    expect(resultAt('applies', changes, '2028-01-01')).toBe('applies')
  })
})

describe('buildLookupResult', () => {
  const rules = new Map([
    ['r-A', rule('r-A', { level: 'city', jurisdiction: 'Legal City, XX' })],
    ['r-B', rule('r-B')],
    ['r-C', rule('r-C', { category: 'algorithmic_rent_setting', effective_date: '2027-07-01' })],
    ['r-F', rule('r-F', { status: 'failed', category: 'rent_increase_limits' })],
    ['r-P', rule('r-P', { status: 'pending', category: 'rent_increase_limits' })],
  ])
  const base = {
    parcel,
    rows: [
      row('r-B', 'superseded', { superseded_by: 'r-A' }),
      row('r-A', 'applies'),
      row('r-C', 'not_yet_effective'),
      row('r-P', 'pending'),
      row('r-X', 'applies'), // no rule record: must be dropped (fail closed)
    ],
    timeline: [{ date: '2027-07-01', changes: [{ team_rule_id: 'r-C', from: 'not_yet_effective', to: 'applies' }] }],
    rulesById: rules,
    summaries: normalizeSummaries({
      summaries: {
        'r-A': { answer_tenant: 'tenant words', answer_owner: 'owner words', source_quote_sha: 'x' },
        'r-B': { answer_tenant: 'stale words', answer_owner: 'stale', source_quote_sha: 'y' },
      },
    }),
    verifiedSummaries: new Set(['r-A']),
    asOf: '2026-10-01',
    defaultAsOf: '2026-10-01',
    role: 'tenant' as const,
  }

  it('always returns all six categories in fixed order', () => {
    const r = buildLookupResult(base)
    expect(r.categories.map((c) => c.category)).toEqual([
      'rent_increase_limits',
      'just_cause_eviction',
      'security_deposits',
      'application_screening_fees',
      'screening_restrictions',
      'algorithmic_rent_setting',
    ])
    expect(r.categories.every((c) => c.question)).toBe(true)
  })

  it('joins rule fields from the record, never from code', () => {
    const r = buildLookupResult(base)
    const dep = r.categories.find((c) => c.category === 'security_deposits')!
    expect(dep.rows.map((x) => x.team_rule_id)).toEqual(['r-A', 'r-B']) // winner (city applies) first
    expect(dep.rows[0].citation).toBe('cite r-A')
    expect(dep.rows[0].answer).toBe('tenant words')
    expect(dep.rows[1].answer).toBeNull() // no summary -> UI shows the quote
    expect(dep.rows[1].superseded_by_citation).toBe('cite r-A')
    expect(r.categories.flatMap((c) => c.rows).some((x) => x.team_rule_id === 'r-X')).toBe(false)
  })

  it('uses owner wording in owner mode', () => {
    const r = buildLookupResult({ ...base, role: 'owner' })
    expect(r.categories.find((c) => c.category === 'security_deposits')!.rows[0].answer).toBe('owner words')
  })

  it('applies timeline transitions for other dates', () => {
    const before = buildLookupResult(base)
    const after = buildLookupResult({ ...base, asOf: '2027-07-02' })
    const alg = (x: typeof before) => x.categories.find((c) => c.category === 'algorithmic_rent_setting')!.rows[0]
    expect(alg(before).result).toBe('not_yet_effective')
    expect(alg(after).result).toBe('applies')
    expect(alg(after).derived_for_date).toBe(true)
    expect(after.as_of).toBe('2027-07-02')
  })

  it('lists failed rules as notes, never as rows', () => {
    const r = buildLookupResult(base)
    expect(r.notes.map((n) => n.team_rule_id)).toEqual(['r-F'])
    expect(r.categories.flatMap((c) => c.rows).some((x) => x.team_rule_id === 'r-F')).toBe(false)
  })

  it('builds the jurisdiction stack from the parcel and keeps the postal city separate', () => {
    const r = buildLookupResult(base)
    expect(r.jurisdiction_stack.map((j) => j.level)).toEqual(['state', 'city'])
    expect(r.jurisdiction_stack[1].name).toBe('Legal City')
    expect(r._postal_city).toBe('Mailtown')
    expect(r.disclaimer).toBe('Not legal advice.')
  })

  it('shows only the state level when the city is not resolved', () => {
    const r = buildLookupResult({ ...base, parcel: { ...parcel, city: null } })
    expect(r.jurisdiction_stack.map((j) => j.level)).toEqual(['state'])
  })
})

describe('sortRows', () => {
  it('orders applies (city before state), unknown, starts later, superseded, proposed', () => {
    const mk = (id: string, result: LookupRow['result'], level: LookupRow['level']) =>
      ({ team_rule_id: id, result, level, confidence: 0.5 }) as LookupRow
    const out = sortRows([
      mk('p', 'pending', 'state'),
      mk('s', 'superseded', 'state'),
      mk('n', 'not_yet_effective', 'state'),
      mk('u', 'unknown', 'city'),
      mk('as', 'applies', 'state'),
      mk('ac', 'applies', 'city'),
    ])
    expect(out.map((r) => r.team_rule_id)).toEqual(['ac', 'as', 'u', 'n', 's', 'p'])
  })
})

describe('verifiedSummaryIds', () => {
  it('keeps a summary only when its source_quote_sha matches sha256 of the current quote', async () => {
    const quote = 'placeholder quote text used only in this test'
    const good = await sha256Hex(quote)
    const s = normalizeSummaries({
      summaries: {
        'r-1': { answer_tenant: 't', source_quote_sha: good },
        'r-2': { answer_tenant: 't', source_quote_sha: 'deadbeef' },
        'r-3': { answer_tenant: 't' },
      },
    })
    const ok = await verifiedSummaryIds(s, [
      { team_rule_id: 'r-1', quoted_span: quote },
      { team_rule_id: 'r-2', quoted_span: quote },
      { team_rule_id: 'r-3', quoted_span: quote },
    ])
    expect([...ok]).toEqual(['r-1'])
    expect(good).toMatch(/^[0-9a-f]{64}$/)
  })
})

describe('normalizeSummaries', () => {
  it('accepts list and map shapes, and missing files', () => {
    expect(normalizeSummaries(null).size).toBe(0)
    expect(normalizeSummaries([{ team_rule_id: 'r-1', answer_tenant: 't' }]).get('r-1')?.tenant).toBe('t')
    expect(normalizeSummaries({ 'r-2': { tenant: { en: 'x' } } }).get('r-2')?.tenant).toBe('x')
  })
})
