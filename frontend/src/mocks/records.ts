// Sample station, site and sensor records and calibration histories (R2.5) for dev:sample and CI. Calibration dates
// are relative to today, so each status (overdue, due soon, OK, unknown) stays on screen whatever the date.
// Sensor models are typical AWOS equipment; serial and part numbers are made up.
import type {
  Calibration,
  CalibrationDraft,
  CalibrationSummary,
  ComponentMeta,
  SiteMeta,
  StationMeta,
} from '@/api/types'
import { SYSTEM } from './data'
import { addMonths } from '@/utils/time'

interface State {
  station: Omit<StationMeta, 'name' | 'icao'>
  sites: Record<string, SiteMeta>
  components: Record<string, ComponentMeta> // "site:type"
  calibrations: (Calibration & { site: string; type: string })[]
}

const KEY = 'simola.mock.records'
const DAY = 86_400_000
const day = (ms: number) => new Date(ms).toISOString().slice(0, 10)

const MODELS: Record<string, [string, string, string, string]> = {
  // type: sensor type, manufacturer, model, part number
  DCP: ['Data collection platform', 'Vaisala', 'AWS310', 'AWS310-SITE'],
  ATRH: ['Temperature and humidity probe', 'Vaisala', 'HMP155', 'HMP155E'],
  BARO: ['Digital barometer', 'Vaisala', 'PTB330', 'PTB330A1A2'],
  ANEM: ['Ultrasonic wind sensor', 'Vaisala', 'WMT700', 'WMT703'],
  RVR: ['Forward scatter sensor', 'Vaisala', 'FS11P', 'FS11P-1'],
  CEL: ['Ceilometer', 'Vaisala', 'CL31', 'CL31-AAA'],
  PWX: ['Present weather sensor', 'Vaisala', 'PWD22', 'PWD22-W'],
  RAIN: ['Tipping bucket rain gauge', 'Vaisala', 'RG13H', 'RG13H-02'],
  SOLR: ['Pyranometer', 'Kipp & Zonen', 'CMP6', 'CMP6-0302'],
  LIGH: ['Thunderstorm sensor', 'Vaisala', 'TSS928', 'TSS928-A'],
}

/** days relative to today of [last calibration, next due]; absent: no record (unknown) */
const CAL: Record<string, [number, number][]> = {
  '04:ATRH': [
    [-358, 7],
    [-723, -358],
  ],
  'middle:ATRH': [[-200, 165]],
  '22:ATRH': [[-400, -35]],
  '04:BARO': [[-90, 275]],
  'middle:BARO': [[-150, 215]],
  '22:BARO': [[-344, 21]],
  '04:ANEM': [[-60, 305]],
  '22:ANEM': [[-61, 304]],
  '04:CEL': [[-120, 245]],
  '22:CEL': [
    [-369, -4],
    [-734, -369],
  ],
  '04:PWX': [[-100, 265]],
  '22:PWX': [[-101, 264]],
  'middle:RAIN': [[-30, 335]],
  'middle:SOLR': [[-353, 12]],
}

function seed(now: number): State {
  const today = Math.floor(now / DAY) * DAY
  const components: State['components'] = {}
  let n = 0
  for (const s of SYSTEM.sites)
    for (const c of s.components) {
      const m = MODELS[c.type]!
      n++
      components[`${s.slug}:${c.type}`] = {
        sensor_type: m[0],
        manufacturer: m[1],
        model: m[2],
        part_number: m[3],
        serial_number: `K${(4710000 + n * 7919).toString()}`,
        installed_on: c.type === 'SOLR' ? '2026-01-15' : '2019-08-14',
        firmware: c.type === 'DCP' ? '7.80.3' : null,
        notes: s.slug === '22' && c.type === 'CEL' ? 'Window heater replaced in 2025.' : null,
      }
    }
  const calibrations: State['calibrations'] = []
  let id = 0
  for (const [key, list] of Object.entries(CAL)) {
    const [site, type] = key.split(':') as [string, string]
    const comp = SYSTEM.sites.flatMap((x) => x.components.map((c) => ({ x, c })))
    const index = comp.findIndex(({ x, c }) => x.slug === site && c.type === type)
    for (const [last, next] of [...list].reverse()) {
      const at = today + last * DAY
      calibrations.push({
        id: ++id,
        component_id: index + 1,
        site,
        type,
        date: day(at),
        performed_by: id % 2 ? 'BMKG Calibration Laboratory' : 'Vaisala service partner',
        certificate: `CAL/${new Date(at).getUTCFullYear()}/${String(100 + id * 37).padStart(4, '0')}`,
        next_due: day(today + next * DAY),
        interval_months: Math.round((next - last) / 30.4) === 12 ? 12 : null,
        notes: null,
        created_by: id % 3 ? 'andi' : 'budi',
        created_at: new Date(at + 6 * 3_600_000).toISOString(),
        updated_by: null,
        updated_at: null,
      })
    }
  }
  return {
    station: {
      wmo_number: null,
      airport_name: 'Raja Haji Fisabilillah International Airport',
      lat: 0.9227,
      lon: 104.5322,
      elevation_m: 16,
      procurement_year: 2019,
      notes: 'AWOS CAT III, two CDPs (CDP1 primary).',
    },
    sites: {
      '04': {
        lat: 0.9152,
        lon: 104.5243,
        elevation_m: 15,
        threshold_elevation_m: 14,
        description: 'Touchdown zone, runway 04',
      },
      middle: {
        lat: 0.9226,
        lon: 104.5321,
        elevation_m: 16,
        threshold_elevation_m: null,
        description: 'Mid-point of the runway',
      },
      '22': {
        lat: 0.9301,
        lon: 104.5398,
        elevation_m: 17,
        threshold_elevation_m: 16,
        description: 'Touchdown zone, runway 22',
      },
    },
    components,
    calibrations,
  }
}

let state: State | null = null
function current(): State {
  if (state) return state
  try {
    const s = globalThis.sessionStorage?.getItem(KEY)
    if (s) return (state = JSON.parse(s) as State)
  } catch {
    /* start fresh */
  }
  return (state = seed(Date.now()))
}
function save() {
  try {
    globalThis.sessionStorage?.setItem(KEY, JSON.stringify(current()))
  } catch {
    /* ignore */
  }
}

export const stationMeta = () => current().station
export function setStation(meta: State['station']) {
  current().station = meta
  save()
}
export const siteMeta = (slug: string): SiteMeta =>
  current().sites[slug] ?? {
    lat: null,
    lon: null,
    elevation_m: null,
    threshold_elevation_m: null,
    description: null,
  }
export function setSiteMeta(slug: string, meta: SiteMeta) {
  current().sites[slug] = meta
  save()
}

/** A sensor's record; serial and part numbers only when ``full`` (signed-in users). */
export function componentMeta(site: string, type: string, full: boolean): ComponentMeta {
  const m = current().components[`${site}:${type}`] ?? {
    sensor_type: null,
    manufacturer: null,
    model: null,
    part_number: null,
    serial_number: null,
    installed_on: null,
    firmware: null,
    notes: null,
  }
  if (full) return m
  const { part_number: _p, serial_number: _s, ...pub } = m
  void _p
  void _s
  return pub
}
export function setComponentMeta(site: string, type: string, meta: ComponentMeta) {
  current().components[`${site}:${type}`] = meta
  save()
}

export function calibrations(site: string, type: string): Calibration[] {
  return current()
    .calibrations.filter((c) => c.site === site && c.type === type)
    .sort((a, b) => b.date.localeCompare(a.date) || b.id - a.id)
    .map(({ site: _s, type: _t, ...c }) => {
      void _s
      void _t
      return c
    })
}

/** Status from the latest record (FR-REG-005): overdue, due soon (within ``window`` days), OK, or unknown. */
export function summary(site: string, type: string, now: number, window: number): CalibrationSummary {
  const latest = calibrations(site, type)[0]
  if (!latest) return { status: 'unknown', last: null, next_due: null, days_left: null }
  const today = Math.floor(now / DAY) * DAY
  const left = Math.round((Date.parse(`${latest.next_due}T00:00:00Z`) - today) / DAY)
  return {
    status: left < 0 ? 'overdue' : left <= window ? 'due_soon' : 'ok',
    last: latest.date,
    next_due: latest.next_due,
    days_left: left,
  }
}

/** Refusal code, or null; fills the next due date from an interval (FR-REG-005, PRD §9.5). */
export function checkCalibration(d: CalibrationDraft, now: number): string | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(d.date ?? '')) return 'invalid_date'
  if (d.date > day(now)) return 'date_in_future'
  if (!d.performed_by?.trim()) return 'performed_by_required'
  if (d.interval_months !== null && d.interval_months !== undefined) {
    if (!Number.isInteger(d.interval_months) || d.interval_months < 1 || d.interval_months > 120)
      return 'invalid_interval'
    d.next_due = addMonths(d.date, d.interval_months)
  }
  if (!d.next_due || !/^\d{4}-\d{2}-\d{2}$/.test(d.next_due)) return 'next_due_required'
  if (d.next_due <= d.date) return 'next_due_before_date'
  return null
}

export function addCalibration(site: string, type: string, d: CalibrationDraft, by: string, now: number) {
  const s = current()
  const c = {
    id: Math.max(0, ...s.calibrations.map((x) => x.id)) + 1,
    component_id: d.component_id,
    site,
    type,
    date: d.date,
    performed_by: d.performed_by.trim(),
    certificate: d.certificate?.trim() || null,
    next_due: d.next_due!,
    interval_months: d.interval_months ?? null,
    notes: d.notes?.trim() || null,
    created_by: by,
    created_at: new Date(now).toISOString(),
    updated_by: null,
    updated_at: null,
  }
  s.calibrations.push(c)
  save()
  return c
}
export function updateCalibration(id: number, d: CalibrationDraft, by: string, now: number) {
  const c = current().calibrations.find((x) => x.id === id)
  if (!c) return null
  Object.assign(c, {
    date: d.date,
    performed_by: d.performed_by.trim(),
    certificate: d.certificate?.trim() || null,
    next_due: d.next_due!,
    interval_months: d.interval_months ?? null,
    notes: d.notes?.trim() || null,
    updated_by: by,
    updated_at: new Date(now).toISOString(),
  })
  save()
  return c
}
export function removeCalibration(id: number) {
  const s = current()
  const before = s.calibrations.length
  s.calibrations = s.calibrations.filter((x) => x.id !== id)
  save()
  return before !== s.calibrations.length
}
export const calibrationById = (id: number) => current().calibrations.find((x) => x.id === id) ?? null
