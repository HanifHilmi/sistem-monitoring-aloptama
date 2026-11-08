import { describe, expect, it } from 'vitest'
import { ALARM_COLUMNS, DAILY_COLUMNS, QUALITY_COLUMNS, minuteHeader, minuteLayout } from '@/utils/exports'
import { SYSTEM, kpis } from './data'
import { exportFile, type SampleFile } from './exports'

const NOW = Date.parse('2026-11-08T06:00:00Z')
const OCT = { from: '2026-10-01T00:00:00.000Z', to: '2026-11-01T00:00:00.000Z' }

function file(
  kind: string,
  q: Record<string, string>,
): { name: string; rows: Record<string, string>[]; header: string[] } {
  const f = exportFile(kind, new URLSearchParams(q), NOW) as SampleFile
  expect(typeof f).toBe('object')
  expect(f.body.startsWith('\ufeff')).toBe(true)
  const lines = f.body.slice(1).split('\r\n').filter(Boolean)
  const header = lines[0]!.split(',')
  // sample cells hold no quoted commas except free text, which these checks do not read
  const rows = lines.slice(1).map((l) => Object.fromEntries(l.split(',').map((v, i) => [header[i]!, v])))
  return { name: f.name, rows, header }
}

describe('sample CSV exports (R3.4)', () => {
  it('the daily file adds up to the month’s figures (U7)', () => {
    const { name, rows, header } = file('daily', OCT)
    expect(name).toBe('SIMOLA_WIDN-CAT3_daily_2026-10-01_2026-10-31.csv')
    expect(header).toEqual(DAILY_COLUMNS.map((c) => c.name))
    expect(rows).toHaveLength(31 * 27)
    const k = kpis(Date.parse(OCT.from), Date.parse(OCT.to), NOW)
    const sum = (pick: (r: Record<string, string>) => boolean) =>
      rows
        .filter(pick)
        .reduce((a, r) => [a[0]! + Number(r.valid_min), a[1]! + Number(r.expected_min)], [0, 0])
    expect(sum((r) => r.scope === 'system')).toEqual([k.sla.valid, k.sla.expected])
    for (const c of k.cdps)
      expect(sum((r) => r.scope === 'cdp' && r.cdp === c.code)).toEqual([c.uptime.valid, c.uptime.expected])
    const ratios: number[] = []
    for (const s of k.sites) {
      const code = SYSTEM.sites.find((x) => x.slug === s.slug)!.code
      const [v, e] = sum((r) => r.scope === 'site' && r.site === code)
      expect([v, e]).toEqual([s.availability.valid, s.availability.expected])
      ratios.push(v! / e!)
    }
    expect(Math.round((ratios.reduce((a, b) => a + b, 0) / ratios.length) * 10000) / 100).toBe(k.ola.pct)
    expect(sum((r) => r.scope === 'component')).toEqual([k.pooled.valid, k.pooled.expected])
  })

  it('the minute file: a row per minute, a status per sensor', () => {
    const { name, rows, header } = file('minutes', {
      from: '2026-10-03T00:00:00Z',
      to: '2026-10-04T00:00:00Z',
      site: '04',
    })
    expect(name).toBe('SIMOLA_WIDN-CAT3_minutes_RWY04_2026-10-03_2026-10-03.csv')
    expect(header).toEqual(minuteHeader(minuteLayout(SYSTEM, '04')))
    expect(rows).toHaveLength(1440)
    expect(rows[0]!.time_utc).toBe('2026-10-03T00:00:00Z')
    const valid = rows.find((r) => r['ATRH.status'] === 'valid')!
    expect(Number(valid['ATRH.TEMP (°C)'])).toBeGreaterThan(10)
    expect(rows.every((r) => r['DCP.status'] === 'no_data' || r.cdps === 'CDP1 CDP2')).toBe(true)
  })

  it('alarm and flag files carry their headers; limits and unknown sites are refused', () => {
    expect(file('alarms', OCT).header).toEqual(ALARM_COLUMNS.map((c) => c.name))
    const q = file('quality', OCT)
    expect(q.header).toEqual(QUALITY_COLUMNS.map((c) => c.name))
    expect(q.rows.every((r) => r.kind !== 'detection' || r.status === 'confirmed')).toBe(true)
    expect(
      exportFile('minutes', new URLSearchParams({ ...OCT, to: '2026-11-02T00:00:00Z', site: '04' }), NOW),
    ).toBe('period_too_long')
    expect(exportFile('minutes', new URLSearchParams({ ...OCT, site: 'x' }), NOW)).toBe('site_not_found')
  })
})
