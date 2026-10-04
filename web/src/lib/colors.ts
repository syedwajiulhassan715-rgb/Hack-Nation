// Read design tokens from CSS so the map and the label share one palette.
import type { SnapCell } from '../api/snapshots'

const cache = new Map<string, string>()

export function token(name: string, fallback = '#888888'): string {
  if (cache.has(name)) return cache.get(name)!
  let v = ''
  if (typeof document !== 'undefined') v = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  const out = v || fallback
  cache.set(name, out)
  return out
}

export function statusColor(result: string, conflict = false): string {
  if (conflict) return token('--conflict')
  switch (result) {
    case 'applies':
      return token('--applies')
    case 'unknown':
      return token('--unknown')
    case 'superseded':
      return token('--superseded')
    case 'not_yet_effective':
      return token('--not-yet')
    case 'pending':
      return token('--pending')
    default:
      return token('--none')
  }
}

function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace('#', '')
  const n = parseInt(h.length === 3 ? h.replace(/(.)/g, '$1$1') : h.slice(0, 6), 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

/** Ink-to-accent ramp for the "All protections" view: t in [0, 1]. */
export function ramp(t: number): string {
  const a = hexToRgb('#3a4150')
  const b = hexToRgb(token('--applies', '#4F7CFF'))
  const c = a.map((x, i) => Math.round(x + (b[i] - x) * Math.min(1, Math.max(0, t))))
  return `rgb(${c[0]},${c[1]},${c[2]})`
}

/** Beacon color for one address: one category's status, or a count ramp for "all". */
export function beaconColor(cells: SnapCell[] | null, catIndex: number | 'all'): string {
  if (!cells) return token('--none')
  if (catIndex === 'all') {
    // Count ramp only; conflicts show in the single-category views (red is for conflicts).
    const n = cells.filter((c) => c.result === 'applies').length
    return ramp(n / cells.length)
  }
  const c = cells[catIndex]
  return statusColor(c?.result ?? 'none', c?.conflict)
}
