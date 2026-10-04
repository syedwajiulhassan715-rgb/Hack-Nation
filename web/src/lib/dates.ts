// Date helpers. Dates are ISO strings (YYYY, YYYY-MM or YYYY-MM-DD) and handled in UTC.

const DAY = 86_400_000

/** Partial dates resolve to their first day (YYYY -> YYYY-01-01). Returns null if unparseable. */
export function toTime(d: string | null | undefined): number | null {
  if (!d) return null
  const m = /^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?/.exec(d)
  if (!m) return null
  return Date.UTC(Number(m[1]), m[2] ? Number(m[2]) - 1 : 0, m[3] ? Number(m[3]) : 1)
}

export function toIso(t: number): string {
  return new Date(t).toISOString().slice(0, 10)
}

export function addDays(iso: string, n: number): string {
  return toIso((toTime(iso) ?? 0) + n * DAY)
}

/** Whole days from `from` to `to` (positive when `to` is later). */
export function daysBetween(from: string, to: string): number | null {
  const a = toTime(from)
  const b = toTime(to)
  if (a == null || b == null) return null
  return Math.round((b - a) / DAY)
}

/** "Starts in 271 days" countdown, computed in the client from effective_date and as_of. */
export function countdown(asOf: string, effective: string | null): string | null {
  const n = effective ? daysBetween(asOf, effective) : null
  if (n == null) return null
  if (n <= 0) return 'Starts on its effective date'
  return n === 1 ? 'Starts in 1 day' : `Starts in ${n.toLocaleString('en-US')} days`
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** "Oct 1, 2026" for full dates; partial dates are shown as written. */
export function prettyDate(d: string | null | undefined): string {
  if (!d) return 'date not stated'
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(d)
  if (!m) return d
  return `${MONTHS[Number(m[2]) - 1]} ${Number(m[3])}, ${m[1]}`
}

export function dayIndex(min: string, d: string): number {
  return daysBetween(min, d) ?? 0
}

export function todayIso(): string {
  return new Date().toISOString().slice(0, 10)
}

const SNAP_DAYS = 10

/** Slider snapping: move to a key date when within 10 days of it. */
export function snapToTick(d: string, ticks: string[]): string {
  let best = d
  let bestN = SNAP_DAYS + 1
  for (const t of ticks) {
    const n = Math.abs(dayIndex(t, d))
    if (n <= SNAP_DAYS && n < bestN) {
      best = t
      bestN = n
    }
  }
  return best
}

