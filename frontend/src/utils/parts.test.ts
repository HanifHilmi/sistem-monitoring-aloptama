import { describe, expect, it } from 'vitest'
import type { Part } from '@/api/types'
import { missingParts, partModel, partsSummary, sortParts, usualParts } from './parts'

const part = (role: string, extra: Partial<Part> = {}): Part => ({
  id: 1,
  component_id: 1,
  role,
  manufacturer: null,
  model: null,
  firmware: null,
  installed_on: null,
  removed_on: null,
  replaces: null,
  replaced_by: null,
  notes: null,
  ...extra,
})

describe('sensor parts (R3.7)', () => {
  it('lists the usual parts; an RVR with ambient light also has the ALS unit', () => {
    expect(usualParts('ATRH')).toEqual(['Thermohygrometer', 'MARS'])
    expect(usualParts('RVR', ['RVR', 'VIS'])).not.toContain('ALS')
    expect(usualParts('RVR', ['RVR', 'VIS', 'ALS'])).toEqual([
      'Transmitter 1',
      'Transmitter 2',
      'Receiver 1',
      'Receiver 2',
      'Logger',
      'ALS',
    ])
    expect(usualParts('UNKNOWN')).toEqual([])
  })

  it('offers the usual parts not recorded yet, whatever their case or spacing', () => {
    const installed = [part('receiver  1'), part('Transmitter 1'), part('Spare cable')]
    expect(missingParts(usualParts('RVR'), installed)).toEqual(['Transmitter 2', 'Receiver 2', 'Logger'])
  })

  it('sorts installed parts in the usual order, others after by name', () => {
    const sorted = sortParts(
      [part('Blower'), part('Heater'), part('Ceilometer'), part('Cable')],
      usualParts('CEL'),
    )
    expect(sorted.map((p) => p.role)).toEqual(['Ceilometer', 'Blower', 'Cable', 'Heater'])
  })

  it('sums a sensor up in one line', () => {
    const parts = [
      part('Thermohygrometer', { manufacturer: 'Vaisala', model: 'HMP155', serial_number: 'K1' }),
    ]
    expect(partsSummary(parts)).toEqual({ model: 'Vaisala HMP155', more: 0, serial: 'K1' })
    expect(partsSummary([...parts, part('MARS')]).more).toBe(1)
    expect(partsSummary([])).toEqual({ model: '', more: 0, serial: null })
    expect(partModel(part('MARS', { manufacturer: 'Vaisala' }))).toBe('Vaisala')
  })
})
