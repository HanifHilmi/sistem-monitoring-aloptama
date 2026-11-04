import { describe, expect, it } from 'vitest'
import type { MatrixRow } from '@/api/types'
import { figureLevel, level, lostMinutes, matrixLost } from './format'

const t = { good: 99, warning: 95 }

describe('level', () => {
  it('maps a percentage to its colour band', () => {
    expect(level(100, t)).toBe('full')
    expect(level(99.5, t)).toBe('good')
    expect(level(97, t)).toBe('warn')
    expect(level(90, t)).toBe('bad')
    expect(level(null, t)).toBe('none')
  })
})

describe('lostMinutes', () => {
  it('uses missing, else expected − valid, else 0', () => {
    expect(lostMinutes({ pct: 99, missing: 7 })).toBe(7)
    expect(lostMinutes({ pct: 99, valid: 90, expected: 100 })).toBe(10)
    expect(lostMinutes({ pct: 99 })).toBe(0)
    expect(lostMinutes({ pct: 100.01, valid: 101, expected: 100, missing: -1 })).toBe(0)
  })
})

describe('figureLevel', () => {
  it('keeps full for a figure with no minute lost', () => {
    expect(figureLevel({ pct: 100, valid: 44640, expected: 44640, missing: 0 }, t)).toBe('full')
  })

  it('is never full when minutes were lost, even if the figure rounds to 100.00', () => {
    // April 2026: 2 of 43 200 minutes lost = 99.995 %, rounded half-up to 100.00.
    expect(figureLevel({ pct: 100, valid: 43198, expected: 43200, missing: 2 }, t)).toBe('good')
    expect(figureLevel({ pct: 100, valid: 43198, expected: 43200 }, t)).toBe('good')
    expect(figureLevel({ pct: 100 }, t, 2)).toBe('good')
  })

  it('leaves lower bands alone and shows no coverage as none', () => {
    expect(figureLevel({ pct: 97, missing: 1300 }, t)).toBe('warn')
    expect(figureLevel({ pct: null, valid: 0, expected: 0, missing: 0 }, t)).toBe('none')
    expect(figureLevel(null, t)).toBe('none')
  })
})

describe('matrixLost', () => {
  const cell = (missing: number) => ({ pct: 100, valid: 1440 - missing, expected: 1440, missing })
  const rows: MatrixRow[] = [
    { key: 'sla', kind: 'sla', cells: [cell(0), cell(3)], total: cell(3) },
    { key: 'ola', kind: 'ola', cells: [{ pct: 100 }, { pct: 100 }], total: { pct: 100 } },
    { key: 'site:a', kind: 'site', site: 'a', cells: [cell(0), cell(0)], total: cell(0) },
    { key: 'site:b', kind: 'site', site: 'b', cells: [cell(0), cell(2)], total: cell(2) },
  ]

  it('reads a row cell or total', () => {
    expect(matrixLost(rows, rows[0]!, 0)).toBe(0)
    expect(matrixLost(rows, rows[0]!, 1)).toBe(3)
    expect(matrixLost(rows, rows[0]!, 'total')).toBe(3)
  })

  it('counts the sites for OLA, which has no counts of its own', () => {
    expect(matrixLost(rows, rows[1]!, 0)).toBe(0)
    expect(matrixLost(rows, rows[1]!, 1)).toBe(2)
    expect(matrixLost(rows, rows[1]!, 'total')).toBe(2)
    expect(figureLevel(rows[1]!.cells[1], t, matrixLost(rows, rows[1]!, 1))).toBe('good')
  })
})
