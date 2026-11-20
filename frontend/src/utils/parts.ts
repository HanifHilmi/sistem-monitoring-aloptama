// Sensor parts (R3.7). A sensor (component) is what counts for availability; its parts are the physical units on the
// mast, each with its own part and serial number. The lists below are what a sensor of each type usually has: the
// screens offer the ones not recorded yet. They are names, so they read the same in both languages.
import type { Part } from '@/api/types'

const USUAL: Record<string, string[]> = {
  DCP: ['Data logger', 'Power supply'],
  ATRH: ['Thermohygrometer', 'MARS'],
  BARO: ['Barometer', 'Quadplate'],
  ANEM: ['Wind sensor'],
  RVR: ['Transmitter 1', 'Transmitter 2', 'Receiver 1', 'Receiver 2', 'Logger'],
  CEL: ['Ceilometer', 'Blower'],
  PWX: ['Present weather sensor'],
  RAIN: ['Rain gauge'],
  SOLR: ['Pyranometer'],
  LIGH: ['Lightning detector'],
}

/** The parts a sensor of this type usually has. An RVR that reports ambient light (ALS) also has the ALS unit. */
export function usualParts(type: string, fields: readonly string[] = []): string[] {
  const list = [...(USUAL[type] ?? [])]
  if (type === 'RVR' && fields.includes('ALS')) list.push('ALS')
  return list
}

/** Usual parts with no installed part of that name yet (names compared without case or extra spaces). */
export function missingParts(
  expected: readonly string[],
  installed: readonly Pick<Part, 'role'>[],
): string[] {
  const key = (s: string) => s.trim().replace(/\s+/g, ' ').toLowerCase()
  const have = new Set(installed.map((p) => key(p.role)))
  return expected.filter((r) => !have.has(key(r)))
}

/** "Vaisala HMP155", or '' when neither is known. */
export const partModel = (p: Pick<Part, 'manufacturer' | 'model'>) =>
  [p.manufacturer, p.model].filter(Boolean).join(' ')

/** One line for lists: the first part's model, and how many parts the sensor has. */
export function partsSummary(parts: readonly Part[]): { model: string; more: number; serial: string | null } {
  const first = parts[0]
  return {
    model: first ? partModel(first) : '',
    more: Math.max(0, parts.length - 1),
    serial: first?.serial_number ?? null,
  }
}

/** Installed parts in the usual order, then the others by name. */
export function sortParts<T extends Pick<Part, 'role'>>(
  parts: readonly T[],
  expected: readonly string[],
): T[] {
  const rank = (p: T) => {
    const i = expected.findIndex((r) => r.toLowerCase() === p.role.trim().toLowerCase())
    return i === -1 ? expected.length : i
  }
  return [...parts].sort((a, b) => rank(a) - rank(b) || a.role.localeCompare(b.role))
}
