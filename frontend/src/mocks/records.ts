// Sample station, site and sensor records, sensor parts and calibration histories (R2.5, R3.7) for dev:sample and
// CI. Calibration dates are relative to today, so each status (overdue, due soon, OK, unknown) stays on screen
// whatever the date. Sensor models are typical AWOS equipment; serial and part numbers are made up.
import type {
  Calibration,
  CalibrationDraft,
  CalibrationSummary,
  ComponentMeta,
  Part,
  PartDraft,
  SiteMeta,
  StationMeta,
} from '@/api/types'
import { SYSTEM } from './data'
import { addMonths } from '@/utils/time'
import { usualParts } from '@/utils/parts'

type StoredCalibration = Omit<Calibration, 'part'> & { site: string; type: string; part_id: number | null }
type StoredPart = Required<Omit<Part, 'part_number' | 'serial_number' | 'notes' | 'removed_reason'>> & {
  part_number: string | null
  serial_number: string | null
  notes: string | null
  removed_reason: string | null
  site: string
  type: string
}
interface State {
  station: Omit<StationMeta, 'name' | 'icao'>
  sites: Record<string, SiteMeta>
  components: Record<string, ComponentMeta> // "site:type"
  parts: StoredPart[]
  calibrations: StoredCalibration[]
}

const KEY = 'simola.mock.records.v2'
const DAY = 86_400_000
const day = (ms: number) => new Date(ms).toISOString().slice(0, 10)

/** sensor type of each component type (the sensor as a whole) */
const SENSOR_TYPE: Record<string, string> = {
  DCP: 'Data collection platform',
  ATRH: 'Temperature and humidity',
  BARO: 'Digital barometer',
  ANEM: 'Ultrasonic wind sensor',
  RVR: 'Transmissometer',
  CEL: 'Ceilometer',
  PWX: 'Present weather sensor',
  RAIN: 'Tipping bucket rain gauge',
  SOLR: 'Pyranometer',
  LIGH: 'Thunderstorm sensor',
}
/** part name: manufacturer, model, part number */
const PART_MODELS: Record<string, [string, string | null, string | null]> = {
  'Data logger': ['Vaisala', 'AWS310', 'AWS310-SITE'],
  'Power supply': ['Vaisala', null, null],
  Thermohygrometer: ['Vaisala', 'HMP155', 'HMP155E'],
  MARS: ['Vaisala', null, null],
  Barometer: ['Vaisala', 'PTB330', 'PTB330A1A2'],
  Quadplate: ['Vaisala', null, null],
  'Wind sensor': ['Vaisala', 'WMT700', 'WMT703'],
  'Transmitter 1': ['Vaisala', 'LT31', 'LT31-TX'],
  'Transmitter 2': ['Vaisala', 'LT31', 'LT31-TX'],
  'Receiver 1': ['Vaisala', 'LT31', 'LT31-RX'],
  'Receiver 2': ['Vaisala', 'LT31', 'LT31-RX'],
  Logger: ['Vaisala', null, null],
  ALS: ['Vaisala', 'LM21', 'LM21'],
  Ceilometer: ['Vaisala', 'CL31', 'CL31-AAA'],
  Blower: ['Vaisala', null, null],
  'Present weather sensor': ['Vaisala', 'PWD22', 'PWD22-W'],
  'Rain gauge': ['Vaisala', 'RG13H', 'RG13H-02'],
  Pyranometer: ['Kipp & Zonen', 'CMP6', 'CMP6-0302'],
  'Lightning detector': ['Vaisala', 'TSS928', 'TSS928-A'],
}
/** sample gaps and history: a part not recorded yet, and parts replaced */
const NOT_RECORDED = new Set(['22:RVR:Receiver 2'])
const REPLACED: Record<string, { on: string; note: string }> = {
  '04:RVR:Receiver 1': {
    on: '2026-05-10',
    note: 'Window contaminated beyond cleaning; swapped for the spare.',
  },
  '22:CEL:Blower': { on: '2025-09-02', note: 'Fan bearing noise.' },
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
  const parts: StoredPart[] = []
  let n = 0
  let componentId = 0
  const at = new Date(now).toISOString()
  for (const s of SYSTEM.sites)
    for (const c of s.components) {
      componentId++
      const installed = c.type === 'SOLR' ? '2026-01-15' : '2019-08-14'
      components[`${s.slug}:${c.type}`] = {
        sensor_type: SENSOR_TYPE[c.type] ?? null,
        installed_on: installed,
        notes: s.slug === '22' && c.type === 'CEL' ? 'Window heater replaced in 2025.' : null,
      }
      for (const role of usualParts(c.type, c.fields)) {
        if (NOT_RECORDED.has(`${s.slug}:${c.type}:${role}`)) continue
        const [manufacturer, model, partNumber] = PART_MODELS[role] ?? [null, null, null]
        const part = (installedOn: string, removedOn: string | null, reason: string | null): StoredPart => ({
          id: parts.length + 1,
          component_id: componentId,
          site: s.slug,
          type: c.type,
          role,
          manufacturer,
          model,
          part_number: partNumber,
          serial_number: `K${(4710000 + ++n * 7919).toString()}`,
          firmware: role === 'Data logger' ? '7.80.3' : null,
          installed_on: installedOn,
          removed_on: removedOn,
          removed_reason: reason,
          replaces: null,
          replaced_by: null,
          notes: null,
          created_by: 'records-import',
          created_at: at,
          updated_by: null,
          updated_at: null,
        })
        const swap = REPLACED[`${s.slug}:${c.type}:${role}`]
        if (swap) {
          const old = part(installed, swap.on, swap.note)
          parts.push(old)
          const next = part(swap.on, null, null)
          next.replaces = old.id
          old.replaced_by = next.id
          parts.push(next)
        } else parts.push(part(installed, null, null))
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
        part_id:
          parts.find((p) => p.component_id === index + 1 && p.removed_on === null && p.role !== 'MARS')?.id ??
          null,
        date: day(at),
        performed_by: id % 2 ? 'BMKG Calibration Laboratory' : 'Vaisala service partner',
        certificate: `CAL/${new Date(at).getUTCFullYear()}/${String(100 + id * 37).padStart(4, '0')}`,
        next_due: day(today + next * DAY),
        interval_months: Math.round((next - last) / 30.4) === 12 ? 12 : null,
        // calibrations of the last two months still wait for their certificate
        validated_on: last >= -61 ? null : day(at + 4 * DAY),
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
    parts,
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

/** A sensor's own record (the sensor as a whole). */
export function componentMeta(site: string, type: string): ComponentMeta {
  return current().components[`${site}:${type}`] ?? { sensor_type: null, installed_on: null, notes: null }
}
export function setComponentMeta(site: string, type: string, meta: ComponentMeta) {
  current().components[`${site}:${type}`] = {
    sensor_type: meta.sensor_type,
    installed_on: meta.installed_on,
    notes: meta.notes,
  }
  save()
}

// ---- parts (R3.7) ----------------------------------------------------------------------------------------
function publicPart(p: StoredPart, full: boolean): Part {
  const { site: _s, type: _t, ...part } = p
  void _s
  void _t
  if (full) return part
  // the public answer leaves out numbers, notes, removal reasons and who changed the part (as the API does)
  const pub: Part = { ...part }
  for (const k of [
    'part_number',
    'serial_number',
    'notes',
    'removed_reason',
    'created_by',
    'created_at',
    'updated_by',
    'updated_at',
  ] as const)
    delete pub[k]
  return pub
}
/** A sensor's parts: installed ones, or every one ever recorded with ``removed``. Numbers only when ``full``. */
export function parts(site: string, type: string, full: boolean, removed = false): Part[] {
  return current()
    .parts.filter((p) => p.site === site && p.type === type && (removed || p.removed_on === null))
    .map((p) => publicPart(p, full))
}
export const partById = (id: number) => current().parts.find((p) => p.id === id) ?? null

const clean = (s: string | null | undefined) => s?.trim() || null
/** Refusal code, or null. */
export function checkPart(d: PartDraft, now: number): string | null {
  if (!d.role?.trim()) return 'role_required'
  if (d.role.trim().length > 60) return 'role_too_long'
  if (d.installed_on && !/^\d{4}-\d{2}-\d{2}$/.test(d.installed_on)) return 'invalid_date'
  if (d.installed_on && d.installed_on > day(now)) return 'date_in_future'
  return null
}
export function checkRemoval(p: StoredPart, removedOn: string, now: number): string | null {
  if (p.removed_on) return 'part_already_removed'
  if (!/^\d{4}-\d{2}-\d{2}$/.test(removedOn ?? '')) return 'invalid_date'
  if (removedOn > day(now)) return 'date_in_future'
  if (p.installed_on && removedOn < p.installed_on) return 'removed_before_installed'
  return null
}
export function addPart(
  componentId: number,
  site: string,
  type: string,
  d: PartDraft,
  by: string,
  now: number,
) {
  const s = current()
  const part: StoredPart = {
    id: Math.max(0, ...s.parts.map((x) => x.id)) + 1,
    component_id: componentId,
    site,
    type,
    role: d.role.trim().replace(/\s+/g, ' '),
    manufacturer: clean(d.manufacturer),
    model: clean(d.model),
    part_number: clean(d.part_number),
    serial_number: clean(d.serial_number),
    firmware: clean(d.firmware),
    installed_on: d.installed_on || null,
    removed_on: null,
    removed_reason: null,
    replaces: null,
    replaced_by: null,
    notes: clean(d.notes),
    created_by: by,
    created_at: new Date(now).toISOString(),
    updated_by: null,
    updated_at: null,
  }
  s.parts.push(part)
  save()
  return part
}
export function updatePart(id: number, d: PartDraft, by: string, now: number) {
  const p = partById(id)
  if (!p) return null
  Object.assign(p, {
    role: d.role.trim().replace(/\s+/g, ' '),
    manufacturer: clean(d.manufacturer),
    model: clean(d.model),
    part_number: clean(d.part_number),
    serial_number: clean(d.serial_number),
    firmware: clean(d.firmware),
    installed_on: d.installed_on || null,
    notes: clean(d.notes),
    updated_by: by,
    updated_at: new Date(now).toISOString(),
  })
  save()
  return p
}
export function removePart(id: number, removedOn: string, notes: string | null, by: string, now: number) {
  const p = partById(id)!
  Object.assign(p, {
    removed_on: removedOn,
    removed_reason: clean(notes),
    updated_by: by,
    updated_at: new Date(now).toISOString(),
  })
  save()
  return p
}
export function replacePart(
  id: number,
  removedOn: string,
  notes: string | null,
  d: PartDraft,
  by: string,
  now: number,
) {
  const old = removePart(id, removedOn, notes, by, now)
  const added = addPart(old.component_id, old.site, old.type, d, by, now)
  added.replaces = old.id
  old.replaced_by = added.id
  save()
  return { removed: old, added }
}
export const publicPartOf = publicPart

export function calibrations(site: string, type: string): Calibration[] {
  const all = current().parts
  return current()
    .calibrations.filter((c) => c.site === site && c.type === type)
    .sort((a, b) => b.date.localeCompare(a.date) || b.id - a.id)
    .map(({ site: _s, type: _t, part_id, ...c }) => {
      void _s
      void _t
      const p = part_id === null ? null : all.find((x) => x.id === part_id)
      return { ...c, part: p ? { id: p.id, role: p.role, serial_number: p.serial_number } : null }
    })
}

/** Status from the latest record (FR-REG-005): overdue, due soon (within ``window`` days), OK, or unknown. */
export function summary(site: string, type: string, now: number, window: number): CalibrationSummary {
  const latest = calibrations(site, type)[0]
  if (!latest)
    return {
      status: 'unknown',
      last: null,
      next_due: null,
      days_left: null,
      validated_on: null,
      pending: false,
    }
  const today = Math.floor(now / DAY) * DAY
  const left = Math.round((Date.parse(`${latest.next_due}T00:00:00Z`) - today) / DAY)
  return {
    status: left < 0 ? 'overdue' : left <= window ? 'due_soon' : 'ok',
    last: latest.date,
    next_due: latest.next_due,
    days_left: left,
    validated_on: latest.validated_on,
    pending: latest.validated_on === null,
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
  if (d.validated_on) {
    if (d.validated_on > day(now)) return 'date_in_future'
    if (d.validated_on < d.date) return 'validated_before_date'
  }
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
    validated_on: d.validated_on || null,
    notes: d.notes?.trim() || null,
    part_id: d.part_id ?? null,
    created_by: by,
    created_at: new Date(now).toISOString(),
    updated_by: null,
    updated_at: null,
  }
  s.calibrations.push(c)
  save()
  return calibrations(site, type).find((x) => x.id === c.id)!
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
    validated_on: d.validated_on || null,
    notes: d.notes?.trim() || null,
    part_id: d.part_id ?? null,
    updated_by: by,
    updated_at: new Date(now).toISOString(),
  })
  save()
  return calibrations(c.site, c.type).find((x) => x.id === c.id)!
}
export function removeCalibration(id: number) {
  const s = current()
  const before = s.calibrations.length
  s.calibrations = s.calibrations.filter((x) => x.id !== id)
  save()
  return before !== s.calibrations.length
}
export const calibrationById = (id: number) => current().calibrations.find((x) => x.id === id) ?? null
