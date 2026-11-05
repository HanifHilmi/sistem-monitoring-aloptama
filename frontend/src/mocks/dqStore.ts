// Sample validity rules and detections (R2.4) for dev:sample and CI. Kept apart from the routes so the loss model
// and the charts in data.ts can read them without a circular import. State lives in this tab's sessionStorage.
import type { DetectionStatus, Evidence, RuleParams, RuleType } from '@/api/types'

export interface StoredVersion {
  version: number
  params: RuleParams
  enabled: boolean
  site: string | null
  created_by: string
  created_at: string
}
export interface StoredRule {
  id: number
  component_type: string
  field: string
  site: string | null
  type: RuleType
  proposed: boolean
  versions: StoredVersion[]
  /** sample only: the proposal was set from the sample history */
  synced?: boolean
}
export interface StoredDetection {
  id: number
  site: string
  component: string
  field: string
  rule_id: number
  rule_version: number
  type: RuleType
  params: RuleParams
  start: string
  end: string
  status: DetectionStatus
  mandatory: boolean
  evidence: Evidence
  decided_by: string | null
  decided_at: string | null
  note: string | null
}
interface State {
  rules: StoredRule[]
  detections: StoredDetection[]
}

const KEY = 'simola.mock.dq'
const H = 3_600_000
const MIN = 60_000
const iso = (ms: number) => new Date(ms).toISOString()
/** Fields that decide availability in the sample registry (mocks/data.ts MANDATORY). */
export const MANDATORY: Record<string, string[]> = {
  ATRH: ['TEMP', 'RH'],
  BARO: ['QNH'],
  ANEM: ['WS', 'WD'],
  RVR: ['RVR'],
  CEL: ['LR1'],
  PWX: ['PW'],
  RAIN: ['RA'],
  SOLR: ['SOL'],
  LIGH: ['LTX'],
}

function seed(now: number): State {
  let rid = 0
  const v1 = '2026-11-02T08:00:00Z'
  const rule = (
    type: string,
    field: string,
    t: RuleType,
    params: RuleParams,
    enabled: boolean,
    opts: { site?: string; proposed?: boolean; history?: [RuleParams, string, string][] } = {},
  ): StoredRule => {
    const older = (opts.history ?? []).map(([p, by, at], i) => ({
      version: i + 1,
      params: p,
      enabled: true,
      site: opts.site ?? null,
      created_by: by,
      created_at: at,
    }))
    return {
      id: ++rid,
      component_type: type,
      field,
      site: opts.site ?? null,
      type: t,
      proposed: !!opts.proposed,
      versions: [
        ...older,
        {
          version: older.length + 1,
          params,
          enabled,
          site: opts.site ?? null,
          created_by: opts.proposed ? 'system' : 'andi',
          created_at: opts.proposed ? '2026-11-01T00:00:00Z' : v1,
        },
      ],
    }
  }
  const rules = [
    rule('ATRH', 'TEMP', 'range', { min: 15, max: 40 }, true, {
      history: [[{ min: 10, max: 45 }, 'andi', '2026-11-01T09:00:00Z']],
    }),
    rule('ATRH', 'TEMP', 'range', { min: 17, max: 38 }, true, { site: 'middle' }),
    rule('ATRH', 'TEMP', 'spike', { max_change: 3 }, true),
    rule('ATRH', 'TEMP', 'stuck', { minutes: 180 }, false, { proposed: true }),
    rule('ATRH', 'RH', 'range', { min: 5, max: 100 }, true),
    rule('ATRH', 'RH', 'stuck', { minutes: 180 }, true),
    rule('ATRH', 'DEWP', 'range', { min: 10, max: 32 }, false, { proposed: true }),
    rule('BARO', 'QNH', 'range', { min: 995, max: 1025 }, true),
    rule('BARO', 'QNH', 'spike', { max_change: 1.5 }, true),
    rule('BARO', 'QNH', 'stuck', { minutes: 360 }, false, { proposed: true }),
    rule('BARO', 'DA', 'range', { min: -500, max: 3000 }, true),
    rule('ANEM', 'WS', 'range', { min: 0, max: 80 }, true),
    rule('ANEM', 'WS', 'stuck', { minutes: 120, ignore: [0] }, false, { proposed: true }),
    rule('ANEM', 'WD', 'stuck', { minutes: 180 }, true),
    rule('RVR', 'RVR', 'range', { min: 0, max: 20000 }, false, { proposed: true }),
    rule('CEL', 'LR1', 'range', { min: 0, max: 250 }, false, { proposed: true }),
    rule('RAIN', 'RA', 'stuck', { minutes: 60, ignore: [0] }, false, { proposed: true }),
    rule('SOLR', 'SOL', 'range', { min: 0, max: 1400 }, true),
    rule('SOLR', 'SOL', 'stuck', { minutes: 120, ignore: [0] }, false, { proposed: true }),
  ]
  const ruleOf = (type: string, field: string, t: RuleType, site: string | null = null) =>
    rules.find(
      (r) => r.component_type === type && r.field === field && r.type === t && (r.site ?? null) === site,
    )!
  let did = 0
  const hour = Math.floor(now / H) * H
  const det = (
    site: string,
    type: string,
    field: string,
    t: RuleType,
    start: string | number,
    minutes: number,
    evidence: Evidence,
    status: DetectionStatus = 'suspect',
    decided: [string, string, string | null] | null = null,
    ruleSite: string | null = null,
  ): StoredDetection => {
    const r = ruleOf(type, field, t, ruleSite)
    const v = r.versions[r.versions.length - 1]!
    const a = typeof start === 'number' ? start : Date.parse(start)
    return {
      id: ++did,
      site,
      component: type,
      field,
      rule_id: r.id,
      rule_version: v.version,
      type: t,
      params: v.params,
      start: iso(a),
      end: iso(a + minutes * MIN),
      status,
      mandatory: MANDATORY[type]!.includes(field),
      evidence,
      decided_by: decided?.[0] ?? null,
      decided_at: decided?.[1] ?? null,
      note: decided?.[2] ?? null,
    }
  }
  return {
    rules,
    detections: [
      // waiting for review
      det('04', 'ATRH', 'RH', 'stuck', '2026-11-04T01:10:00Z', 270, { value: 87 }),
      det('22', 'ATRH', 'TEMP', 'spike', '2026-11-04T13:22:00Z', 2, { change: 6.4 }),
      det('middle', 'BARO', 'QNH', 'spike', '2026-11-03T07:15:00Z', 1, { change: -2.6 }),
      det('04', 'ANEM', 'WD', 'stuck', '2026-11-02T18:00:00Z', 270, { value: 145 }),
      det('04', 'BARO', 'DA', 'range', '2026-11-01T10:00:00Z', 20, { value: 4210 }),
      det(
        'middle',
        'ATRH',
        'TEMP',
        'range',
        '2026-11-04T06:30:00Z',
        11,
        { value: 16.2 },
        'suspect',
        null,
        'middle',
      ),
      det('middle', 'SOLR', 'SOL', 'range', '2026-10-31T05:00:00Z', 5, { value: 1520 }),
      det('22', 'ANEM', 'WD', 'stuck', '2026-11-04T20:00:00Z', 195, { value: 90 }),
      det('04', 'ATRH', 'TEMP', 'spike', hour - 30 * MIN, 2, { change: 5.8 }),
      // confirmed
      det('04', 'ATRH', 'TEMP', 'range', hour - 50 * MIN, 6, { value: 41.6 }, 'confirmed', [
        'andi',
        iso(hour - 20 * MIN),
        'Shield loose again; readings far too high.',
      ]),
      det('04', 'ATRH', 'RH', 'stuck', '2026-10-17T02:00:00Z', 240, { value: 92 }, 'confirmed', [
        'budi',
        '2026-10-17T08:05:00Z',
        'Sensor head replaced at 07:30.',
      ]),
      det('middle', 'ANEM', 'WD', 'stuck', '2026-10-23T09:00:00Z', 210, { value: 200 }, 'confirmed', [
        'andi',
        '2026-10-23T13:10:00Z',
        'Vane bearing seized; freed and greased.',
      ]),
      det('22', 'BARO', 'QNH', 'spike', '2026-10-09T04:12:00Z', 1, { change: 3.1 }, 'confirmed', [
        'budi',
        '2026-10-09T06:00:00Z',
        null,
      ]),
      det('22', 'ATRH', 'RH', 'range', '2026-10-28T15:00:00Z', 30, { value: 104 }, 'confirmed', [
        'andi',
        '2026-10-28T16:02:00Z',
        'Above 100 % is impossible; wet sensor.',
      ]),
      // rejected
      det('04', 'ANEM', 'WD', 'stuck', '2026-10-20T03:00:00Z', 200, { value: 120 }, 'rejected', [
        'budi',
        '2026-10-20T07:40:00Z',
        'Calm night: the vane holds its direction when there is no wind.',
      ]),
      det('22', 'BARO', 'QNH', 'spike', '2026-10-02T16:41:00Z', 1, { change: 1.8 }, 'rejected', [
        'andi',
        '2026-10-02T17:30:00Z',
        'Real pressure jump with the thunderstorm gust front.',
      ]),
    ],
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

export function dqState(): State {
  return current()
}

export function saveDq(): void {
  try {
    globalThis.sessionStorage?.setItem(KEY, JSON.stringify(current()))
  } catch {
    /* ignore */
  }
}

/** Confirmed detections on a mandatory field of one component overlapping [from, to), oldest first. */
export function confirmedSpans(
  site: string,
  type: string,
  from: number,
  to: number,
): { start: number; end: number; id: number; field: string; type: RuleType }[] {
  return current()
    .detections.filter(
      (d) =>
        d.status === 'confirmed' &&
        d.mandatory &&
        d.site === site &&
        d.component === type &&
        Date.parse(d.end) > from &&
        Date.parse(d.start) < to,
    )
    .sort((a, b) => a.id - b.id)
    .map((d) => ({
      start: Date.parse(d.start),
      end: Date.parse(d.end),
      id: d.id,
      field: d.field,
      type: d.type,
    }))
}

/** Suspect detections (any field) of one component overlapping [from, to). */
export function suspectSpans(site: string, type: string, from: number, to: number) {
  return current().detections.filter(
    (d) =>
      d.status === 'suspect' &&
      d.site === site &&
      d.component === type &&
      Date.parse(d.end) > from &&
      Date.parse(d.start) < to,
  )
}

/**
 * The value the sample sensor reports while a detection's problem is going on, so charts show what the rule saw:
 * a stuck value, an out-of-range value, or a jump.
 */
export function detectedValue(site: string, type: string, field: string, t: number, v: number | null) {
  if (v === null) return v
  for (const d of current().detections) {
    if (d.site !== site || d.component !== type || d.field !== field) continue
    const a = Date.parse(d.start)
    const b = Date.parse(d.end)
    if (t < a || t >= b) continue
    if (d.type === 'spike') return v + (d.evidence.change ?? 0)
    return d.evidence.value ?? v
  }
  return v
}
