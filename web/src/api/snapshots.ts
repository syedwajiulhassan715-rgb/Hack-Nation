// Compact snapshot format written by scripts/sync-data.mjs from outputs/snapshots.json.
// codes[date] is a string with one char per (address, category):
//   char = 'a' + resultIndex * 2 + conflictFlag
import { CATEGORIES, type Category } from './types'

export const SNAP_RESULTS = ['none', 'applies', 'unknown', 'superseded', 'not_yet_effective', 'pending'] as const
export type SnapResult = (typeof SNAP_RESULTS)[number]

export interface CompactSnapshots {
  dates: string[]
  categories: Category[]
  results: string[]
  address_ids: string[]
  codes: Record<string, string>
}

export interface SnapCell {
  result: SnapResult
  conflict: boolean
}

export function decodeChar(ch: string): SnapCell {
  const n = ch.charCodeAt(0) - 97
  const idx = Math.max(0, Math.floor(n / 2))
  return { result: SNAP_RESULTS[idx] ?? 'none', conflict: n % 2 === 1 }
}

/** The snapshot date in force on `asOf`: the latest key date on or before it. */
export function snapshotDateFor(dates: string[], asOf: string): string | null {
  if (!dates.length) return null
  const sorted = [...dates].sort()
  let pick: string | null = null
  for (const d of sorted) if (d <= asOf) pick = d
  return pick ?? sorted[0]
}

export class SnapshotIndex {
  readonly data: CompactSnapshots
  private readonly addrIndex = new Map<string, number>()
  private readonly sortedDates: string[]

  constructor(data: CompactSnapshots) {
    this.data = data
    data.address_ids.forEach((id, i) => this.addrIndex.set(id, i))
    this.sortedDates = [...data.dates].filter((d) => d in data.codes).sort()
  }

  get dates() {
    return this.sortedDates
  }

  cell(asOf: string, addressId: string, category: Category): SnapCell | null {
    const d = snapshotDateFor(this.sortedDates, asOf)
    const i = this.addrIndex.get(addressId)
    if (d == null || i == null) return null
    const catIdx = (this.data.categories ?? CATEGORIES).indexOf(category)
    if (catIdx < 0) return null
    const s = this.data.codes[d]
    return decodeChar(s[i * this.data.categories.length + catIdx])
  }

  /** Per-address cells for one date; used to recolor all beacons at once. */
  row(asOf: string, addressId: string): SnapCell[] | null {
    const d = snapshotDateFor(this.sortedDates, asOf)
    const i = this.addrIndex.get(addressId)
    if (d == null || i == null) return null
    const n = this.data.categories.length
    const s = this.data.codes[d]
    const out: SnapCell[] = []
    for (let c = 0; c < n; c++) out.push(decodeChar(s[i * n + c]))
    return out
  }
}
