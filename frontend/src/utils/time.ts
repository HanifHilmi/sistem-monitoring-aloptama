// UTC-only time helpers. Periods are half-open [from, to) at minute resolution (PRD §7.3.1).

export type PeriodKind = 'day' | 'week' | 'month' | 'quarter' | 'year' | 'custom'

export interface Period {
  kind: PeriodKind
  from: Date
  to: Date
}

const MINUTE = 60_000
const DAY = 86_400_000

const pad = (n: number, w = 2) => String(n).padStart(w, '0')

export function floorMinute(d: Date): Date {
  return new Date(Math.floor(d.getTime() / MINUTE) * MINUTE)
}

export function ceilMinute(d: Date): Date {
  return new Date(Math.ceil(d.getTime() / MINUTE) * MINUTE)
}

/** 2026-11-04 06:30 UTC */
export function formatUtc(
  value: string | number | Date | null | undefined,
  opts: { seconds?: boolean } = {},
): string {
  if (value === null || value === undefined) return '—'
  const d = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(d.getTime())) return '—'
  const base = `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`
  return `${base}${opts.seconds ? `:${pad(d.getUTCSeconds())}` : ''} UTC`
}

export function formatUtcDate(d: Date): string {
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`
}

export function utcDay(y: number, m: number, d: number): Date {
  return new Date(Date.UTC(y, m, d))
}

/** The calendar-aligned period of `kind` containing `anchor` (ISO weeks start on Monday). */
export function periodContaining(kind: Exclude<PeriodKind, 'custom'>, anchor: Date): Period {
  const y = anchor.getUTCFullYear()
  const m = anchor.getUTCMonth()
  const d = anchor.getUTCDate()
  switch (kind) {
    case 'day':
      return { kind, from: utcDay(y, m, d), to: utcDay(y, m, d + 1) }
    case 'week': {
      const dow = (anchor.getUTCDay() + 6) % 7 // Monday = 0
      return { kind, from: utcDay(y, m, d - dow), to: utcDay(y, m, d - dow + 7) }
    }
    case 'month':
      return { kind, from: utcDay(y, m, 1), to: utcDay(y, m + 1, 1) }
    case 'quarter': {
      const q = Math.floor(m / 3) * 3
      return { kind, from: utcDay(y, q, 1), to: utcDay(y, q + 3, 1) }
    }
    case 'year':
      return { kind, from: utcDay(y, 0, 1), to: utcDay(y + 1, 0, 1) }
  }
}

export function shiftPeriod(p: Period, step: 1 | -1): Period {
  if (p.kind === 'custom') {
    const span = p.to.getTime() - p.from.getTime()
    return {
      kind: 'custom',
      from: new Date(p.from.getTime() + step * span),
      to: new Date(p.to.getTime() + step * span),
    }
  }
  const anchor = step === 1 ? new Date(p.to.getTime()) : new Date(p.from.getTime() - DAY)
  return periodContaining(p.kind, anchor)
}

export function isOpen(p: Period, now = new Date()): boolean {
  return p.to.getTime() > now.getTime()
}

/** URL encoding: month:2026-11-01, custom:2026-11-01T00:00Z~2026-11-04T06:30Z */
export function encodePeriod(p: Period): string {
  if (p.kind === 'custom') return `custom:${p.from.toISOString()}~${p.to.toISOString()}`
  return `${p.kind}:${formatUtcDate(p.from)}`
}

export function decodePeriod(raw: unknown, fallback: Period): Period {
  if (typeof raw !== 'string') return fallback
  const sep = raw.indexOf(':')
  const kind = sep > 0 ? raw.slice(0, sep) : ''
  const value = sep > 0 ? raw.slice(sep + 1) : ''
  if (!value) return fallback
  if (kind === 'custom') {
    const [a, b] = value.split('~')
    const from = new Date(a ?? '')
    const to = new Date(b ?? '')
    if (Number.isNaN(from.getTime()) || Number.isNaN(to.getTime()) || from >= to) return fallback
    return { kind: 'custom', from: floorMinute(from), to: floorMinute(to) }
  }
  if (!['day', 'week', 'month', 'quarter', 'year'].includes(kind)) return fallback
  const anchor = new Date(`${value}T00:00:00Z`)
  if (Number.isNaN(anchor.getTime())) return fallback
  return periodContaining(kind as Exclude<PeriodKind, 'custom'>, anchor)
}

// ---- chart windows (FR-DSH-008) -------------------------------------------------------------
export const WINDOW_PRESETS = ['1h', '3h', '6h', '12h', '24h', '3d', '7d', '31d'] as const
export type WindowPreset = (typeof WINDOW_PRESETS)[number]
export const MAX_WINDOW_MS = 31 * DAY

const PRESET_MS: Record<WindowPreset, number> = {
  '1h': 60 * MINUTE,
  '3h': 180 * MINUTE,
  '6h': 360 * MINUTE,
  '12h': 720 * MINUTE,
  '24h': DAY,
  '3d': 3 * DAY,
  '7d': 7 * DAY,
  '31d': 31 * DAY,
}

export interface ChartWindow {
  preset: WindowPreset | 'custom'
  from: Date
  to: Date
}

export function windowFromPreset(preset: WindowPreset, now = new Date()): ChartWindow {
  const to = ceilMinute(now)
  return { preset, from: new Date(to.getTime() - PRESET_MS[preset]), to }
}

export function encodeWindow(w: ChartWindow): string {
  return w.preset === 'custom' ? `custom:${w.from.toISOString()}~${w.to.toISOString()}` : w.preset
}

export function decodeWindow(raw: unknown, now = new Date()): ChartWindow {
  if (typeof raw === 'string' && (WINDOW_PRESETS as readonly string[]).includes(raw)) {
    return windowFromPreset(raw as WindowPreset, now)
  }
  if (typeof raw === 'string' && raw.startsWith('custom:')) {
    const [a, b] = raw.slice(7).split('~')
    const from = new Date(a ?? '')
    const to = new Date(b ?? '')
    if (
      !Number.isNaN(from.getTime()) &&
      !Number.isNaN(to.getTime()) &&
      from < to &&
      to.getTime() - from.getTime() <= MAX_WINDOW_MS
    ) {
      return { preset: 'custom', from: floorMinute(from), to: floorMinute(to) }
    }
  }
  return windowFromPreset('3h', now)
}

/** Value for <input type="datetime-local">, interpreted as UTC. */
export function toUtcInput(d: Date): string {
  return `${formatUtcDate(d)}T${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}`
}

export function fromUtcInput(v: string): Date | null {
  const d = new Date(`${v}:00Z`)
  return Number.isNaN(d.getTime()) ? null : d
}

// ---- board buckets -------------------------------------------------------------------------------
export type Bucket = 'day' | 'week' | 'month'

/** Column granularity of the performance board for a period. */
export function bucketFor(p: Period): Bucket {
  if (p.kind === 'year') return 'month'
  if (p.kind === 'quarter') return 'week'
  const days = (p.to.getTime() - p.from.getTime()) / DAY
  if (days <= 31) return 'day'
  if (days <= 120) return 'week'
  return 'month'
}

/** ISO date (YYYY-MM-DD) of a Date in UTC. */
export function isoDay(d: Date): string {
  return formatUtcDate(d)
}

/** ISO week number (UTC). */
export function isoWeek(d: Date): number {
  const t = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()))
  const day = (t.getUTCDay() + 6) % 7
  t.setUTCDate(t.getUTCDate() - day + 3)
  const firstThursday = new Date(Date.UTC(t.getUTCFullYear(), 0, 4))
  return (
    1 +
    Math.round(
      ((t.getTime() - firstThursday.getTime()) / DAY - 3 + ((firstThursday.getUTCDay() + 6) % 7)) / 7,
    )
  )
}

/**
 * A UTC date (YYYY-MM-DD) `months` later, on the same day or the month's last day when it has fewer days
 * (31 Jan + 1 → 28 or 29 Feb), as the server works out a calibration's next due date (FR-REG-005).
 */
export function addMonths(date: string, months: number): string {
  const [y, m, d] = date.split('-').map(Number) as [number, number, number]
  const total = m - 1 + months
  const year = y + Math.floor(total / 12)
  const month = (((total % 12) + 12) % 12) + 1
  const last = new Date(Date.UTC(year, month, 0)).getUTCDate()
  return `${String(year).padStart(4, '0')}-${String(month).padStart(2, '0')}-${String(Math.min(d, last)).padStart(2, '0')}`
}
