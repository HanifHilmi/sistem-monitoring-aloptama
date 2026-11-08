// Deterministic sample data shaped exactly like the SIMOLA API (design and screenshot work only).
import type {
  Availability,
  KpiResponse,
  MatrixBucket,
  MatrixCell,
  MatrixResponse,
  MatrixRow,
  MinutesResponse,
  OutageCause,
  OutagesResponse,
  SeriesField,
  SeriesResponse,
  StatusResponse,
  SystemInfo,
  SystemSummary,
} from '@/api/types'
import { confirmedSpans, detectedValue, dqState, suspectSpans } from './dqStore'
import { activeSpans, reasonOf } from './flagStore'
import * as sensors from './sensors'

const DAY = 86_400_000
const GRACE = 3
const COVERAGE = Date.UTC(2025, 11, 24, 3, 40)
const n = (en: string, id: string) => ({ en, id })

const COMP_NAMES: Record<string, [string, string]> = {
  DCP: ['Data Collection Platform', 'Data Collection Platform'],
  ATRH: ['Air Temperature & Humidity', 'Suhu & Kelembapan Udara'],
  BARO: ['Barometer', 'Barometer'],
  ANEM: ['Anemometer', 'Anemometer'],
  RVR: ['Runway Visual Range', 'Runway Visual Range'],
  CEL: ['Ceilometer', 'Ceilometer'],
  PWX: ['Present Weather Sensor', 'Sensor Cuaca Saat Ini'],
  RAIN: ['Rain Gauge', 'Penakar Hujan'],
  SOLR: ['Solar Radiation Sensor', 'Sensor Radiasi Matahari'],
  LIGH: ['Lightning Detector', 'Detektor Petir'],
}
const FIELDS: Record<string, string[]> = {
  ATRH: ['TEMP', 'DEWP', 'RH'],
  BARO: ['QNH', 'DA'],
  ANEM: ['WS', 'WD', 'WGS', 'WGD'],
  CEL: ['LR1', 'SKY'],
  PWX: ['PW', 'RA'],
  RAIN: ['RA'],
  SOLR: ['SOL'],
  LIGH: ['LTX'],
  DCP: [],
}
const MANDATORY: Record<string, string[]> = {
  ATRH: ['TEMP', 'RH'],
  BARO: ['QNH'],
  ANEM: ['WS', 'WD'],
  RVR: ['RVR'],
  CEL: ['LR1'],
  PWX: ['PW'],
  RAIN: ['RA'],
  SOLR: ['SOL'],
  LIGH: ['LTX'],
  DCP: [],
}
const SITE_COMPS: Record<string, string[]> = {
  '04': ['DCP', 'ATRH', 'BARO', 'ANEM', 'RVR', 'CEL', 'PWX'],
  middle: ['DCP', 'ATRH', 'BARO', 'ANEM', 'RAIN', 'SOLR', 'LIGH'],
  '22': ['DCP', 'ATRH', 'BARO', 'ANEM', 'RVR', 'CEL', 'PWX'],
}

export const SYSTEM: SystemInfo = {
  code: 'WIDN-CAT3',
  type: 'AWOS_CAT3',
  kpi_profile: 'sla_ola',
  name: n('AWOS CAT.III WIDN', 'AWOS KAT. III WIDN'),
  icao: 'WIDN',
  coverage_start: new Date(COVERAGE).toISOString(),
  cdps: [
    { code: 'CDP1', preference: 1 },
    { code: 'CDP2', preference: 2 },
  ],
  sites: [
    ['RWY04', '04', '04', n('Runway 04', 'Landasan 04')],
    ['RWYMID', 'M', 'middle', n('Runway Middle', 'Landasan Tengah')],
    ['RWY22', '22', '22', n('Runway 22', 'Landasan 22')],
  ].map(([code, station, slug, name]) => ({
    code: code as string,
    station_code: station as string,
    slug: slug as string,
    name: name as { en: string; id: string },
    components: SITE_COMPS[slug as string]!.map((type) => {
      const fields =
        type === 'RVR'
          ? slug === '04'
            ? ['RVR', 'VIS', 'ALS', 'D/N', 'RLS']
            : ['RVR', 'VIS', 'RLS']
          : FIELDS[type]!
      return {
        type,
        is_dcp: type === 'DCP',
        name: n(...COMP_NAMES[type]!),
        fields,
        mandatory: MANDATORY[type]!.filter((f) => fields.includes(f)),
        in_service_from: null,
        in_service_to: null,
      }
    }),
  })),
  fields: Object.fromEntries(
    (
      [
        ['TEMP', '°C', 'numeric', 'Air temperature', 'Suhu udara'],
        ['DEWP', '°C', 'numeric', 'Dew point', 'Titik embun'],
        ['RH', '%', 'numeric', 'Relative humidity', 'Kelembapan relatif'],
        ['QNH', 'hPa', 'numeric', 'QNH', 'QNH'],
        ['DA', 'ft', 'numeric', 'Density altitude', 'Ketinggian densitas'],
        ['WS', 'kt', 'numeric', 'Wind speed', 'Kecepatan angin'],
        ['WD', '°', 'numeric', 'Wind direction', 'Arah angin'],
        ['WGS', 'kt', 'numeric', 'Gust speed', 'Kecepatan hembusan'],
        ['WGD', '°', 'numeric', 'Gust direction', 'Arah hembusan'],
        ['RVR', 'm', 'numeric', 'Runway visual range', 'Runway visual range'],
        ['VIS', 'm', 'numeric', 'Visibility', 'Jarak pandang'],
        ['ALS', 'cd', 'numeric', 'Ambient light', 'Cahaya latar'],
        ['D/N', null, 'text', 'Day / night', 'Siang / malam'],
        ['RLS', null, 'numeric', 'Runway light setting', 'Pengaturan lampu landasan'],
        ['LR1', '100 ft', 'numeric', 'Cloud base (layer 1)', 'Dasar awan (lapisan 1)'],
        ['SKY', null, 'text', 'Sky condition', 'Kondisi langit'],
        ['PW', null, 'text', 'Present weather', 'Cuaca saat ini'],
        ['RA', 'mm', 'numeric', 'Rainfall', 'Curah hujan'],
        ['SOL', 'W/m²', 'numeric', 'Solar radiation', 'Radiasi matahari'],
        ['LTX', null, 'text', 'Lightning', 'Petir'],
      ] as [string, string | null, 'numeric' | 'text', string, string][]
    ).map(([c, unit, type, en, id]) => [c, { unit, type, name: n(en, id) }]),
  ),
}

// ---- deterministic loss model --------------------------------------------------------------------
function hash(s: string): number {
  let h = 2166136261
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619)
  // murmur3 finaliser so similar keys (consecutive days) do not get similar values
  h ^= h >>> 16
  h = Math.imul(h, 0x85ebca6b)
  h ^= h >>> 13
  h = Math.imul(h, 0xc2b2ae35)
  h ^= h >>> 16
  return (h >>> 0) / 4294967295
}
const dayKey = (t: number) => new Date(t).toISOString().slice(0, 10)

/** Minutes with no CDP data at all on a day (shared by everything). */
function commonLoss(day: string): number {
  const r = hash(`common:${day}`)
  if (day.endsWith('-12') && day.startsWith('2026-10')) return 41 // a real-looking outage
  return r < 0.55 ? 0 : r < 0.85 ? 1 : r < 0.97 ? 3 : 9
}
function cdpExtra(cdp: string, day: string): number {
  const r = hash(`${cdp}:${day}`)
  return r < 0.6 ? 0 : r < 0.9 ? Math.round(r * 6) : Math.round(r * 18)
}
function compExtra(site: string, type: string, day: string): number {
  if (type === 'DCP') return 0
  const r = hash(`${site}:${type}:${day}`)
  if (site === '22' && type === 'CEL' && (day === '2026-10-20' || day === '2026-11-02')) return 86
  if (site === 'middle' && type === 'ATRH' && day.endsWith('-03')) return 18
  if (site === '04' && type === 'PWX' && day >= '2026-10-26' && day <= '2026-10-28') return 140
  return r < 0.82 ? 0 : r < 0.97 ? 2 : 7
}

function expectedFor(dayStart: number, now: number): number {
  const evalEnd = Math.floor(now / 60_000) * 60_000 - GRACE * 60_000
  const a = Math.max(dayStart, COVERAGE)
  const b = Math.min(dayStart + DAY, evalEnd)
  return Math.max(0, Math.floor((b - a) / 60_000))
}

type Scope =
  { kind: 'sla' } | { kind: 'cdp'; cdp: string } | { kind: 'component'; site: string; type: string }

/** A day's valid and expected minutes before manual flags. */
function baseCounts(scope: Scope, dayStart: number, now: number): [number, number] {
  const e = expectedFor(dayStart, now)
  if (!e) return [0, 0]
  const k = dayKey(dayStart)
  const frac = e / 1440
  let lost = commonLoss(k)
  if (scope.kind === 'cdp') lost += cdpExtra(scope.cdp, k)
  if (scope.kind === 'component') lost += compExtra(scope.site, scope.type, k)
  lost = Math.min(e, Math.round(lost * frac))
  return [e - lost, e]
}

/** Flagged or confirmed-bad minutes that were otherwise valid count as lost, exactly those and nothing more. */
function dayCounts(scope: Scope, dayStart: number, now: number): [number, number] {
  const [v, e] = baseCounts(scope, dayStart, now)
  const invalid = invalidPieces(scope, dayStart, now).reduce((n, p) => n + p.len, 0)
  return [v - invalid, e]
}

const avail = (v: number, e: number): Availability => ({
  valid: v,
  expected: e,
  missing: e - v,
  pct: e ? Math.round((v / e) * 10000) / 100 : null,
})

function periodDays(from: number, to: number): number[] {
  const out: number[] = []
  for (let d = Math.floor(from / DAY) * DAY; d < to; d += DAY) out.push(d)
  return out
}

function sum(scope: Scope, days: number[], now: number): [number, number] {
  let v = 0
  let e = 0
  for (const d of days) {
    const [a, b] = dayCounts(scope, d, now)
    v += a
    e += b
  }
  return [v, e]
}

function siteSum(site: string, days: number[], now: number): [number, number] {
  let v = 0
  let e = 0
  for (const type of SITE_COMPS[site]!) {
    const [a, b] = sum({ kind: 'component', site, type }, days, now)
    v += a
    e += b
  }
  return [v, e]
}

function ola(days: number[], now: number): number | null {
  const r = Object.keys(SITE_COMPS)
    .map((s) => siteSum(s, days, now))
    .filter(([, e]) => e > 0)
    .map(([v, e]) => v / e)
  return r.length ? Math.round((r.reduce((a, b) => a + b, 0) / r.length) * 10000) / 100 : null
}

export function kpis(from: number, to: number, now: number): KpiResponse {
  const days = periodDays(from, to)
  const sites = Object.keys(SITE_COMPS).map((site) => ({
    code: site,
    slug: site,
    availability: avail(...siteSum(site, days, now)),
    components: SITE_COMPS[site]!.map((type) => ({
      type,
      is_dcp: type === 'DCP',
      availability: avail(...sum({ kind: 'component', site, type }, days, now)),
    })),
  }))
  const pooled = sites.reduce<[number, number]>(
    (a, s) => [a[0] + s.availability.valid, a[1] + s.availability.expected],
    [0, 0],
  )
  const [sv, se] = sum({ kind: 'sla' }, days, now)
  return {
    system: SYSTEM.code,
    period: {
      from: new Date(from).toISOString(),
      to: new Date(to).toISOString(),
      evaluated_from: new Date(from).toISOString(),
      evaluated_to: new Date(Math.min(to, now)).toISOString(),
      as_of: new Date(now).toISOString(),
      open: to > now,
      coverage_start: SYSTEM.coverage_start,
    },
    sla: avail(sv, se),
    cdps: ['CDP1', 'CDP2'].map((cdp) => {
      const [v, e] = sum({ kind: 'cdp', cdp }, days, now)
      return {
        code: cdp,
        uptime: avail(v, e),
        reachability: {
          reachable: e,
          sampled: e,
          pct: e ? 100 : null,
          probe_coverage_pct: e ? 100 : null,
          legacy_minutes: 0,
        },
      }
    }),
    sites,
    ola: { pct: ola(days, now) },
    pooled: avail(pooled[0], pooled[1]),
  }
}

function bucketStart(t: number, bucket: MatrixBucket): number {
  const d = new Date(t)
  if (bucket === 'day') return t
  if (bucket === 'week') return t - ((d.getUTCDay() + 6) % 7) * DAY
  return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), 1)
}

export function matrix(from: number, to: number, bucket: MatrixBucket, now: number): MatrixResponse {
  const days = periodDays(from, to)
  const groups = new Map<number, number[]>()
  for (const d of days) {
    const b = Math.max(bucketStart(d, bucket), from)
    groups.set(b, [...(groups.get(b) ?? []), d])
  }
  const buckets = [...groups.entries()]
  const iso = (t: number) => new Date(t).toISOString().slice(0, 10)
  const cell =
    (fn: (ds: number[]) => [number, number]) =>
    (ds: number[]): MatrixCell =>
      avail(...fn(ds))
  const row = (
    key: string,
    kind: MatrixRow['kind'],
    f: (ds: number[]) => MatrixCell,
    meta: Partial<MatrixRow> = {},
  ): MatrixRow => ({
    key,
    kind,
    ...meta,
    cells: buckets.map(([, ds]) => f(ds)),
    total: f(days),
  })
  const rows: MatrixRow[] = [
    row(
      'sla',
      'sla',
      cell((ds) => sum({ kind: 'sla' }, ds, now)),
    ),
    ...['CDP1', 'CDP2'].map((cdp) =>
      row(
        `cdp:${cdp}`,
        'cdp',
        cell((ds) => sum({ kind: 'cdp', cdp }, ds, now)),
        { cdp },
      ),
    ),
    row('ola', 'ola', (ds) => ({ pct: ola(ds, now) })),
  ]
  for (const site of Object.keys(SITE_COMPS)) {
    rows.push(
      row(
        `site:${site}`,
        'site',
        cell((ds) => siteSum(site, ds, now)),
        { site },
      ),
    )
    for (const type of SITE_COMPS[site]!) {
      rows.push(
        row(
          `component:${site}:${type}`,
          'component',
          cell((ds) => sum({ kind: 'component', site, type }, ds, now)),
          { site, type, is_dcp: type === 'DCP' },
        ),
      )
    }
  }
  return {
    system: SYSTEM.code,
    period: {
      from: new Date(from).toISOString(),
      to: new Date(to).toISOString(),
      evaluated_to: new Date(Math.min(to, now)).toISOString(),
      as_of: new Date(now).toISOString(),
      open: to > now,
    },
    bucket,
    buckets: buckets.map(([b, ds]) => ({ start: iso(b), end: iso(ds[ds.length - 1]! + DAY) })),
    rows,
  }
}

function parseScope(scope: string): Scope {
  const parts = scope.split(':')
  if (parts[0] === 'cdp') return { kind: 'cdp', cdp: parts[1]! }
  if (parts[0] === 'component') return { kind: 'component', site: parts[1]!, type: parts[2]! }
  return { kind: 'sla' }
}

interface Piece {
  at: number // minute of the day
  len: number
  cause: 'cdp_no_data' | 'field_missing' | 'flagged' | 'detection'
  /** flagged: the flag; detection: the confirmed detection */
  ref?: number
}

/**
 * Where a scope lost its minutes on a day: the loss shared by everything (no CDP data), then the scope's own.
 * Pieces never overlap and stay inside the evaluated minutes, so they add up to exactly what the matrix lost.
 */
function basePieces(s: Scope, dayStart: number, now: number): Piece[] {
  const e = expectedFor(dayStart, now)
  const [v] = baseCounts(s, dayStart, now)
  const day = dayKey(dayStart)
  const lost = e - v
  const common = Math.min(lost, Math.round(commonLoss(day) * (e / 1440)))
  const pieces: Piece[] = []
  let c0 = 0
  if (common) {
    c0 = Math.max(0, Math.min(day.endsWith('-12') ? 638 : 30, e - common))
    pieces.push({ at: c0, len: common, cause: 'cdp_no_data' })
  }
  const rest = lost - common
  if (rest > 0) {
    const cause = s.kind === 'component' ? 'field_missing' : 'cdp_no_data'
    const key = s.kind === 'component' ? `${s.site}:${s.type}` : s.kind === 'cdp' ? s.cdp : 'sla'
    let at = Math.min(Math.floor(hash(key + day) * Math.max(1, e - rest - 60)) + 60, e - rest)
    const c1 = c0 + common
    if (common && at < c1 && at + rest > c0) at = c1 + rest <= e ? c1 : c0 - rest
    if (at >= 0) pieces.push({ at, len: rest, cause })
    else {
      // no single free stretch is long enough: fill after the shared loss, then before it
      const after = e - c1
      pieces.push({ at: c1, len: after, cause }, { at: c0 - (rest - after), len: rest - after, cause })
    }
  }
  return pieces.filter((p) => p.len > 0).sort((a, b) => a.at - b.at)
}

/**
 * Minutes of a component's day under an active flag or a confirmed detection on a mandatory field that would
 * otherwise be valid. Minutes already lost for another reason keep that cause; flags come before detections and
 * older before newer, so a minute is never counted twice (PRD E9).
 */
function invalidPieces(s: Scope, dayStart: number, now: number): Piece[] {
  if (s.kind !== 'component' || s.type === 'DCP') return []
  const spans = [
    ...activeSpans(s.site, s.type, dayStart, dayStart + DAY).map((x) => ({ ...x, key: x.id })),
    ...confirmedSpans(s.site, s.type, dayStart, dayStart + DAY).map((x) => ({ ...x, key: -x.id })),
  ]
  if (!spans.length) return []
  const e = expectedFor(dayStart, now)
  const LOST = 1 << 30 // lost for another reason; otherwise 0 = valid, > 0 a flag, < 0 a detection
  const taken = new Int32Array(e)
  for (const p of basePieces(s, dayStart, now)) taken.fill(LOST, p.at, Math.min(e, p.at + p.len))
  for (const sp of spans) {
    const a = Math.max(0, Math.floor((sp.start - dayStart) / 60_000))
    const b = Math.min(e, Math.ceil((sp.end - dayStart) / 60_000))
    for (let i = a; i < b; i++) if (taken[i] === 0) taken[i] = sp.key
  }
  const pieces: Piece[] = []
  for (let i = 0; i < e;) {
    const k = taken[i]!
    let j = i + 1
    while (j < e && taken[j] === k) j++
    if (k !== 0 && k !== LOST)
      pieces.push({ at: i, len: j - i, cause: k > 0 ? 'flagged' : 'detection', ref: Math.abs(k) })
    i = j
  }
  return pieces
}

function dayPieces(s: Scope, dayStart: number, now: number): Piece[] {
  return [...basePieces(s, dayStart, now), ...invalidPieces(s, dayStart, now)].sort((a, b) => a.at - b.at)
}

const detectionRef = (id: number) => {
  const d = dqState().detections.find((x) => x.id === id)
  return { id, field: d?.field ?? '?', type: d?.type ?? 'range' }
}

/** One day of a scope, minute by minute. Suspect minutes ('s') are for signed-in users only (`viewer`). */
export function minutes(day: string, scope: string, now: number, viewer = false): MinutesResponse {
  const start = Date.parse(`${day}T00:00:00Z`)
  const e = expectedFor(start, now)
  const codes: string[] = Array.from({ length: 1440 }, (_, i) => (i < e ? 'v' : 'u'))
  const ids = new Int32Array(1440)
  const CODE = { field_missing: 'f', flagged: 'g', detection: 'd', cdp_no_data: 'n' } as const
  const sc = parseScope(scope)
  for (const p of dayPieces(sc, start, now))
    for (let i = p.at; i < p.at + p.len; i++) {
      codes[i] = CODE[p.cause]
      ids[i] = p.ref ?? 0
    }
  if (viewer && sc.kind === 'component')
    for (const d of suspectSpans(sc.site, sc.type, start, start + DAY)) {
      const a = Math.max(0, (Date.parse(d.start) - start) / 60_000)
      const b = Math.min(1440, (Date.parse(d.end) - start) / 60_000)
      for (let i = a; i < b; i++) if (codes[i] === 'v') codes[i] = 's'
    }
  const str = codes.join('')
  const intervals: MinutesResponse['intervals'] = []
  for (let i = 0; i < str.length;) {
    const c = str[i]!
    if (c === 'f' || c === 'n' || c === 'g' || c === 'd') {
      let j = i
      while (str[j] === c && ids[j] === ids[i]) j++
      intervals.push({
        start: new Date(start + i * 60_000).toISOString(),
        end: new Date(start + j * 60_000).toISOString(),
        minutes: j - i,
        cause: c === 'f' ? 'field_missing' : c === 'g' ? 'flagged' : c === 'd' ? 'detection' : 'no_data',
        ...(c === 'g' ? { flags: [{ id: ids[i]!, reason: reasonOf(ids[i]!) }] } : {}),
        ...(c === 'd' ? { detections: [detectionRef(ids[i]!)] } : {}),
      })
      i = j
    } else i++
  }
  intervals.sort((a, b) => b.minutes - a.minutes)
  const valid = [...str].filter((c) => c === 'v' || c === 's').length
  return { scope, day, codes: str, valid, expected: e, intervals }
}

export const MAX_OUTAGE_SPAN = 93 * DAY

/** Outage breakdown shaped like /outages: identical intervals of several components are listed once. */
export function outages(
  from: number,
  to: number,
  scope: string,
  now: number,
  limit: number,
): OutagesResponse {
  type Member = { site: string; component: string; fields?: string[] }
  const scopes: { s: Scope; member?: Member }[] = []
  const comps = (site: string) =>
    SITE_COMPS[site]!.map((type) => ({
      s: { kind: 'component', site, type } as Scope,
      member: { site, component: type },
    }))
  if (scope === 'ola') scopes.push(...Object.keys(SITE_COMPS).flatMap(comps))
  else if (scope.startsWith('site:')) scopes.push(...comps(scope.slice(5)))
  else {
    const one = parseScope(scope)
    scopes.push({
      s: one,
      member: one.kind === 'component' ? { site: one.site, component: one.type } : undefined,
    })
  }
  const sitesInfo = SYSTEM.sites
  const groups = new Map<
    string,
    { start: number; end: number; cause: OutageCause; ref?: number; members: Member[] }
  >()
  const byCause: Record<OutageCause, number> = {
    cdp_no_data: 0,
    no_record: 0,
    field_missing: 0,
    flagged: 0,
    detection: 0,
  }
  let valid = 0
  let expected = 0
  const evalEnd = Math.floor(now / 60_000) * 60_000 - GRACE * 60_000
  for (const d of periodDays(from, to)) {
    for (const { s, member } of scopes) {
      const [v, e] = dayCounts(s, d, now)
      valid += v
      expected += e
      for (const p of dayPieces(s, d, now)) {
        const start = d + p.at * 60_000
        const end = start + p.len * 60_000
        const key = `${start}|${end}|${p.cause}|${p.ref ?? ''}`
        const g = groups.get(key) ?? { start, end, cause: p.cause, ref: p.ref, members: [] }
        if (member && s.kind === 'component') {
          const fields =
            sitesInfo.find((x) => x.slug === s.site)?.components.find((c) => c.type === s.type)?.mandatory ??
            []
          g.members.push(
            p.cause === 'field_missing'
              ? {
                  ...member,
                  fields: fields.length ? [fields[Math.floor(hash(key + s.type) * fields.length)]!] : [],
                }
              : member,
          )
        }
        groups.set(key, g)
        byCause[p.cause] += p.len
      }
    }
  }
  const list = [...groups.values()].sort(
    (a, b) => b.end - b.start - (a.end - a.start) || b.members.length - a.members.length || a.start - b.start,
  )
  return {
    system: SYSTEM.code,
    scope,
    period: {
      from: new Date(from).toISOString(),
      to: new Date(to).toISOString(),
      evaluated_from: new Date(Math.max(from, COVERAGE)).toISOString(),
      evaluated_to: new Date(Math.min(to, evalEnd)).toISOString(),
      as_of: new Date(now).toISOString(),
      open: to > evalEnd,
    },
    availability: avail(valid, expected),
    by_cause: byCause,
    intervals_total: list.length,
    truncated: list.length > limit,
    intervals: list.slice(0, limit).map((g) => {
      const minutes = (g.end - g.start) / 60_000
      return {
        start: new Date(g.start).toISOString(),
        end: new Date(g.end).toISOString(),
        minutes,
        cause: g.cause,
        lost_minutes: minutes * Math.max(1, g.members.length),
        ongoing: to > evalEnd && g.end >= evalEnd,
        ...(g.members.length ? { components: g.members } : {}),
        ...(g.ref && g.cause === 'flagged' ? { flags: [{ id: g.ref, reason: reasonOf(g.ref) }] } : {}),
        ...(g.ref && g.cause === 'detection' ? { detections: [detectionRef(g.ref)] } : {}),
      }
    }),
  }
}

export function status(now: number): StatusResponse {
  const last = new Date(Math.floor(now / 60_000) * 60_000 - 2 * 60_000).toISOString()
  return {
    generated_at: new Date(now).toISOString(),
    grace_minutes: GRACE,
    ingestion_stale: false,
    ingestion: ['CDP1', 'CDP2'].map((cdp) => ({
      cdp,
      available: true,
      stale: false,
      lag_min: 0.6,
      last_record_time: last,
    })),
    cdps: ['CDP1', 'CDP2'].map((code) => ({
      code,
      data_flow: 'producing',
      last_data_minute: last,
      reachability: 'reachable',
      rtt_ms: 7.2,
    })),
    sites: SYSTEM.sites.map((s) => ({
      code: s.code,
      slug: s.slug,
      last_data_minute: last,
      no_data: false,
      components_online: s.components.length - (s.slug === '04' ? 1 : 0),
      components_total: s.components.length,
      components: s.components.map((c) => ({
        type: c.type,
        is_dcp: c.is_dcp,
        status: s.slug === '04' && c.type === 'PWX' ? 'field_missing' : 'valid',
        last_valid_minute: last,
      })),
    })),
    last_data_minute: last,
  } as StatusResponse
}

// ---- sensor series -------------------------------------------------------------------------------
function wave(t: number, period: number, phase = 0) {
  return Math.sin(((t / 3_600_000 + phase) / period) * 2 * Math.PI)
}
function noise(t: number, key: string) {
  return hash(`${key}:${Math.floor(t / 60_000)}`) - 0.5
}
const LOCAL = 7 // WIB, for day/night shapes only

function numeric(code: string, t: number): number | null {
  const h = ((new Date(t).getUTCHours() + LOCAL) % 24) + new Date(t).getUTCMinutes() / 60
  const day = Math.max(0, Math.sin(((h - 6) / 12) * Math.PI))
  switch (code) {
    case 'TEMP':
      return Math.round((25 + 5.5 * day + noise(t, 'T') * 0.4) * 10) / 10
    case 'DEWP':
      return Math.round((24.2 + 0.8 * wave(t, 24, 3) + noise(t, 'D') * 0.3) * 10) / 10
    case 'RH':
      return Math.round(97 - 24 * day + noise(t, 'R') * 2)
    case 'QNH':
      return Math.round((1011.5 + 1.6 * wave(t, 12, 2) + noise(t, 'Q') * 0.2) * 10) / 10
    case 'DA':
      return Math.round(1600 + 650 * day + noise(t, 'A') * 40)
    case 'WS':
      return Math.max(0, Math.round(3 + 6 * day + noise(t, 'W') * 5))
    case 'WD':
      return Math.round((((90 + 60 * wave(t, 30, 1) + noise(t, 'WD') * 50) % 360) + 360) % 360)
    case 'WGS':
      return hash(`g:${Math.floor(t / 60_000)}`) > 0.995 ? 18 : 0
    case 'WGD':
      return hash(`g:${Math.floor(t / 60_000)}`) > 0.995 ? 120 : 0
    case 'RVR':
      return Math.round(9000 + 7000 * day + noise(t, 'RVR') * 2500)
    case 'VIS':
      return Math.round(10000 + 8000 * day + noise(t, 'V') * 2000)
    case 'ALS':
      return Math.round(6000 * day + 5)
    case 'RLS':
      return day > 0.1 ? 0 : 3
    case 'LR1':
      return hash(`c:${Math.floor(t / 1_800_000)}`) > 0.55
        ? Math.round(15 + hash(`cb:${Math.floor(t / 600_000)}`) * 30)
        : 0
    case 'RA': {
      const shower = hash(`ra:${Math.floor(t / 7_200_000)}`) > 0.9
      return shower ? Math.round(hash(`r:${Math.floor(t / 60_000)}`) * 8) / 10 : 0
    }
    case 'SOL':
      return Math.round(980 * day * (0.75 + 0.25 * hash(`s:${Math.floor(t / 900_000)}`)))
  }
  return null
}
/** A sample sensor's minute values over [from, to), as the rules see them (R2.4 history and dry runs). */
export function sampleValues(
  site: string,
  type: string,
  code: string,
  from: number,
  to: number,
): (number | null)[] {
  const out: (number | null)[] = []
  for (let t = from; t < to; t += 60_000) out.push(detectedValue(site, type, code, t, numeric(code, t)))
  return out
}

function textVal(code: string, t: number): string | null {
  const h = (new Date(t).getUTCHours() + LOCAL) % 24
  const block = Math.floor(t / 2_700_000)
  switch (code) {
    case 'D/N':
      return h >= 6 && h < 18 ? 'D' : 'N'
    case 'SKY': {
      const r = hash(`c:${Math.floor(t / 1_800_000)}`)
      if (r < 0.45) return 'NCD'
      if (r < 0.48) return 'VV005'
      return ['FEW018', 'SCT017 BKN080', 'BKN016 OVC120', 'FEW020 SCT090 BKN220', 'SCT025CB BKN100'][
        block % 5
      ]!
    }
    case 'PW': {
      const r = hash(`pw:${block}`)
      return r > 0.96 ? 'TSRA' : r > 0.93 ? '-RA' : r > 0.91 ? 'VCTS' : r > 0.86 ? 'BR' : r > 0.83 ? 'HZ' : ''
    }
    case 'LTX': {
      const r = hash(`l:${block}`)
      return r > 0.975
        ? 'TS at Airport - LTG DSNT ALQDS'
        : r > 0.955
          ? 'TS in Vicinity - LTG DSNT NE AND E'
          : r > 0.93
            ? 'LTG DSNT W'
            : ''
    }
  }
  return null
}

/** One field's sample value in the minute starting at ``t`` (the 1-minute export). */
export function minuteValue(slug: string, type: string, code: string, t: number): number | string | null {
  const info = SYSTEM.fields[code]
  if (!info) return null
  return info.type === 'numeric' ? detectedValue(slug, type, code, t, numeric(code, t)) : textVal(code, t)
}

export function series(slug: string, type: string, from: number, to: number, now: number): SeriesResponse {
  const comp = SYSTEM.sites.find((s) => s.slug === slug)!.components.find((c) => c.type === type)!
  const end = Math.min(to, now)
  const total = Math.max(1, Math.floor((end - from) / 60_000))
  const step = Math.max(1, Math.ceil(total / 600))
  const pwBroken = slug === '04' && type === 'PWX'
  const allTs = Array.from({ length: total }, (_, i) => from + i * 60_000)
  const raw: Record<string, (number | string | null)[]> = {}
  const fields: SeriesField[] = comp.fields.map((code) => {
    const info = SYSTEM.fields[code]!
    const ts: number[] = []
    const vs: (number | string | null)[] = []
    const all: (number | string | null)[] = []
    let last: { time: string; value: number | string } | null = null
    for (let i = 0; i < total; i++) {
      const t = from + i * 60_000
      let v: number | string | null =
        info.type === 'numeric' ? detectedValue(slug, type, code, t, numeric(code, t)) : textVal(code, t)
      if (pwBroken && code === 'PW' && end - t < 3_600_000) v = null
      all.push(v)
      if (v !== null) last = { time: new Date(t).toISOString(), value: v }
      if (i % step === 0) {
        ts.push(t)
        vs.push(v)
      }
    }
    raw[code] = all
    const cloudBase = code === 'LR1'
    const nums = all.filter((x): x is number => typeof x === 'number' && !(cloudBase && x === 0))
    const base = { code, unit: info.unit, type: info.type, mandatory: comp.mandatory.includes(code) }
    const stats = {
      last,
      count: cloudBase ? nums.length : all.filter((x) => x !== null).length,
      ...(cloudBase ? { zero_minutes: all.filter((x) => x === 0).length } : {}),
      ...(info.type === 'numeric' && nums.length
        ? {
            min: Math.min(...nums),
            max: Math.max(...nums),
            mean: Math.round((nums.reduce((a, b) => a + b, 0) / nums.length) * 10) / 10,
          }
        : {}),
    }
    if (code === 'WGS' || code === 'WGD')
      return { ...base, chart: 'gust' as const, series: { t: [], v: [], downsampled: false }, stats }
    if (code === 'WD' || cloudBase)
      return {
        ...base,
        chart: 'dots' as const,
        series: sensors.dots(allTs, all as (number | null)[], total, cloudBase),
        stats,
      }
    if (info.type === 'numeric')
      return {
        ...base,
        chart: 'line' as const,
        series: { t: ts, v: vs as (number | null)[], downsampled: step > 1 },
        stats,
      }
    const transitions: [number, string | null][] = []
    const counts = new Map<string, number>()
    let missing = 0
    all.forEach((v, i) => {
      if (v === null) missing++
      else counts.set(String(v), (counts.get(String(v)) ?? 0) + 1)
      if (i === 0 || v !== all[i - 1]) transitions.push([from + i * 60_000, v as string | null])
    })
    return {
      ...base,
      text: {
        transitions,
        truncated: false,
        counts: [...counts.entries()]
          .sort((a, b) => b[1] - a[1])
          .map(([value, minutes]) => ({ value, minutes })),
        missing_minutes: missing,
      },
      ...(code === 'SKY' ? { sky: sensors.sky(allTs, all as (string | null)[], total) } : {}),
      ...(code === 'PW' ? { weather: sensors.weather(allTs, all as (string | null)[], total) } : {}),
      ...(code === 'LTX' ? { lightning: sensors.lightning(allTs, all as (string | null)[], total) } : {}),
      stats,
    }
  })
  const wind =
    type === 'ANEM'
      ? {
          rose: Array.from({ length: 16 }, (_, i) => ({
            sector: i,
            calm: Math.round(hash(`rc${i}`) * 20),
            light: Math.round((i > 2 && i < 7 ? 160 : 40) * hash(`rl${i}`)),
            moderate: Math.round((i > 3 && i < 6 ? 60 : 8) * hash(`rm${i}`)),
            strong: i === 4 ? 6 : 0,
            gale: 0,
          })),
          max_speed_kt: 15,
          min_speed_kt: 0,
          gust: {
            count: (raw.WGS ?? []).filter((g) => typeof g === 'number' && g > 0).length,
            max_speed_kt: 18,
            direction_deg: 120,
            ...sensors.gusts(
              allTs,
              (raw.WGS ?? []) as (number | null)[],
              (raw.WGD ?? []) as (number | null)[],
            ),
          },
        }
      : undefined
  // The window's availability from the same minutes as the minute view, so flags and losses match it.
  let v = 0
  let e = 0
  for (const d of periodDays(from, end)) {
    const m = minutes(dayKey(d), `component:${slug}:${type}`, now)
    const a = Math.max(0, Math.floor((from - d) / 60_000))
    const b = Math.min(1440, Math.floor((end - d) / 60_000))
    for (let i = a; i < b; i++) {
      const c = m.codes[i]
      if (c === 'u') continue
      e++
      if (c === 'v') v++
    }
  }
  return {
    component: type,
    from: new Date(from).toISOString(),
    to: new Date(to).toISOString(),
    fields,
    availability: avail(v, e),
    wind,
  }
}

/** GET /systems: one summary per system, as on the Dashboard. */
export function systems(now: number): SystemSummary[] {
  const d = new Date(now)
  const month = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), 1)
  const today = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate())
  const m = kpis(month, now, now)
  return [
    {
      code: SYSTEM.code,
      type: SYSTEM.type,
      name: SYSTEM.name,
      icao: SYSTEM.icao,
      sla_today: kpis(today, now, now).sla,
      sla_month: m.sla,
      ola_month: { pct: m.ola.pct },
      problems: 1, // the sample /problems has one
      last_data_minute: status(now).last_data_minute,
    },
  ]
}
