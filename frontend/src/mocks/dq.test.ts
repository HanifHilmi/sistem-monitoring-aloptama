import { describe, expect, it } from 'vitest'
import { minutes, outages } from './data'
import { applyRule } from './dq'

// The sample rules behave like the planned ones (FR-DQ-001): boundaries, missing values, runs.
describe('sample rules', () => {
  it('range fires outside the limits only, and merges neighbours', () => {
    const hits = applyRule('range', { min: 0, max: 10 }, [0, 10, 11, 12, null, -1, 5])
    expect(hits.map((h) => [h.a, h.b, h.evidence.low, h.evidence.high])).toEqual([
      [2, 4, 11, 12],
      [5, 6, undefined, undefined],
    ])
    expect(hits[1]!.evidence.value).toBe(-1)
  })

  it('stuck needs the full run; a missing minute or an ignored value breaks it', () => {
    expect(applyRule('stuck', { minutes: 3 }, [5, 5, 5, 6]).map((h) => [h.a, h.b])).toEqual([[0, 3]])
    expect(applyRule('stuck', { minutes: 3 }, [5, 5, null, 5, 5])).toEqual([])
    expect(applyRule('stuck', { minutes: 3, ignore: [0] }, [0, 0, 0, 0])).toEqual([])
  })

  it('spike compares consecutive valid minutes only', () => {
    const hits = applyRule('spike', { max_change: 2 }, [10, 12, 14.5, null, 30, 30])
    expect(hits.map((h) => [h.a, h.evidence.change])).toEqual([[2, 2.5]]) // exactly 2 does not fire
  })
})

// A confirmed detection on a mandatory field costs minutes like a flag; a suspect costs nothing.
describe('sample detections', () => {
  const now = Date.UTC(2026, 10, 5, 12)
  it('confirmed: the minutes become lost with cause "detection"', () => {
    const m = minutes('2026-10-17', 'component:04:ATRH', now)
    const range = m.codes.slice(120, 360) // 02:00–06:00, detection 11
    expect([...range].every((c) => c !== 'v')).toBe(true)
    const d = [...range].filter((c) => c === 'd').length
    expect(d).toBeGreaterThan(0)
    const o = outages(Date.UTC(2026, 9, 17), Date.UTC(2026, 9, 18), 'component:04:ATRH', now, 100)
    expect(o.by_cause.detection).toBe(d)
    expect(o.intervals.find((i) => i.cause === 'detection')?.detections?.[0]).toMatchObject({ field: 'RH' })
  })

  it('suspect: shown to signed-in users, valid all the same', () => {
    const visitor = minutes('2026-11-04', 'component:04:ATRH', now)
    const viewer = minutes('2026-11-04', 'component:04:ATRH', now, true)
    expect(visitor.codes.includes('s')).toBe(false)
    expect(viewer.codes.includes('s')).toBe(true)
    expect(viewer.valid).toBe(visitor.valid)
  })
})
