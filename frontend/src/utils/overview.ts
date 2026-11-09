// The dashboard (FR-DSH-001): what each system's panel and the cards under it show, worked out from the API's
// answers. Nothing here is a new figure: each value is one the board, the site pages or the exports also show.
import type { Assets, MatrixResponse, MatrixRow, Outage, SystemInfo } from '@/api/types'
import type { Locale } from '@/i18n'
import { figureLevel, matrixLost, type Level, type Thresholds } from './format'
import { reportMonths } from './exports'
import { isoDay } from './time'

type T = (key: string, values?: Record<string, unknown>) => string

/** One day of a month strip. */
export interface DayCell {
  day: string
  pct: number | null
  lost: number
  level: Level
  /** done: a whole day counted; today: counted so far; future: not reached yet; none: no minute counted */
  state: 'done' | 'today' | 'future' | 'none'
}

/** A matrix row (by day) as month-strip cells: each day's level, today marked, the days still to come apart. */
export function dayCells(m: MatrixResponse, row: MatrixRow | undefined, t: Thresholds, now: Date): DayCell[] {
  const today = isoDay(now)
  return m.buckets.map((b, i) => {
    if (b.start > today) return { day: b.start, pct: null, lost: 0, level: 'none', state: 'future' }
    const cell = row?.cells[i]
    const lost = row ? matrixLost(m.rows, row, i) : 0
    const lvl = cell ? figureLevel(cell, t, lost) : 'none'
    const pct = cell?.pct ?? null
    const state = b.start === today ? 'today' : pct === null ? 'none' : 'done'
    return { day: b.start, pct, lost, level: lvl, state }
  })
}

/** Day of the month and the month's length (UTC): "day 9 of 30". */
export function monthProgress(now: Date): { day: number; days: number } {
  const days = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() + 1, 0)).getUTCDate()
  return { day: now.getUTCDate(), days }
}

/** Calibration status of a system's sensors, and the next date one falls due (FR-REG-005). */
export interface CalibrationCounts {
  overdue: number
  due_soon: number
  ok: number
  unknown: number
  /** the earliest due date still ahead, with how many sensors fall due that day */
  next: { date: string; days: number; sensors: number } | null
}

/** Counts every sensor by its calibration status. DCPs are left out: a data logger is not calibrated. */
export function calibrationCounts(a: Assets, info: SystemInfo | null): CalibrationCounts {
  const isDcp = (site: string, type: string) =>
    info?.sites.find((s) => s.slug === site)?.components.find((c) => c.type === type)?.is_dcp ??
    type === 'DCP'
  const out: CalibrationCounts = { overdue: 0, due_soon: 0, ok: 0, unknown: 0, next: null }
  for (const c of a.components) {
    if (isDcp(c.site, c.type)) continue
    const cal = c.calibration
    out[cal.status] += 1
    if (cal.status === 'overdue' || !cal.next_due || cal.days_left === null) continue
    if (!out.next || cal.next_due < out.next.date)
      out.next = { date: cal.next_due, days: cal.days_left, sensors: 1 }
    else if (cal.next_due === out.next.date) out.next.sensors += 1
  }
  return out
}

/** Several systems' counts together, for the dashboard card. */
export function addCounts(a: CalibrationCounts, b: CalibrationCounts): CalibrationCounts {
  const next =
    !a.next || (b.next && b.next.date < a.next.date)
      ? b.next
      : !b.next || a.next.date < b.next.date
        ? a.next
        : { ...a.next, sensors: a.next.sensors + b.next.sensors }
  return {
    overdue: a.overdue + b.overdue,
    due_soon: a.due_soon + b.due_soon,
    ok: a.ok + b.ok,
    unknown: a.unknown + b.unknown,
    next,
  }
}

/** An outage and the system it belongs to. */
export interface SystemOutage extends Outage {
  system: string
}

/** The `n` largest outages over every system: most minutes lost first, then the latest. */
export function largestOutages(lists: { system: string; intervals: Outage[] }[], n: number): SystemOutage[] {
  return lists
    .flatMap((l) => l.intervals.map((o) => ({ ...o, system: l.system })))
    .sort((a, b) => b.lost_minutes - a.lost_minutes || b.start.localeCompare(a.start))
    .slice(0, n)
}

/** Where an outage hit: "all 21 components", "Runway Middle · RAIN", or "4 components". */
export function outagePlace(o: Outage, info: SystemInfo | null, lc: Locale, t: T): string {
  const hit = o.components ?? []
  if (!hit.length) return ''
  const total = info?.sites.reduce((n, s) => n + s.components.length, 0) ?? 0
  if (total && hit.length >= total) return t('outages.allComponents', { n: total })
  if (hit.length > 2) return t('outages.components', { n: hit.length })
  return hit
    .map((c) => {
      const site = info?.sites.find((s) => s.slug === c.site)
      return `${site?.name[lc] ?? c.site} · ${c.component}`
    })
    .join(', ')
}

/** The newest month that is over, which a monthly report is usually made for; null before the first one ends. */
export function lastCompleteMonth(coverageStart: string, now: Date): string | null {
  return reportMonths(coverageStart, now)[1] ?? null
}
