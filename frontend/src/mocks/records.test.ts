import { describe, expect, it } from 'vitest'
import { addMonths } from '@/utils/time'
import { checkCalibration, summary } from './records'

// Calibration status follows the latest record (FR-REG-005): overdue, due soon within the window, OK, unknown.
describe('sample calibration status', () => {
  const now = Date.now()
  it('derives each status from the latest record', () => {
    expect(summary('22', 'CEL', now, 30)).toMatchObject({ status: 'overdue', days_left: -4 })
    expect(summary('04', 'ATRH', now, 30)).toMatchObject({ status: 'due_soon', days_left: 7 })
    expect(summary('04', 'ATRH', now, 5).status).toBe('ok') // a shorter window
    expect(summary('04', 'BARO', now, 30).status).toBe('ok')
    expect(summary('04', 'RVR', now, 30)).toEqual({
      status: 'unknown',
      last: null,
      next_due: null,
      days_left: null,
      validated_on: null,
      pending: false,
    })
  })

  it('checks a record as the PRD says (§9.5)', () => {
    const base = { component_id: 2, performed_by: 'Lab', certificate: null, notes: null, validated_on: null }
    const today = new Date(now).toISOString().slice(0, 10)
    const future = new Date(now + 86_400_000).toISOString().slice(0, 10)
    expect(checkCalibration({ ...base, date: future, next_due: null, interval_months: 12 }, now)).toBe(
      'date_in_future',
    )
    expect(checkCalibration({ ...base, date: today, next_due: today, interval_months: null }, now)).toBe(
      'next_due_before_date',
    )
    expect(checkCalibration({ ...base, date: today, next_due: null, interval_months: 0 }, now)).toBe(
      'invalid_interval',
    )
    const d = { ...base, date: '2026-01-31', next_due: null, interval_months: 12 }
    expect(checkCalibration(d, now)).toBeNull()
    expect(d.next_due).toBe('2027-01-31') // filled from the interval
    // the certificate's validation date: optional (pending), not before the calibration, not in the future
    expect(checkCalibration({ ...d, validated_on: '2026-01-30' }, now)).toBe('validated_before_date')
    expect(checkCalibration({ ...d, validated_on: future }, now)).toBe('date_in_future')
    expect(checkCalibration({ ...d, validated_on: '2026-02-04' }, now)).toBeNull()
  })

  it('marks a calibration whose certificate is not validated yet as pending', () => {
    expect(summary('middle', 'RAIN', now, 30)).toMatchObject({ pending: true, validated_on: null })
    expect(summary('04', 'BARO', now, 30).pending).toBe(false)
    expect(summary('04', 'RVR', now, 30).pending).toBe(false) // nothing recorded: unknown, not pending
  })
})

describe('addMonths (same rule as the server)', () => {
  it('keeps the day, or takes the month’s last day when it has fewer', () => {
    expect(addMonths('2026-01-31', 1)).toBe('2026-02-28')
    expect(addMonths('2028-01-31', 1)).toBe('2028-02-29')
    expect(addMonths('2026-11-30', 3)).toBe('2027-02-28')
    expect(addMonths('2026-12-15', 1)).toBe('2027-01-15')
    expect(addMonths('2026-03-31', 12)).toBe('2027-03-31')
    expect(addMonths('2026-05-10', 120)).toBe('2036-05-10')
  })
})
