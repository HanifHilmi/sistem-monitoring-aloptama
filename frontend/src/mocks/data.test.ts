import { describe, expect, it } from 'vitest'
import { matrix, minutes, outages, SYSTEM } from './data'

const DAY = 86_400_000
const scopesOf = () => [
  'sla',
  'ola',
  'cdp:CDP1',
  'cdp:CDP2',
  ...SYSTEM.sites.flatMap((s) => [
    `site:${s.slug}`,
    ...s.components.map((c) => `component:${s.slug}:${c.type}`),
  ]),
]

// The sample data must tell one story: browser tests compare the outage list with the matrix (FR-KPI-009 AC1).
describe('sample outages', () => {
  const now = Date.UTC(2026, 10, 5, 0, 17, 30) // early in a UTC day: the open day has 14 minutes
  const periods: [number, number][] = [
    [Date.UTC(2026, 9, 1), Date.UTC(2026, 10, 1)],
    [Date.UTC(2026, 10, 1), Date.UTC(2026, 11, 1)], // open: ends in the future
    [Date.UTC(2026, 9, 26), Date.UTC(2026, 10, 2)],
  ]

  it('adds up to the matrix totals for every scope', () => {
    for (const [from, to] of periods) {
      const rows = new Map(matrix(from, to, 'day', now).rows.map((r) => [r.key, r]))
      const pooled = [...rows.values()]
        .filter((r) => r.kind === 'site')
        .reduce((n, r) => n + (r.total.missing ?? 0), 0)
      for (const scope of scopesOf()) {
        const o = outages(from, to, scope, now, 10_000)
        const lost = Object.values(o.by_cause).reduce((a, b) => a + b, 0)
        expect(lost, scope).toBe(o.availability.missing)
        expect(
          o.intervals.reduce((n, i) => n + i.lost_minutes, 0),
          scope,
        ).toBe(lost)
        expect(o.availability.missing, scope).toBe(scope === 'ola' ? pooled : rows.get(scope)?.total.missing)
      }
    }
  })

  it('matches the minute view of each day', () => {
    for (let d = Date.UTC(2026, 9, 1); d < Date.UTC(2026, 10, 6); d += DAY) {
      const day = new Date(d).toISOString().slice(0, 10)
      for (const scope of ['sla', 'cdp:CDP1', 'component:22:CEL', 'component:04:PWX']) {
        const m = minutes(day, scope, now)
        const o = outages(d, d + DAY, scope, now, 10_000)
        expect(m.expected - m.valid, `${scope} ${day}`).toBe(o.availability.missing)
      }
    }
  })

  it('lists a shared gap once, with every component it hit', () => {
    const o = outages(Date.UTC(2026, 9, 12), Date.UTC(2026, 9, 13), 'ola', now, 100)
    const gap = o.intervals.find((i) => i.cause === 'cdp_no_data')
    expect(gap?.minutes).toBe(41)
    expect(gap?.components).toHaveLength(SYSTEM.sites.reduce((n, s) => n + s.components.length, 0))
  })
})
