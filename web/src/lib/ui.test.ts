import { describe, expect, it } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import { countdown, daysBetween, prettyDate, snapToTick } from './dates'
import { changeKind, testCategory } from './changes'
import { answerText, categoryView } from './rows'
import type { CategoryBlock, LookupRow } from '../api/types'

describe('dates', () => {
  it('computes the countdown in the client', () => {
    expect(daysBetween('2026-10-01', '2027-07-01')).toBe(273)
    expect(countdown('2026-10-01', '2027-07-01')).toBe('Starts in 273 days')
    expect(countdown('2026-10-01', null)).toBeNull()
    expect(prettyDate('2026-10-01')).toBe('Oct 1, 2026')
    expect(prettyDate(null)).toBe('date not stated')
  })
})

describe('slider', () => {
  it('snaps to a tick within 10 days only', () => {
    const ticks = ['2026-01-01', '2027-07-01']
    expect(snapToTick('2026-01-08', ticks)).toBe('2026-01-01')
    expect(snapToTick('2026-01-20', ticks)).toBe('2026-01-20')
  })
})

describe('changes grouping', () => {
  it('separates enacted, not yet effective, pending and failed from the test fields', () => {
    expect(changeKind({ type: 'as_of', as_of_after: '2026-01-02' }, '2026-10-01')).toBe('enacted')
    expect(changeKind({ type: 'as_of', as_of_after: '2027-07-02' }, '2026-10-01')).toBe('not_yet_effective')
    expect(changeKind({ type: 'pending' }, '2026-10-01')).toBe('pending')
    expect(changeKind({ type: 'negative' }, '2026-10-01')).toBe('failed')
    expect(changeKind({ type: 'boundary' }, '2026-10-01')).toBe('enacted')
    expect(testCategory({ rule_ids: ['XX-ALG-01'] })).toBe('algorithmic_rent_setting')
    expect(testCategory({ rule_ids: ['XX-RENT-P1'] })).toBe('rent_increase_limits')
  })
})

describe('rows', () => {
  const r = (over: Partial<LookupRow>): LookupRow =>
    ({
      team_rule_id: 'r-1',
      result: 'applies',
      level: 'state',
      answer: null,
      quoted_span: 'placeholder quote '.repeat(20),
      missing_facts: [],
      confidence_reasons: [],
      ...over,
    }) as LookupRow

  it('shows the quote when answer is null', () => {
    const a = answerText(r({}), 40)
    expect(a.isQuote).toBe(true)
    expect(a.text.endsWith('…')).toBe(true)
    expect(answerText(r({ answer: 'plain' })).text).toBe('plain')
  })

  it('moves pending rows out and keeps superseded rows under the winner', () => {
    const block: CategoryBlock = {
      category: 'rent_increase_limits',
      question: 'q',
      no_rule_note: null,
      rows: [
        r({ team_rule_id: 'w', level: 'city' }),
        r({ team_rule_id: 's', result: 'superseded' }),
        r({ team_rule_id: 'p', result: 'pending' }),
      ],
    }
    const v = categoryView(block, null)
    expect(v.winner?.team_rule_id).toBe('w')
    expect(v.superseded.map((x) => x.team_rule_id)).toEqual(['s'])
    expect(v.others).toEqual([])
    expect(categoryView(block, 'state').winner?.team_rule_id).toBe('s')
  })
})

describe('no hand-written law in web/src (acceptance check)', () => {
  it('has no statute citation patterns', () => {
    // Same pattern as the CLAUDE.md grep, escaped so this file does not match itself.
    const pattern = new RegExp([String.fromCharCode(0xa7),'Civ\\. Code', 'G\\.L\\.', 'N\\.J\\.S\\.A', 'Admin\\. Code', 'P\\.L\\.'].join('|'))
    const hits: string[] = []
    const walk = (dir: string) => {
      for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
        const p = path.join(dir, e.name)
        if (e.isDirectory()) walk(p)
        else if (pattern.test(fs.readFileSync(p, 'utf8'))) hits.push(p)
      }
    }
    walk(path.resolve(__dirname, '..'))
    expect(hits).toEqual([])
  })
})
