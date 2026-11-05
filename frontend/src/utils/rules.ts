// Shared wording for validity rules and detections (R2.4): "Range 15–40 °C", "Stuck ≥ 180 min",
// "Spike > 3 °C per minute", and what a detection saw.
import type { Evidence, RuleParams, RuleType } from '@/api/types'
import type { Locale } from '@/i18n'
import { num } from './format'
import { formatDuration } from './flags'

type T = (key: string, values?: Record<string, unknown>) => string

/** Digits for a field's values: one decimal for temperatures, pressure and rain, none otherwise. */
const DIGITS: Record<string, number> = { '°C': 1, hPa: 1, mm: 1 }
export function value(v: number | null | undefined, unit: string | null, lc: Locale): string {
  if (v === null || v === undefined) return '—'
  const digits = Number.isInteger(v) ? 0 : (DIGITS[unit ?? ''] ?? 1)
  const n = num(v, lc, digits)
  if (!unit) return n
  return /^\d/.test(unit)
    ? `${n} ×${unit}`
    : unit === '%' || unit === '°'
      ? `${n}${unit === '%' ? ' %' : '°'}`
      : `${n} ${unit}`
}

/** "15–40 °C", "≥ 180 min", "> 3 °C" with the rule's parameters. */
export function ruleText(type: RuleType, p: RuleParams, unit: string | null, lc: Locale, t: T): string {
  if (type === 'range') {
    if (p.min !== null && p.min !== undefined && p.max !== null && p.max !== undefined)
      return t('rules.text.range', { min: value(p.min, null, lc), max: value(p.max, unit, lc) })
    if (p.min !== null && p.min !== undefined)
      return t('rules.text.rangeMin', { min: value(p.min, unit, lc) })
    return t('rules.text.rangeMax', { max: value(p.max, unit, lc) })
  }
  if (type === 'stuck') {
    const base = t('rules.text.stuck', { d: formatDuration(p.minutes ?? 0, t) })
    return p.ignore?.length
      ? `${base} ${t('rules.text.ignore', { values: p.ignore.map((v) => value(v, unit, lc)).join(', ') })}`
      : base
  }
  const change = value(p.max_change, unit, lc)
  return (p.window ?? 1) > 1
    ? t('rules.text.spikeWindow', { change, n: p.window })
    : t('rules.text.spike', { change })
}

/** What the rule saw: "value 87 %", "values 104–106 %", "jumped +6.4 °C". */
export function evidenceText(type: RuleType, e: Evidence, unit: string | null, lc: Locale, t: T): string {
  if (type === 'spike') {
    const c = e.change ?? 0
    return t('detections.evidence.spike', { change: `${c > 0 ? '+' : ''}${value(c, unit, lc)}` })
  }
  if (e.low !== undefined && e.high !== undefined && e.low !== e.high)
    return t('detections.evidence.values', { low: value(e.low, null, lc), high: value(e.high, unit, lc) })
  return t(`detections.evidence.${type}`, { value: value(e.value, unit, lc) })
}
