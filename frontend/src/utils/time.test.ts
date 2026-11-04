import { describe, expect, it } from 'vitest'
import { decodePeriod, decodeWindow, encodePeriod, periodContaining, shiftPeriod } from './time'

const at = (iso: string) => new Date(iso)

describe('UTC periods (FR-KPI-002)', () => {
  it('ISO weeks start on Monday', () => {
    const p = periodContaining('week', at('2026-11-04T10:00:00Z')) // Wednesday
    expect(p.from.toISOString()).toBe('2026-11-02T00:00:00.000Z')
    expect(p.to.toISOString()).toBe('2026-11-09T00:00:00.000Z')
  })

  it('months are half-open and adjacent', () => {
    const sep = periodContaining('month', at('2026-09-15T00:00:00Z'))
    const oct = shiftPeriod(sep, 1)
    expect(sep.to.getTime()).toBe(oct.from.getTime())
    expect((sep.to.getTime() - sep.from.getTime()) / 60000).toBe(43200)
  })

  it('quarters and previous period', () => {
    const q = periodContaining('quarter', at('2026-11-04T00:00:00Z'))
    expect(q.from.toISOString()).toBe('2026-10-01T00:00:00.000Z')
    expect(shiftPeriod(q, -1).from.toISOString()).toBe('2026-07-01T00:00:00.000Z')
  })

  it('round-trips through the URL', () => {
    const p = periodContaining('day', at('2026-11-03T05:00:00Z'))
    expect(decodePeriod(encodePeriod(p), periodContaining('year', new Date()))).toEqual(p)
    const custom = {
      kind: 'custom' as const,
      from: at('2026-11-01T00:00:00Z'),
      to: at('2026-11-04T06:30:00Z'),
    }
    expect(decodePeriod(encodePeriod(custom), p)).toEqual(custom)
  })

  it('rejects invalid custom periods', () => {
    const fb = periodContaining('month', at('2026-11-04T00:00:00Z'))
    expect(decodePeriod('custom:2026-11-04T00:00:00Z~2026-11-01T00:00:00Z', fb)).toBe(fb)
    expect(decodePeriod('nonsense', fb)).toBe(fb)
  })
})

describe('chart windows (FR-DSH-008)', () => {
  it('limits custom windows to 31 days', () => {
    const w = decodeWindow('custom:2026-09-01T00:00:00Z~2026-11-01T00:00:00Z', at('2026-11-04T00:00:00Z'))
    expect(w.preset).toBe('3h')
  })
  it('presets end at the current minute', () => {
    const w = decodeWindow('24h', at('2026-11-04T10:30:20Z'))
    expect(w.to.toISOString()).toBe('2026-11-04T10:31:00.000Z')
    expect((w.to.getTime() - w.from.getTime()) / 3600000).toBe(24)
  })
})
