// Sample AWOS alarms (R3.1) for dev:sample and CI: names and messages as the AWOS writes them (addresses left out),
// raised and cleared over the last two months, with a few still active. Times are relative to now, so the active
// list and the history always have something to show. The mapping lives in this tab's sessionStorage.
import type {
  ActiveAlarm,
  ActiveAlarms,
  AlarmEvent,
  AlarmName,
  AlarmPage,
  AlarmPlace,
  AlarmType,
  Problem,
} from '@/api/types'
import { SYSTEM } from './data'

const KEY = 'simola.mock.alarms'
const MIN = 60_000
const HOUR = 3_600_000
const DAY = 86_400_000

const C = (site: string, component: string): AlarmPlace => ({ kind: 'component', site, component })
const STATION: AlarmPlace = { kind: 'station', site: null, component: null }

/** name → type, message, seeded place */
const NAMES: Record<string, [AlarmType, string, AlarmPlace]> = {
  DCPA_Missing: ['error', 'DCP 04 Communication Error - check connections', C('04', 'DCP')],
  DCPB_Missing: ['error', 'DCP 04M Communication Error - check connections', C('middle', 'DCP')],
  DCPC_Missing: ['error', 'DCP 22 Communication Error - check connections', C('22', 'DCP')],
  DCPA_VISA_DataIncompleteError: ['error', 'Visibility Sensor 04 Data Incomplete', C('04', 'RVR')],
  DCPC_VISC_DirtyWindowWarning: ['warning', 'Visibility Sensor 22 Dirty Window', C('22', 'RVR')],
  DCPA_CHIA_DirtyWindowWarning: ['warning', 'Ceilometer 04 Dirty Window', C('04', 'CEL')],
  DCP6498CpsbDegradedWarning: [
    'warning',
    'Present Weather Sensor 22 Possible Degraded Performance Warning',
    C('22', 'PWX'),
  ],
  DCPC_PWXCommError: ['error', 'DCP 22 Present Weather Sensor Communications Failure', C('22', 'PWX')],
  DCPA_windSensorWarning: ['warning', 'DCP 04 Wind Sensor Failure', C('04', 'ANEM')],
  DCPB_LightningCommWarning: [
    'warning',
    'DCP 04M Lightning Sensor Communications Failure',
    C('middle', 'LIGH'),
  ],
  BPAIsManualWarning: ['warning', 'BP Sensor at 04 using manually entered value', C('04', 'BARO')],
  RLS0_Missing: [
    'error',
    'RLS Communication Error at Runway 04 - check connections',
    { kind: 'site', site: '04', component: null },
  ],
  GPSActiveError: ['error', 'The GPS device cannot receive a satellite signal.', STATION],
  BPOutOfRangeWarning: ['warning', 'Range of readings from BP sensors exceeds allowed setting.', STATION],
  AFTNSocketFailedPortConnectionWarning: ['warning', 'AFTN failed to connect to the message switch', STATION],
  AMHSGatewayTimeoutWarning: [
    'warning',
    'AMHS gateway did not answer',
    { kind: 'unmapped', site: null, component: null },
  ],
}

/** an alarm counts as active while its latest change is at most this old (the AWOS rarely logs a clear) */
const WINDOW_HOURS = 24

/** latest change says active: name → [hours since raised, acknowledged?]; older than a day = no clear logged */
const ACTIVE: Record<string, [number, boolean]> = {
  DCPA_VISA_DataIncompleteError: [3.4, false],
  DCPC_VISC_DirtyWindowWarning: [53, true],
  DCP6498CpsbDegradedWarning: [6.2, false],
  GPSActiveError: [74, true],
  DCPB_LightningCommWarning: [0.7, false],
  AMHSGatewayTimeoutWarning: [26, false],
}

interface Stored {
  places: Record<string, { place: AlarmPlace; by: string; at: string }>
}

function load(): Stored {
  try {
    const raw = sessionStorage.getItem(KEY)
    if (raw) return JSON.parse(raw) as Stored
  } catch {
    /* fall through */
  }
  return { places: {} }
}
let state: Stored | null = null
const current = () => (state ??= load())
function save() {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(current()))
  } catch {
    /* sample mode only */
  }
}

/** A small, repeatable random sequence, so the history is the same on every load of the day. */
function rng(seed: number) {
  let x = seed
  return () => (x = (x * 1103515245 + 12345) % 2147483648) / 2147483648
}

function placeOf(name: string): AlarmPlace {
  return (
    current().places[name]?.place ?? NAMES[name]?.[2] ?? { kind: 'unmapped', site: null, component: null }
  )
}
const cdpsFor = (r: () => number): string[] => (r() < 0.8 ? ['CDP1', 'CDP2'] : ['CDP1'])

/** Every change of the last 60 days, oldest first. */
export function events(now: number): AlarmEvent[] {
  const today = Math.floor(now / DAY) * DAY
  const r = rng(today / DAY)
  const out: Omit<AlarmEvent, 'id' | 'place' | 'raised'>[] = []
  const push = (time: number, name: string, state: string, active: boolean, cdps: string[]) => {
    const [type, message] = NAMES[name]!
    out.push({ time: new Date(time).toISOString(), name, type, state, active, message, cdps })
  }
  const names = Object.keys(NAMES)
  for (let d = 60; d >= 1; d--) {
    const n = Math.floor(r() * 3)
    for (let i = 0; i < n; i++) {
      const name = names[Math.floor(r() * names.length)]!
      const at = today - d * DAY + Math.floor(r() * 22 * 60) * MIN
      const cdps = cdpsFor(r)
      const acked = r() < 0.3
      const clearedAt = at + (5 + Math.floor(r() * 300)) * MIN
      const clearState = r() < 0.3 ? 'acknowledged' : 'pending'
      // Only the alarms in ACTIVE are active: a random one not cleared by now is left out, so the sample's
      // active list is the same at every hour of the day.
      if (clearedAt > now) continue
      const fixed = ACTIVE[name]
      if (fixed && clearedAt >= now - fixed[0] * HOUR) continue // would end an alarm that is still active
      push(at, name, 'pending', true, cdps)
      if (acked && at + 20 * MIN < clearedAt) push(at + 20 * MIN, name, 'acknowledged', true, cdps)
      push(clearedAt, name, clearState, false, cdps)
    }
  }
  // Yesterday at 10:43 the three DCPs dropped together, next to a gap in the data, and came back at 10:55.
  for (const name of ['DCPA_Missing', 'DCPB_Missing', 'DCPC_Missing']) {
    const at = today - DAY + 10 * HOUR + 43 * MIN + (name === 'DCPC_Missing' ? 1000 : 0)
    push(at, name, 'pending', true, ['CDP1', 'CDP2'])
    push(at + 12 * MIN, name, 'pending', false, ['CDP1', 'CDP2'])
  }
  for (const [name, [hours, ack]] of Object.entries(ACTIVE)) {
    const at = Math.floor((now - hours * HOUR) / 1000) * 1000
    const cdps = name === 'AMHSGatewayTimeoutWarning' ? ['CDP1'] : ['CDP1', 'CDP2']
    push(at, name, 'pending', true, cdps)
    if (ack) push(at + 35 * MIN, name, 'acknowledged', true, cdps)
  }
  const wasActive = new Map<string, boolean>()
  return out
    .filter((e) => Date.parse(e.time) <= now)
    .sort((a, b) => a.time.localeCompare(b.time) || a.name.localeCompare(b.name))
    .map((e, i) => {
      // An acknowledgement of an alarm already active does not raise it again.
      const raised = e.active && !(wasActive.get(e.name) && e.state === 'acknowledged')
      wasActive.set(e.name, e.active)
      return { ...e, id: i + 1, raised, place: placeOf(e.name) }
    })
}

function inScope(p: AlarmPlace, scope: string | null | undefined): boolean {
  if (!scope) return true
  if (scope === 'station' || scope === 'unmapped') return p.kind === scope
  const [kind, site, component] = scope.split(':')
  if (kind === 'site') return p.site === site
  return p.site === site && p.component === component
}

/** FR-ALM-001: latest change says active and is at most a day old (errors first, then the oldest); older ones
 * have no clear logged (newest first). */
export function active(now: number, scope?: string | null): ActiveAlarms {
  const latest = new Map<string, AlarmEvent>()
  const since = new Map<string, string>()
  for (const e of events(now)) {
    if (e.raised) since.set(e.name, e.time)
    latest.set(e.name, e)
  }
  const all: ActiveAlarm[] = [...latest.values()]
    .filter((e) => e.active && inScope(e.place, scope))
    .map((e) => ({
      name: e.name,
      type: e.type,
      state: e.state,
      message: e.message,
      since: since.get(e.name)!,
      changed: e.time,
      cdps: e.cdps,
      place: e.place,
    }))
  const edge = new Date(now - WINDOW_HOURS * HOUR).toISOString()
  const errorsFirst = (a: ActiveAlarm, b: ActiveAlarm) =>
    a.type === b.type ? 0 : a.type === 'error' ? -1 : 1
  return {
    window_hours: WINDOW_HOURS,
    active: all
      .filter((a) => a.changed >= edge)
      .sort((a, b) => errorsFirst(a, b) || a.since.localeCompare(b.since)),
    not_cleared: all
      .filter((a) => a.changed < edge)
      .sort((a, b) => errorsFirst(a, b) || b.changed.localeCompare(a.changed)),
  }
}

/** The changes the history's filters keep, oldest first (also the alarm export). */
export function filtered(now: number, q: URLSearchParams): AlarmEvent[] {
  const from = Date.parse(q.get('from') ?? '')
  const to = Date.parse(q.get('to') ?? '')
  const type = q.get('type')
  const name = (q.get('name') ?? '').toLowerCase()
  const act = q.get('active')
  return events(now).filter((e) => {
    const t = Date.parse(e.time)
    return (
      t >= from &&
      t < to &&
      (!type || e.type === type) &&
      inScope(e.place, q.get('scope')) &&
      (!name || e.name.toLowerCase().includes(name) || e.message.toLowerCase().includes(name)) &&
      (act === null || String(e.active) === act)
    )
  })
}

/** FR-ALM-002: changes in [from, to), filtered, 50 a page, with alarms raised per day. */
export function history(now: number, q: URLSearchParams): AlarmPage {
  const from = Date.parse(q.get('from') ?? '')
  const to = Date.parse(q.get('to') ?? '')
  const list = filtered(now, q)
  const days = new Map<string, { day: string; error: number; warning: number }>()
  for (let d = Math.floor(from / DAY) * DAY; d < to; d += DAY) {
    const day = new Date(d).toISOString().slice(0, 10)
    days.set(day, { day, error: 0, warning: 0 })
  }
  for (const e of list) if (e.raised) days.get(e.time.slice(0, 10))![e.type]++
  const sorted = q.get('order') === 'asc' ? list : [...list].reverse()
  const offset = Number(q.get('offset') ?? 0)
  return { total: list.length, events: sorted.slice(offset, offset + 50), per_day: [...days.values()] }
}

/** Admin → Alarm mapping: every name seen, unmapped first. */
export function names(now: number): AlarmName[] {
  const all = events(now)
  return Object.keys(NAMES)
    .map((name) => {
      const mine = all.filter((e) => e.name === name)
      const stored = current().places[name]
      return {
        name,
        type: NAMES[name]![0],
        message: NAMES[name]![1],
        place: placeOf(name),
        source: stored ? ('admin' as const) : ('seed' as const),
        events: mine.length,
        last_seen: mine.at(-1)?.time ?? new Date(now).toISOString(),
        updated_by: stored?.by ?? null,
        updated_at: stored?.at ?? null,
      }
    })
    .sort(
      (a, b) =>
        Number(b.place.kind === 'unmapped') - Number(a.place.kind === 'unmapped') ||
        a.name.localeCompare(b.name),
    )
}

/** Refusal code, or the saved name. */
export function setPlace(name: string, place: AlarmPlace, by: string, now: number): AlarmName | string {
  if (!NAMES[name]) return 'alarm_not_found'
  const site = SYSTEM.sites.find((s) => s.slug === place.site)
  if ((place.kind === 'component' || place.kind === 'site') && !site) return 'site_not_found'
  if (place.kind === 'component' && !site!.components.some((c) => c.type === place.component))
    return 'component_not_found'
  const clean: AlarmPlace = {
    kind: place.kind,
    site: place.kind === 'component' || place.kind === 'site' ? place.site : null,
    component: place.kind === 'component' ? place.component : null,
  }
  current().places[name] = { place: clean, by, at: new Date(now).toISOString() }
  save()
  return names(now).find((n) => n.name === name)!
}

/** Problems panel: the number of active alarms, for everyone; the list is for signed-in users. */
export function alarmProblems(now: number, signedIn: boolean): Problem[] {
  const list = active(now).active
  if (!list.length) return []
  const errors = list.filter((a) => a.type === 'error').length
  return [
    {
      code: 'alarms_active',
      severity: errors ? 'minor' : 'info',
      link: signedIn ? `/systems/${SYSTEM.code}/alarms` : `/systems/${SYSTEM.code}`,
      params: { n: list.length, errors },
    },
  ]
}
