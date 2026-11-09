import { describe, expect, it } from 'vitest'
import type { Assets, CalibrationSummary, MatrixResponse, Outage, SystemInfo } from '@/api/types'
import {
  addCounts,
  calibrationCounts,
  dayCells,
  largestOutages,
  lastCompleteMonth,
  monthProgress,
  outagePlace,
} from './overview'

const th = { good: 99, warning: 95 }
const t = (key: string, v?: Record<string, unknown>) => `${key}${v ? JSON.stringify(v) : ''}`

const comp = (type: string, is_dcp = false) => ({
  type,
  is_dcp,
  name: { en: type, id: type },
  fields: [],
  mandatory: [],
  in_service_from: null,
  in_service_to: null,
})
const INFO = {
  code: 'X',
  sites: [
    {
      code: 'A',
      slug: 'a',
      station_code: 'a',
      name: { en: 'Site A', id: 'Lokasi A' },
      components: [comp('DCP', true), comp('ATRH'), comp('BARO')],
    },
    {
      code: 'B',
      slug: 'b',
      station_code: 'b',
      name: { en: 'Site B', id: 'Lokasi B' },
      components: [comp('DCP', true), comp('RAIN')],
    },
  ],
} as unknown as SystemInfo

describe('dayCells', () => {
  const m = {
    buckets: ['2026-11-01', '2026-11-02', '2026-11-03', '2026-11-04'].map((d) => ({ start: d, end: d })),
    rows: [
      {
        key: 'sla',
        kind: 'sla',
        cells: [
          { pct: 100, valid: 1440, expected: 1440, missing: 0 },
          { pct: 99.24, valid: 1429, expected: 1440, missing: 11 },
          { pct: 100, valid: 600, expected: 600, missing: 0 },
          { pct: null, valid: 0, expected: 0, missing: 0 },
        ],
        total: { pct: 99.7 },
      },
    ],
  } as unknown as MatrixResponse
  it('marks days done, today and still to come, with their level and lost minutes', () => {
    const cells = dayCells(m, m.rows[0], th, new Date('2026-11-03T10:00:00Z'))
    expect(cells.map((c) => c.state)).toEqual(['done', 'done', 'today', 'future'])
    expect(cells.map((c) => c.level)).toEqual(['full', 'good', 'full', 'none'])
    expect(cells[1]).toMatchObject({ day: '2026-11-02', pct: 99.24, lost: 11 })
    expect(cells[3]?.pct).toBeNull()
  })
  it('tells a past day without counted minutes from a day to come', () => {
    const cells = dayCells(m, m.rows[0], th, new Date('2026-11-05T00:00:00Z'))
    expect(cells[3]?.state).toBe('none')
  })
})

describe('monthProgress', () => {
  it('gives the day and the length of the UTC month', () => {
    expect(monthProgress(new Date('2026-11-09T00:30:00Z'))).toEqual({ day: 9, days: 30 })
    expect(monthProgress(new Date('2028-02-29T23:59:00Z'))).toEqual({ day: 29, days: 29 })
  })
})

describe('calibrationCounts', () => {
  const cal = (status: CalibrationSummary['status'], next_due: string | null, days_left: number | null) => ({
    status,
    last: null,
    next_due,
    days_left,
    validated_on: null,
    pending: false,
  })
  const assets = {
    components: [
      { site: 'a', type: 'DCP', calibration: cal('unknown', null, null) },
      { site: 'a', type: 'ATRH', calibration: cal('ok', '2026-12-27', 48) },
      { site: 'a', type: 'BARO', calibration: cal('due_soon', '2026-11-20', 11) },
      { site: 'b', type: 'DCP', calibration: cal('unknown', null, null) },
      { site: 'b', type: 'RAIN', calibration: cal('overdue', '2026-10-01', -39) },
    ],
  } as unknown as Assets
  it('counts sensors by status, leaves DCPs out and finds the next due date still ahead', () => {
    expect(calibrationCounts(assets, INFO)).toEqual({
      overdue: 1,
      due_soon: 1,
      ok: 1,
      unknown: 0,
      next: { date: '2026-11-20', days: 11, sensors: 1 },
    })
  })
  it('adds two systems together, joining sensors due on the same day', () => {
    const a = calibrationCounts(assets, INFO)
    const b = {
      overdue: 0,
      due_soon: 2,
      ok: 5,
      unknown: 1,
      next: { date: '2026-11-20', days: 11, sensors: 2 },
    }
    expect(addCounts(a, b)).toEqual({
      overdue: 1,
      due_soon: 3,
      ok: 6,
      unknown: 1,
      next: { date: '2026-11-20', days: 11, sensors: 3 },
    })
    expect(addCounts(b, { ...b, next: null }).next).toEqual(b.next)
  })
})

describe('outages', () => {
  const o = (start: string, lost: number, components?: { site: string; component: string }[]): Outage => ({
    start,
    end: start,
    minutes: 1,
    cause: 'cdp_no_data',
    lost_minutes: lost,
    ongoing: false,
    components,
  })
  it('lists the largest over every system, the latest first on a tie', () => {
    const rows = largestOutages(
      [
        { system: 'X', intervals: [o('2026-11-02T01:00:00Z', 84), o('2026-11-03T01:00:00Z', 42)] },
        { system: 'Y', intervals: [o('2026-11-05T01:00:00Z', 42), o('2026-11-06T01:00:00Z', 10)] },
      ],
      3,
    )
    expect(rows.map((r) => [r.system, r.lost_minutes, r.start.slice(0, 10)])).toEqual([
      ['X', 84, '2026-11-02'],
      ['Y', 42, '2026-11-05'],
      ['X', 42, '2026-11-03'],
    ])
  })
  it('says where an outage hit', () => {
    const all = INFO.sites.flatMap((s) => s.components.map((c) => ({ site: s.slug, component: c.type })))
    expect(outagePlace(o('x', 1, all), INFO, 'en', t)).toBe('outages.allComponents{"n":5}')
    expect(outagePlace(o('x', 1, [{ site: 'b', component: 'RAIN' }]), INFO, 'id', t)).toBe('Lokasi B · RAIN')
    expect(outagePlace(o('x', 1, all.slice(0, 3)), INFO, 'en', t)).toBe('outages.components{"n":3}')
    expect(outagePlace(o('x', 1), INFO, 'en', t)).toBe('')
  })
})

describe('lastCompleteMonth', () => {
  it('is last month, or nothing while the first month of data is still running', () => {
    expect(lastCompleteMonth('2025-12-24T00:00:00Z', new Date('2026-11-09T00:00:00Z'))).toBe('2026-10')
    expect(lastCompleteMonth('2026-11-03T00:00:00Z', new Date('2026-11-09T00:00:00Z'))).toBeNull()
  })
})
