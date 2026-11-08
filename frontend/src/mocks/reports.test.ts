import { describe, expect, it } from 'vitest'
import { day, latest } from './reports'

// The browser tests rely on yesterday's sample thunderstorm and on every type having a latest report: true at every
// hour of every day.
const HOUR = 3_600_000
const start = Date.parse('2026-11-01T00:00:00Z')
const moments = Array.from({ length: 90 }, (_, i) => start + i * 9 * HOUR + (i % 7) * 13 * 60_000)

describe('sample reports', () => {
  it("always have yesterday's thunderstorm SPECI and TAF amendment", () => {
    for (const now of moments) {
      const y = new Date(now - 24 * HOUR).toISOString().slice(0, 10)
      const speci = day(now, y, 'metar').reports.filter((r) => r.notes.includes('thunderstorm onset'))
      expect(
        speci.map((r) => r.logged_at.slice(11, 16)),
        y,
      ).toEqual(['07:16'])
      expect(day(now, y, 'taf').reports.filter((r) => r.kind === 'TAF AMD')).toHaveLength(1)
    }
  })

  it('always have a latest report of each type, newest first, never in the future', () => {
    for (const now of moments) {
      const l = latest(now)
      for (const list of [l.metar, l.metreport, l.taf]) {
        expect(list.length).toBeGreaterThan(0)
        expect(Date.parse(list[0]!.logged_at)).toBeLessThanOrEqual(now)
        expect([...list].sort((a, b) => b.logged_at.localeCompare(a.logged_at))).toEqual(list)
      }
    }
  })
})
