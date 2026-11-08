// Sample AWOS reports (R3.2) for dev:sample and CI, laid out like the CDPs' logs: a METAR every half hour (logged
// half a minute before its time) with a few SPECI, a MET REPORT with the same weather, and a TAF three times a day.
// Each day is the same on every load. Yesterday always has a thunderstorm: a SPECI and a SPECIAL at 07:16 and a
// TAF AMD at 07:40. Browser tests use only those fixed parts (the rest is random per day).
import {
  REPORT_TYPES,
  type LatestReports,
  type ReportDay,
  type ReportEntry,
  type ReportSearch,
  type ReportType,
} from '@/api/types'
import { SYSTEM } from './data'

const MIN = 60_000
const DAY = 86_400_000
const ICAO = 'WIDN'
const pad = (n: number, w = 2) => String(n).padStart(w, '0')
const COVERAGE = Date.parse(SYSTEM.coverage_start)

function rng(seed: number) {
  let x = (seed * 2654435761) % 2147483648
  return () => (x = (x * 1103515245 + 12345) % 2147483648) / 2147483648
}

const SPECI_REASONS = [
  'manually created condition',
  'visibility decrease through 5000',
  'visibility increase through or to 5000',
  'amount of cloud coverage below 1500 feet increasing to BKN or OVC',
]

interface Weather {
  dir: number
  spd: number
  storm: boolean
  cb: boolean
  cover: string
  base: number
  t: number
  dp: number
  qnh: number
}

/** The weather at a minute of a day; a storm sets wind, rain and cloud while it lasts. */
function weather(dayNum: number, minute: number, storm: [number, number] | null): Weather {
  const r = rng(dayNum * 2000 + minute + 7)
  const h = minute / 60
  const inStorm = !!storm && minute >= storm[0] && minute < storm[1]
  const t = Math.round(28 + 4.5 * Math.cos(((h - 6.5) / 24) * 2 * Math.PI) + (r() - 0.5))
  const qnh = Math.round(1011.5 + 1.2 * Math.cos(((h - 3) / 12) * 2 * Math.PI) + (r() - 0.5))
  const spd = inStorm ? 10 + Math.floor(r() * 8) : Math.floor(r() * (h > 3 && h < 11 ? 9 : 5))
  const dir = ((inStorm ? 300 : 20) + Math.floor(r() * 12) * 10) % 360 || 360
  return {
    dir,
    spd,
    storm: inStorm,
    cb: inStorm || (h > 4 && h < 11 && r() < 0.4),
    cover: inStorm ? 'BKN' : h > 2 && h < 10 ? (r() < 0.5 ? 'SCT' : 'BKN') : 'FEW',
    base: inStorm ? 15 : 17,
    t: inStorm ? t - 3 : t,
    dp: 24 + (r() < 0.5 ? 0 : 1),
    qnh,
  }
}

function metar(kind: string, stamp: string, w: Weather): string {
  const wind = w.spd === 0 ? '00000KT' : w.spd < 3 ? `VRB0${w.spd}KT` : `${pad(w.dir, 3)}${pad(w.spd)}KT`
  const vis = w.storm ? '4000 TSRA' : '9999'
  const cloud = w.cb ? `SCT0${w.base - 2}CB ${w.cover}0${w.base}` : `${w.cover}0${w.base}`
  return `${kind} ${ICAO} ${stamp} ${wind} ${vis} ${cloud} ${w.t}/${Math.min(w.dp, w.t)} Q${w.qnh} ${w.storm ? 'TEMPO TSRA' : 'NOSIG'}=`
}

function metReport(kind: string, stamp: string, w: Weather, rwy: string): string {
  const point = (k: number) => {
    const s = Math.max(0, w.spd + k)
    return s === 0 ? 'CALM' : `${pad((w.dir + k * 10 + 360) % 360 || 360, 3)}/${s}KT`
  }
  const vis = w.storm ? '4000M' : '10KM'
  const cld = w.cb
    ? `SCT CB ${(w.base - 2) * 100}FT ${w.cover} ${w.base * 100}FT`
    : `${w.cover} ${w.base * 100}FT`
  return (
    `${kind} ${ICAO} ${stamp} WIND RWY ${rwy} TDZ ${point(0)} MID ${point(1)} END ${point(-1)} ` +
    `VIS RWY ${rwy} TDZ ${vis} END ${vis} ${w.storm ? 'MOD TSRA ' : ''}CLD RWY 04 ${cld} RWY 22 ${cld} ` +
    `T${w.t} DP${Math.min(w.dp, w.t)} QNH ${w.qnh}HPA QFE RWY 04 ${w.qnh - 2}HPA RWY 22 ${w.qnh - 3}HPA ` +
    `TREND ${w.storm ? 'TEMPO TSRA' : 'NOSIG'}=`
  )
}

const ddhh = (t: number) => {
  const d = new Date(t)
  return `${pad(d.getUTCDate())}${pad(d.getUTCHours())}`
}

/** Every report logged on one UTC day, in the order logged (not yet cut at "now"). */
function build(dayNum: number, todayNum: number): ReportEntry[] {
  const start = dayNum * DAY
  const r = rng(dayNum)
  const yesterday = dayNum === todayNum - 1
  const stormDay = yesterday || r() < 0.3
  const s0 = yesterday ? 7 * 60 + 16 : (5 + Math.floor(r() * 4)) * 60 + 16
  const storm: [number, number] | null = stormDay ? [s0, s0 + 134] : null
  const rwy = r() < 0.2 ? '22' : '04'
  const out: Omit<ReportEntry, 'id'>[] = []
  const add = (
    type: ReportType,
    kind: string,
    at: number,
    text: string,
    notes: string[] = [],
    bulletin: string | null = null,
  ) => {
    // CDP2 logs only some reports: its specials, routine reports in two blocks of the day, morning TAFs.
    const h = new Date(at).getUTCHours()
    const special = kind === 'SPECI' || kind === 'SPECIAL'
    const both = type === 'taf' ? h < 12 : special || h < 6 || (h >= 12 && h < 18)
    out.push({
      type,
      kind,
      logged_at: new Date(at).toISOString(),
      text,
      notes,
      runway: type === 'taf' ? null : rwy,
      bulletin,
      cdps: both ? ['CDP1', 'CDP2'] : ['CDP1'],
    })
  }

  // Routine reports for each half hour; the 00:00 one belongs to the next day's date and is logged at 23:59.
  const dup = 10 + Math.floor(r() * 30)
  for (let slot = 1; slot <= 48; slot++) {
    const minute = slot * 30
    const obs = start + minute * MIN
    const stamp = `${ddhh(obs)}${pad(minute % 60)}Z`
    const w = weather(dayNum, minute, storm)
    const logged = obs - (16 + Math.floor(r() * 24)) * 1000
    add('metar', 'METAR', logged, metar('METAR', stamp, w))
    if (slot === dup) add('metar', 'METAR', logged + 57_000, metar('METAR', stamp, w)) // sent twice
    add('metreport', 'MET REPORT', logged + 3_000, metReport('MET REPORT', stamp, w, rwy))
  }

  // Specials: the storm's start and end, and now and then another reason.
  const specials: [number, string][] = []
  if (storm) specials.push([storm[0], 'thunderstorm onset'], [storm[1] + 1, 'thunderstorm cessation'])
  if (r() < 0.6)
    specials.push([60 + Math.floor(r() * 1300), SPECI_REASONS[Math.floor(r() * SPECI_REASONS.length)]!])
  for (const [minute, reason] of specials) {
    if (minute % 30 === 0) continue
    const at = start + minute * MIN
    const stamp = `${ddhh(at)}${pad(minute % 60)}Z`
    const w = weather(dayNum, minute, storm)
    add('metar', 'SPECI', at + 29_000, metar('SPECI', stamp, w), [reason])
    add('metreport', 'SPECIAL', at + 20_000, metReport('SPECIAL', stamp, w, rwy), [reason])
  }

  // TAF at 05, 11 and 23 UTC under bulletin FTID32; a storm day gets an amendment.
  const issue = (hour: number, minute: number, kind = 'TAF') => {
    const at = start + (hour * 60 + minute + 1 + Math.floor(r() * 12)) * MIN + Math.floor(r() * 50) * 1000
    const from = start + (hour + 1) * 3_600_000
    const vf = ddhh(from)
    const vt = ddhh(from + DAY)
    const head = `${ddhh(start + hour * 3_600_000)}${pad(minute)}`
    const tempo =
      storm && hour < 7
        ? `\nTEMPO ${ddhh(start + 7 * 3_600_000)}/${ddhh(start + 10 * 3_600_000)} 4000 TSRA SCT015CB=`
        : '='
    const amd = kind === 'TAF AMD'
    const body = `${kind} ${ICAO} ${head}Z ${vf}/${vt} ${amd ? '30012KT 4000 TSRA BKN015CB' : 'VRB02KT 9999 SCT017'}`
    add(
      'taf',
      kind,
      at,
      body +
        (amd
          ? '\nBECMG ' + `${ddhh(start + 10 * 3_600_000)}/${ddhh(start + 11 * 3_600_000)} 9999 NSW SCT017=`
          : tempo),
      [],
      `FTID32 ${ICAO} ${head}`,
    )
  }
  issue(5, 0)
  if (storm) issue(Math.floor((storm[0] + 24) / 60), (storm[0] + 24) % 60, 'TAF AMD')
  issue(11, 0)
  issue(23, 0)

  return out
    .sort((a, b) => a.logged_at.localeCompare(b.logged_at))
    .map((e, i) => ({ ...e, id: dayNum * 1000 + i }))
}

const cache = new Map<string, ReportEntry[]>()
function dayEntries(dayNum: number, now: number): ReportEntry[] {
  const today = Math.floor(now / DAY)
  if (dayNum > today || (dayNum + 1) * DAY <= COVERAGE) return []
  const key = `${dayNum}:${today}`
  if (!cache.has(key)) cache.set(key, build(dayNum, today))
  const iso = new Date(now).toISOString()
  return cache.get(key)!.filter((e) => e.logged_at <= iso)
}

/** FR-RPT-001: the newest six of each type. */
export function latest(now: number): LatestReports {
  const today = Math.floor(now / DAY)
  const recent = [...dayEntries(today - 1, now), ...dayEntries(today, now)].reverse()
  return Object.fromEntries(
    REPORT_TYPES.map((t) => [t, recent.filter((e) => e.type === t).slice(0, 6)]),
  ) as LatestReports
}

/** FR-RPT-002: one UTC day of one type, in the order logged, with each type's count. */
export function day(now: number, dayIso: string, type: ReportType): ReportDay {
  const all = dayEntries(Math.floor(Date.parse(`${dayIso}T00:00:00Z`) / DAY), now)
  const counts = Object.fromEntries(
    REPORT_TYPES.map((t) => [t, all.filter((e) => e.type === t).length]),
  ) as Record<ReportType, number>
  return { day: dayIso, type, counts, reports: all.filter((e) => e.type === type) }
}

/** FR-RPT-003: text in one type's reports (or the AWOS's notes) over whole UTC days, newest first. */
export function search(now: number, q: URLSearchParams): ReportSearch {
  const type = (q.get('type') ?? 'metar') as ReportType
  const from = Math.floor(Date.parse(`${q.get('from')}T00:00:00Z`) / DAY)
  const to = Math.floor(Date.parse(`${q.get('to')}T00:00:00Z`) / DAY)
  const text = (q.get('q') ?? '').trim().toUpperCase()
  const hits: ReportEntry[] = []
  for (let d = to; d >= from && to - d < 31; d--) {
    for (const e of [...dayEntries(d, now)].reverse()) {
      if (e.type !== type) continue
      if (!text || e.text.toUpperCase().includes(text) || e.notes.some((n) => n.toUpperCase().includes(text)))
        hits.push(e)
    }
  }
  const offset = Number(q.get('offset') ?? 0)
  return { total: hits.length, reports: hits.slice(offset, offset + 50) }
}
