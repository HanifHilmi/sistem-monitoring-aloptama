import { describe, expect, it } from 'vitest'
import { SYSTEM } from '@/mocks/data'
import {
  ALARM_COLUMNS,
  DAILY_COLUMNS,
  QUALITY_COLUMNS,
  dailyRowsPerDay,
  estimateRows,
  exportFileName,
  exportUrl,
  minuteHeader,
  minuteLayout,
} from './exports'

const at = (iso: string) => new Date(iso)
const NOV = [at('2026-11-01T00:00:00Z'), at('2026-12-01T00:00:00Z')] as const

describe('CSV exports (FR-EXP-002)', () => {
  it('names a file by its first and last day, like the monthly PDF', () => {
    expect(exportFileName('WIDN-CAT3', 'daily', ...NOV)).toBe(
      'SIMOLA_WIDN-CAT3_daily_2026-11-01_2026-11-30.csv',
    )
    expect(exportFileName('WIDN-CAT3', 'minutes', ...NOV, 'RWY04')).toBe(
      'SIMOLA_WIDN-CAT3_minutes_RWY04_2026-11-01_2026-11-30.csv',
    )
    // a custom period with minutes keeps them
    expect(
      exportFileName('WIDN-CAT3', 'alarms', at('2026-11-03T10:30:00Z'), at('2026-11-03T12:00:00Z')),
    ).toBe('SIMOLA_WIDN-CAT3_alarms_2026-11-03T1030Z_2026-11-03T1200Z.csv')
  })

  it('sends each file only its own options', () => {
    const daily = new URL(exportUrl('WIDN-CAT3', 'daily', ...NOV, { site: '04', type: 'error' }), 'http://x')
    expect(daily.pathname).toBe('/api/v1/systems/WIDN-CAT3/exports/daily.csv')
    expect([...daily.searchParams.keys()]).toEqual(['from', 'to'])
    expect(daily.searchParams.get('from')).toBe('2026-11-01T00:00:00.000Z')

    const minutes = new URL(exportUrl('WIDN-CAT3', 'minutes', ...NOV, { site: '04' }), 'http://x')
    expect(minutes.searchParams.get('site')).toBe('04')

    const alarms = new URL(
      exportUrl('WIDN-CAT3', 'alarms', ...NOV, { type: 'error', scope: 'component:04:RVR' }),
      'http://x',
    )
    expect(alarms.searchParams.get('type')).toBe('error')
    expect(alarms.searchParams.get('scope')).toBe('component:04:RVR')

    const quality = new URL(exportUrl('WIDN-CAT3', 'quality', ...NOV, { detections: false }), 'http://x')
    expect(quality.searchParams.get('records')).toBe('flags')
    expect(quality.searchParams.has('all')).toBe(false)
    const all = new URL(exportUrl('WIDN-CAT3', 'quality', ...NOV, { all: true }), 'http://x')
    expect(all.searchParams.get('records')).toBe('flags,detections')
    expect(all.searchParams.get('all')).toBe('1')
  })

  it('counts the rows: one per day and scope, one per minute', () => {
    // the system, two CDPs, three sites and 21 sensors
    expect(dailyRowsPerDay(SYSTEM)).toBe(27)
    const later = at('2027-01-01T00:00:00Z').getTime()
    expect(estimateRows('daily', SYSTEM, ...NOV, later, null)).toBe(30 * 27)
    expect(estimateRows('minutes', SYSTEM, ...NOV, later, null)).toBe(43_200)
    // an open period counts up to now
    expect(estimateRows('minutes', SYSTEM, ...NOV, at('2026-11-02T00:10:00Z').getTime(), null)).toBe(1450)
    expect(estimateRows('daily', SYSTEM, ...NOV, at('2026-11-02T00:10:00Z').getTime(), null)).toBe(2 * 27)
    expect(estimateRows('alarms', SYSTEM, ...NOV, later, 12)).toBe(12)
  })

  it('writes one status column per sensor and units in the headers', () => {
    const header = minuteHeader(minuteLayout(SYSTEM, '04'))
    expect(header.slice(0, 3)).toEqual(['time_utc', 'cdps', 'DCP.status'])
    expect(header).toContain('ATRH.TEMP (°C)')
    expect(header).toContain('PWX.PW') // no unit
    expect(header.filter((h) => h.endsWith('.status'))).toHaveLength(7)
    expect(header.slice(-2)).toEqual(['definitions_version', 'generated_at_utc'])
    expect(new Set(header).size).toBe(header.length)
  })

  it('ends every file with the definitions version and the time it was made (FR-KPI-008)', () => {
    for (const cols of [DAILY_COLUMNS, ALARM_COLUMNS, QUALITY_COLUMNS]) {
      const names = cols.map((c) => c.name)
      expect(names.slice(-2)).toEqual(['definitions_version', 'generated_at_utc'])
      expect(new Set(names).size).toBe(names.length)
      // header names are plain: a spreadsheet never reads them as formulas
      expect(names.every((n) => /^[a-z_]+$/.test(n))).toBe(true)
    }
  })
})
