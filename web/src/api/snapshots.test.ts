import { describe, expect, it } from 'vitest'
import { decodeChar, snapshotDateFor, SnapshotIndex } from './snapshots'
import { CATEGORIES } from './types'

const enc = (idx: number, conflict = false) => String.fromCharCode(97 + idx * 2 + (conflict ? 1 : 0))

describe('snapshots', () => {
  it('decodes result and conflict', () => {
    expect(decodeChar(enc(0))).toEqual({ result: 'none', conflict: false })
    expect(decodeChar(enc(1, true))).toEqual({ result: 'applies', conflict: true })
    expect(decodeChar(enc(4))).toEqual({ result: 'not_yet_effective', conflict: false })
  })

  it('picks the latest key date on or before as_of', () => {
    const d = ['2026-01-01', '2024-01-01', '2027-07-01']
    expect(snapshotDateFor(d, '2025-06-01')).toBe('2024-01-01')
    expect(snapshotDateFor(d, '2027-07-01')).toBe('2027-07-01')
    expect(snapshotDateFor(d, '2020-01-01')).toBe('2024-01-01')
  })

  it('indexes cells by address and category', () => {
    const a1 = [enc(1), enc(2), enc(0), enc(0), enc(0), enc(4)].join('')
    const a2 = [enc(0), enc(0), enc(0), enc(0), enc(0), enc(1, true)].join('')
    const a1later = [enc(1), enc(2), enc(0), enc(0), enc(0), enc(1)].join('')
    const idx = new SnapshotIndex({
      dates: ['2026-10-01', '2027-07-01'],
      categories: [...CATEGORIES],
      results: [],
      address_ids: ['A1', 'A2'],
      codes: { '2026-10-01': a1 + a2, '2027-07-01': a1later + a2 },
    })
    expect(idx.cell('2026-12-01', 'A1', 'algorithmic_rent_setting')?.result).toBe('not_yet_effective')
    expect(idx.cell('2027-08-01', 'A1', 'algorithmic_rent_setting')?.result).toBe('applies')
    expect(idx.cell('2027-08-01', 'A2', 'algorithmic_rent_setting')).toEqual({ result: 'applies', conflict: true })
    expect(idx.row('2026-10-01', 'A1')?.map((c) => c.result)).toEqual([
      'applies',
      'unknown',
      'none',
      'none',
      'none',
      'not_yet_effective',
    ])
    expect(idx.cell('2026-10-01', 'A404', 'security_deposits')).toBeNull()
  })
})
