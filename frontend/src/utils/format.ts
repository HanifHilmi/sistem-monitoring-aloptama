import type { Locale } from '@/i18n'
import type { MatrixRow } from '@/api/types'

const cache = new Map<string, Intl.NumberFormat>()
function nf(locale: Locale, opts: Intl.NumberFormatOptions): Intl.NumberFormat {
  const key = `${locale}:${JSON.stringify(opts)}`
  let f = cache.get(key)
  if (!f) {
    f = new Intl.NumberFormat(locale === 'id' ? 'id-ID' : 'en-GB', opts)
    cache.set(key, f)
  }
  return f
}

/** 99.72 (the API already rounded half-up to 2 decimals, FR-KPI-007). */
export function pct(v: number | null | undefined, locale: Locale): string {
  if (v === null || v === undefined) return '—'
  return nf(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(v)
}

export function int(v: number | null | undefined, locale: Locale): string {
  if (v === null || v === undefined) return '—'
  return nf(locale, { maximumFractionDigits: 0 }).format(v)
}

export function num(v: number | null | undefined, locale: Locale, digits = 1, fixed = false): string {
  if (v === null || v === undefined) return '—'
  return nf(locale, { minimumFractionDigits: fixed ? digits : 0, maximumFractionDigits: digits }).format(v)
}

/** Signed difference in percentage points, e.g. +0.12 / −0.48. */
export function delta(v: number | null | undefined, locale: Locale): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  const s = nf(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Math.abs(v))
  return `${v > 0 ? '+' : v < 0 ? '−' : '±'}${s}`
}

export type Level = 'full' | 'good' | 'warn' | 'bad' | 'none'

export interface Thresholds {
  good: number
  warning: number
}

/** Display level of an availability (thresholds are display settings, not targets: decision B7). */
export function level(p: number | null | undefined, t: Thresholds): Level {
  if (p === null || p === undefined) return 'none'
  if (p >= 100) return 'full'
  if (p >= t.good) return 'good'
  if (p >= t.warning) return 'warn'
  return 'bad'
}

/** An availability figure as the API sends it. OLA (a mean of the sites) comes without counts. */
export interface Figure {
  pct: number | null
  valid?: number
  expected?: number
  missing?: number
}

/** Minutes a figure lost: `missing`, else expected − valid; 0 when the API sent no counts. */
export function lostMinutes(f: Figure): number {
  const n = f.missing ?? (f.expected !== undefined && f.valid !== undefined ? f.expected - f.valid : 0)
  return Math.max(0, n)
}

/**
 * Display level of a figure. 'full' means no minute lost, so a figure that lost minutes is at most 'good' even
 * when it rounds to 100.00 (half-up to 2 decimals, FR-KPI-007). Pass `lost` for a figure without counts (OLA).
 */
export function figureLevel(
  f: Figure | null | undefined,
  t: Thresholds,
  lost = f ? lostMinutes(f) : 0,
): Level {
  if (!f || f.expected === 0) return 'none'
  const l = level(f.pct, t)
  return l === 'full' && lost > 0 ? 'good' : l
}

/** Minutes lost by a matrix row in column `col` ('total' for the whole period). OLA counts its sites' losses. */
export function matrixLost(rows: MatrixRow[], r: MatrixRow, col: number | 'total'): number {
  const lostIn = (x: MatrixRow) => {
    const c = col === 'total' ? x.total : x.cells[col]
    return c ? lostMinutes(c) : 0
  }
  if (r.kind !== 'ola') return lostIn(r)
  return rows.filter((x) => x.kind === 'site').reduce((n, x) => n + lostIn(x), 0)
}

export const LEVEL_BG: Record<Level, string> = {
  full: 'bg-full',
  good: 'bg-good',
  warn: 'bg-warn',
  bad: 'bg-bad',
  none: 'bg-empty',
}

/** Text colour readable on top of LEVEL_BG in both themes. */
export const LEVEL_ON: Record<Level, string> = {
  full: 'text-bg',
  good: 'text-ink',
  warn: 'text-[#1d1500]',
  bad: 'text-white',
  none: 'text-ink-3',
}

export const LEVEL_TEXT: Record<Level, string> = {
  full: 'text-ink',
  good: 'text-ink',
  warn: 'text-warn',
  bad: 'text-bad',
  none: 'text-ink-3',
}
