import type { Locale } from '@/i18n'

const pctFormatters = new Map<Locale, Intl.NumberFormat>()
const intFormatters = new Map<Locale, Intl.NumberFormat>()

function nf(map: Map<Locale, Intl.NumberFormat>, locale: Locale, opts: Intl.NumberFormatOptions) {
  let f = map.get(locale)
  if (!f) {
    f = new Intl.NumberFormat(locale === 'id' ? 'id-ID' : 'en-GB', opts)
    map.set(locale, f)
  }
  return f
}

/** 99.72 % / 99,72 % — the API already rounded half-up to 2 decimals (FR-KPI-007). */
export function formatPct(pct: number | null | undefined, locale: Locale): string {
  if (pct === null || pct === undefined) return '—'
  return `${nf(pctFormatters, locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(pct)} %`
}

export function formatInt(n: number | null | undefined, locale: Locale): string {
  if (n === null || n === undefined) return '—'
  return nf(intFormatters, locale, { maximumFractionDigits: 0 }).format(n)
}

export function formatNumber(n: number | null | undefined, locale: Locale, digits = 1): string {
  if (n === null || n === undefined) return '—'
  return new Intl.NumberFormat(locale === 'id' ? 'id-ID' : 'en-GB', { maximumFractionDigits: digits }).format(
    n,
  )
}

export type Level = 'good' | 'warning' | 'bad' | 'none'

export function levelFor(
  pct: number | null | undefined,
  thresholds: { good: number; warning: number },
): Level {
  if (pct === null || pct === undefined) return 'none'
  if (pct >= thresholds.good) return 'good'
  if (pct >= thresholds.warning) return 'warning'
  return 'bad'
}

export const LEVEL_TEXT: Record<Level, string> = {
  good: 'text-good',
  warning: 'text-warn',
  bad: 'text-bad',
  none: 'text-muted',
}
