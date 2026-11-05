// Sample Admin operations for dev:sample and CI (R2.2): jobs (a running one moves along), settings, mandatory
// fields and in-service periods; R2.5 adds records, calibrations and the figure change trace. State lives in this
// tab's sessionStorage, like the sample accounts.
import type {
  AdminSettings,
  Assets,
  Availability,
  CalibrationDraft,
  ComponentMeta,
  ComponentRow,
  JobDetail,
  JobRow,
  MandatoryPreview,
  MandatoryType,
  Problem,
  SiteMeta,
  TraceEvent,
} from '@/api/types'
import { SYSTEM } from './data'
import { dqState } from './dqStore'
import { allFlags } from './flagStore'
import * as rec from './records'

interface Job extends JobRow {
  log: string
  /** sample only: how long the job takes, in ms */
  span: number
}
interface State {
  jobs: Job[]
  settings: AdminSettings
  mandatory: Record<string, string[]>
  service: Record<number, { from: string | null; to: string | null }>
}

const KEY = 'simola.mock.admin'
const H = 3_600_000
const iso = (ms: number) => new Date(ms).toISOString()

export function components(window = 30, now = Date.now()): ComponentRow[] {
  let id = 0
  return SYSTEM.sites.flatMap((s) =>
    s.components.map((c) => ({
      id: ++id,
      site: s.slug,
      site_name: s.name,
      type: c.type,
      name: c.name,
      is_dcp: c.is_dcp,
      in_service_from: c.in_service_from,
      in_service_to: c.in_service_to,
      meta: rec.componentMeta(s.slug, c.type, true),
      calibration: rec.summary(s.slug, c.type, now, window),
    })),
  )
}

function seed(now: number): State {
  const job = (
    id: number,
    type: JobRow['type'],
    from: string,
    to: string,
    by: string,
    hoursAgo: number,
    minutes: number,
    message: string,
  ): Job => ({
    id,
    type,
    params: { system: SYSTEM.code, from, to },
    status: 'done',
    progress: 1,
    message,
    created_by: by,
    created_at: iso(now - hoursAgo * H),
    started_at: iso(now - hoursAgo * H + 4_000),
    finished_at: iso(now - hoursAgo * H + 4_000 + minutes * 60_000),
    log: '',
    span: 0,
  })
  const solr = components().find((c) => c.site === 'middle' && c.type === 'SOLR')!
  return {
    jobs: [
      job(
        1,
        'reprocess',
        '2025-12-24',
        '2026-11-04',
        'cli',
        30,
        20,
        'reprocessed 316 day(s), 905810 CDP-minutes; 315 daily rollup(s) stored',
      ),
      job(
        2,
        'reprocess',
        '2025-12-24',
        '2026-11-05',
        'cli',
        6,
        21,
        'reprocessed 317 day(s), 908606 CDP-minutes; 316 daily rollup(s) stored',
      ),
      job(3, 'recompute', '2026-10-01', '2026-10-31', 'andi', 2, 1, 'recomputed 31 day(s)'),
    ],
    settings: {
      color_thresholds: { good: 99, warning: 95 },
      grace_minutes: 3,
      problem_thresholds: {
        cdp_no_data_min: 2,
        cdp_unreachable_min: 2,
        site_no_data_min: 2,
        field_missing_min: 5,
        ingest_lag_min: 5,
      },
      calibration_due_soon_days: 30,
      changed: { problem_thresholds: { at: iso(now - 50 * H), by: 'budi' } },
    },
    mandatory: Object.fromEntries(
      SYSTEM.sites[0]!.components.concat(SYSTEM.sites[1]!.components).map((c) => [c.type, c.mandatory]),
    ),
    service: { [solr.id]: { from: '2026-01-15T00:00:00Z', to: null } },
  }
}

function load(now: number): State {
  try {
    const s = sessionStorage.getItem(KEY)
    if (s) return JSON.parse(s) as State
  } catch {
    /* start fresh */
  }
  return seed(now)
}
function save(s: State) {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(s))
  } catch {
    /* ignore */
  }
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
const problem = (status: number, code: string) => json({ code, title: code, status }, status)

/** A sample job moves from queued to done over `span` ms, writing one log line per day. */
function advance(j: Job, now: number) {
  if (j.status !== 'queued' && j.status !== 'running') return
  const start = Date.parse(j.created_at) + 1_500
  if (now < start) return
  const days = Math.round((Date.parse(j.params.to!) - Date.parse(j.params.from!)) / 86_400_000) + 1
  const f = Math.min(1, (now - start) / j.span)
  j.status = f >= 1 ? 'done' : 'running'
  j.started_at = iso(start)
  j.progress = f >= 1 ? 1 : Math.round(f * 1000) / 1000
  const n = Math.floor(f * days)
  const to = Date.parse(j.params.to!)
  j.log = Array.from({ length: n }, (_, i) => {
    const d = new Date(to - i * 86_400_000).toISOString().slice(0, 10)
    return j.type === 'reprocess' ? `${d} CDP1=1440 CDP2=1440` : d
  }).join('\n')
  if (f >= 1) {
    j.finished_at = iso(start + j.span)
    j.message =
      j.type === 'reprocess'
        ? `reprocessed ${days} day(s)`
        : j.type === 'detect'
          ? `checked ${days} day(s)`
          : `recomputed ${days} day(s)`
  }
}

function enqueue(
  s: State,
  type: 'reprocess' | 'recompute' | 'detect',
  from: string,
  to: string,
  by: string,
  now: number,
): Job {
  const days = Math.round((Date.parse(to) - Date.parse(from)) / 86_400_000) + 1
  const j: Job = {
    id: Math.max(0, ...s.jobs.map((x) => x.id)) + 1,
    type,
    params: { system: SYSTEM.code, from, to },
    status: 'queued',
    progress: 0,
    message: null,
    created_by: by,
    created_at: iso(now),
    started_at: null,
    finished_at: null,
    log: '',
    span: Math.min(90_000, 4_000 + days * (type === 'reprocess' ? 300 : type === 'detect' ? 40 : 80)),
  }
  s.jobs.push(j)
  return j
}
const ROW_KEYS = [
  'id',
  'type',
  'params',
  'status',
  'progress',
  'message',
  'created_by',
  'created_at',
  'started_at',
  'finished_at',
] as const
const row = (j: Job): JobRow => Object.fromEntries(ROW_KEYS.map((k) => [k, j[k]])) as unknown as JobRow
const detail = (j: Job): JobDetail => ({ ...row(j), log: j.log })

function availability(pct: number): Availability {
  const expected = 44_640
  const valid = Math.round((expected * pct) / 100)
  return { valid, expected, missing: expected - valid, pct: Math.round((valid / expected) * 10_000) / 100 }
}

/** Queues a recompute of the given UTC days, as a flag change does (R2.3). */
export function enqueueRecompute(from: string, to: string, user: string, now: number): JobRow {
  return enqueueJob('recompute', from, to, user, now)
}

/** Queues a job: a recompute after a flag or decision, a detection run after a rule change (R2.4). */
export function enqueueJob(
  type: 'recompute' | 'detect',
  from: string,
  to: string,
  user: string,
  now: number,
): JobRow {
  const s = load(now)
  s.jobs.forEach((j) => advance(j, now))
  const j = enqueue(s, type, from, to, user, now)
  save(s)
  return row(j)
}

/** Days whose figures are still being recalculated: queued and running recompute jobs. */
export function recalculating(now: number): { from: string; to: string }[] {
  const s = load(now)
  s.jobs.forEach((j) => advance(j, now))
  save(s)
  return s.jobs
    .filter((j) => j.type === 'recompute' && (j.status === 'queued' || j.status === 'running'))
    .map((j) => ({ from: j.params.from!, to: j.params.to! }))
}

/** Handles /admin/{jobs,settings,mandatory-fields,components}; null for other paths. */
export function adminRoute(
  path: string,
  url: URL,
  method: string,
  body: unknown,
  user: string,
): Response | null {
  if (!/^\/admin\/(jobs|settings|mandatory-fields|components|station|sites|calibrations)/.test(path))
    return null
  const now = Date.now()
  const s = load(now)
  s.jobs.forEach((j) => advance(j, now))
  const b = (body ?? {}) as Record<string, unknown>
  const done = (r: Response) => {
    save(s)
    return r
  }

  if (path === '/admin/jobs' && method === 'GET') return done(json([...s.jobs].reverse().map(row)))
  if (path === '/admin/jobs' && method === 'POST') {
    const type = b.type === 'recompute' ? 'recompute' : 'reprocess'
    if (
      type === 'reprocess' &&
      s.jobs.some((j) => j.type === 'reprocess' && ['queued', 'running'].includes(j.status))
    )
      return problem(409, 'job_running')
    return done(json(row(enqueue(s, type, String(b.from), String(b.to), user, now)), 201))
  }
  const jm = path.match(/^\/admin\/jobs\/(\d+)(\/cancel)?$/)
  if (jm) {
    const j = s.jobs.find((x) => x.id === Number(jm[1]))
    if (!j) return problem(404, 'not_found')
    if (jm[2] && method === 'POST' && ['queued', 'running'].includes(j.status)) {
      j.status = 'cancelled'
      j.finished_at = iso(now)
    }
    return done(json(jm[2] ? row(j) : detail(j)))
  }

  if (path === '/admin/settings' && method === 'GET') return done(json(s.settings))
  const sm = path.match(
    /^\/admin\/settings\/(color_thresholds|grace_minutes|problem_thresholds|calibration_due_soon_days)$/,
  )
  if (sm && method === 'PUT') {
    const key = sm[1] as
      'color_thresholds' | 'grace_minutes' | 'problem_thresholds' | 'calibration_due_soon_days'
    if (
      key === 'calibration_due_soon_days' &&
      !(Number.isInteger(b.value) && (b.value as number) >= 1 && (b.value as number) <= 180)
    )
      return problem(422, 'invalid_setting')
    ;(s.settings as unknown as Record<string, unknown>)[key] = b.value
    s.settings.changed[key] = { at: iso(now), by: user }
    return done(json(s.settings))
  }

  if (path === '/admin/mandatory-fields' && method === 'GET') {
    const types = new Map<string, MandatoryType>()
    for (const site of SYSTEM.sites)
      for (const c of site.components) {
        const t = types.get(c.type) ?? { type: c.type, name: c.name, is_dcp: c.is_dcp, fields: [] }
        for (const f of c.fields)
          if (!t.fields.some((x) => x.code === f))
            t.fields.push({
              code: f,
              name: SYSTEM.fields[f]!.name,
              mandatory: (s.mandatory[c.type] ?? []).includes(f),
            })
        types.set(c.type, t)
      }
    return done(json([...types.values()]))
  }
  const mm = path.match(/^\/admin\/mandatory-fields\/([^/]+)(\/preview)?$/)
  if (mm) {
    const type = decodeURIComponent(mm[1]!)
    const proposed = mm[2]
      ? (url.searchParams.get('fields') ?? '').split(',').filter(Boolean)
      : (b.fields as string[])
    const before = s.mandatory[type] ?? []
    if (mm[2]) {
      const added = proposed.filter((f) => !before.includes(f)).length
      const removed = before.filter((f) => !proposed.includes(f)).length
      const month = new Date(now)
      const preview: MandatoryPreview = {
        type,
        from: iso(Date.UTC(month.getUTCFullYear(), month.getUTCMonth(), 1)),
        to: iso(now),
        sites: SYSTEM.sites
          .filter((x) => x.components.some((c) => c.type === type))
          .map((x, i) => {
            const base = 99.6 + i * 0.12
            return {
              slug: x.slug,
              name: x.name,
              current: availability(base),
              proposed: availability(Math.min(100, base - added * (1.7 + i * 0.4) + removed * 0.08)),
            }
          }),
      }
      return json(preview)
    }
    if (method === 'PUT') {
      if (!proposed?.length) return problem(422, 'at_least_one')
      s.mandatory[type] = proposed
      const job = enqueue(
        s,
        'recompute',
        SYSTEM.coverage_start.slice(0, 10),
        iso(now).slice(0, 10),
        user,
        now,
      )
      return done(json({ job: row(job) }))
    }
  }

  // ---- records and calibration (R2.5) ----
  const window = s.settings.calibration_due_soon_days ?? 30
  if (path === '/admin/station' && method === 'GET')
    return done(json({ name: SYSTEM.name, icao: SYSTEM.icao, ...rec.stationMeta() }))
  if (path === '/admin/station' && method === 'PUT') {
    const m = b as unknown as ReturnType<typeof rec.stationMeta> & { icao?: string }
    if (m.lat !== null && m.lat !== undefined && (m.lat < -90 || m.lat > 90))
      return problem(422, 'invalid_lat')
    if (m.lon !== null && m.lon !== undefined && (m.lon < -180 || m.lon > 180))
      return problem(422, 'invalid_lon')
    if (m.procurement_year && m.procurement_year > new Date(now).getUTCFullYear())
      return problem(422, 'year_in_future')
    if (m.wmo_number && !/^\d{5}$/.test(m.wmo_number)) return problem(422, 'invalid_wmo')
    const { icao: _i, name: _n, ...meta } = m as Record<string, unknown>
    void _i
    void _n
    rec.setStation(meta as ReturnType<typeof rec.stationMeta>)
    return done(json({ name: SYSTEM.name, icao: SYSTEM.icao, ...rec.stationMeta() }))
  }
  const sitem = path.match(/^\/admin\/sites\/([^/]+)$/)
  if (sitem && method === 'PUT') {
    const m = b as unknown as SiteMeta
    if (m.lat !== null && (m.lat < -90 || m.lat > 90)) return problem(422, 'invalid_lat')
    if (m.lon !== null && (m.lon < -180 || m.lon > 180)) return problem(422, 'invalid_lon')
    rec.setSiteMeta(decodeURIComponent(sitem[1]!), m)
    return done(json(rec.siteMeta(decodeURIComponent(sitem[1]!))))
  }
  const metam = path.match(/^\/admin\/components\/(\d+)\/(meta|calibrations)$/)
  if (metam) {
    const c = components(window, now).find((x) => x.id === Number(metam[1]))
    if (!c) return problem(404, 'component_not_found')
    if (metam[2] === 'calibrations' && method === 'GET') return done(json(rec.calibrations(c.site, c.type)))
    if (metam[2] === 'meta' && method === 'PUT') {
      const m = b as unknown as ComponentMeta
      if (m.installed_on && m.installed_on > iso(now).slice(0, 10)) return problem(422, 'date_in_future')
      rec.setComponentMeta(c.site, c.type, m)
      return done(json(rec.componentMeta(c.site, c.type, true)))
    }
  }
  if (path === '/admin/calibrations' && method === 'POST') {
    const d = { ...(b as unknown as CalibrationDraft) }
    const c = components(window, now).find((x) => x.id === d.component_id)
    if (!c) return problem(404, 'component_not_found')
    if (c.is_dcp) return problem(422, 'dcp_not_calibrated')
    const code = rec.checkCalibration(d, now)
    if (code) return problem(422, code)
    return done(json(rec.addCalibration(c.site, c.type, d, user, now), 201))
  }
  const calm = path.match(/^\/admin\/calibrations\/(\d+)$/)
  if (calm) {
    if (!rec.calibrationById(Number(calm[1]))) return problem(404, 'calibration_not_found')
    if (method === 'DELETE') {
      rec.removeCalibration(Number(calm[1]))
      return done(json({ removed: Number(calm[1]) }))
    }
    if (method === 'PATCH') {
      const d = { ...(b as unknown as CalibrationDraft) }
      const code = rec.checkCalibration(d, now)
      if (code) return problem(422, code)
      return done(json(rec.updateCalibration(Number(calm[1]), d, user, now)))
    }
  }

  if (path === '/admin/components' && method === 'GET')
    return done(
      json(
        components(window, now).map((c) => ({
          ...c,
          in_service_from: s.service[c.id]?.from ?? c.in_service_from,
          in_service_to: s.service[c.id]?.to ?? c.in_service_to,
        })),
      ),
    )
  const cm = path.match(/^\/admin\/components\/(\d+)$/)
  if (cm && method === 'PATCH') {
    const c = components().find((x) => x.id === Number(cm[1]))
    if (!c) return problem(404, 'not_found')
    s.service[c.id] = {
      from: (b.in_service_from as string | null) ?? null,
      to: (b.in_service_to as string | null) ?? null,
    }
    const job = enqueue(s, 'recompute', SYSTEM.coverage_start.slice(0, 10), iso(now).slice(0, 10), user, now)
    return done(
      json({
        component: { ...c, in_service_from: s.service[c.id]!.from, in_service_to: s.service[c.id]!.to },
        job: row(job),
      }),
    )
  }
  return problem(405, 'method_not_allowed')
}

// ------------------------------------------------------------------------------- R2.5: public records and trace
const calibrationWindow = (now: number) => load(now).settings.calibration_due_soon_days ?? 30

/** GET /systems/{code}/assets: serial and part numbers only for signed-in users (OPEN-13). */
export function assets(full: boolean, now: number): Assets {
  const window = calibrationWindow(now)
  return {
    station: { name: SYSTEM.name, icao: SYSTEM.icao, ...rec.stationMeta() },
    sites: SYSTEM.sites.map((x) => ({ slug: x.slug, meta: rec.siteMeta(x.slug) })),
    components: SYSTEM.sites.flatMap((x) =>
      x.components.map((c) => ({
        site: x.slug,
        type: c.type,
        meta: rec.componentMeta(x.slug, c.type, full),
        calibration: rec.summary(x.slug, c.type, now, window),
      })),
    ),
    due_soon_days: window,
  }
}

/** Problems: one minor item per sensor whose calibration is overdue (FR-DSH-010). */
export function calibrationProblems(now: number): Problem[] {
  const window = calibrationWindow(now)
  return SYSTEM.sites.flatMap((x) =>
    x.components
      .filter((c) => !c.is_dcp)
      .map((c) => ({ x, c, cal: rec.summary(x.slug, c.type, now, window) }))
      .filter(({ cal }) => cal.status === 'overdue')
      .map(({ x, c, cal }) => ({
        code: 'calibration_overdue',
        severity: 'minor' as const,
        link: `/systems/${SYSTEM.code}/sites/${x.slug}`,
        params: { site: x.code, component: c.type, due: cal.next_due },
      })),
  )
}

/**
 * GET /systems/{code}/trace (signed-in users): what changed a component's figures in [from, to) — flags,
 * detection decisions, mandatory fields of its type, its in-service period, reprocess and recompute jobs.
 */
export function trace(scope: string, from: number, to: number, now: number): TraceEvent[] {
  const [, site, type] = scope.split(':')
  const overlaps = (a: string, b: string) => Date.parse(b) > from && Date.parse(a) < to
  const out: TraceEvent[] = []
  let n = 0
  const add = (
    time: string,
    actor: string | null,
    action: string,
    entity: string,
    id: string,
    detail: Record<string, unknown>,
  ) => out.push({ id: ++n, time, actor, action, entity_type: entity, entity_id: id, detail })
  for (const f of allFlags()) {
    if (!f.components.some((c) => c.site === site && c.type === type) || !overlaps(f.start, f.end)) continue
    const detail = { flag: f.id, reason: f.reason, start: f.start, end: f.end }
    add(f.created_at, f.created_by, 'flag_created', 'flag', String(f.id), detail)
    if (f.updated_at) add(f.updated_at, f.updated_by, 'flag_updated', 'flag', String(f.id), detail)
    if (f.removed_at) add(f.removed_at, f.removed_by, 'flag_removed', 'flag', String(f.id), detail)
  }
  for (const d of dqState().detections) {
    if (d.site !== site || d.component !== type || !d.decided_at || !d.mandatory || !overlaps(d.start, d.end))
      continue
    add(d.decided_at, d.decided_by, 'detections_decided', 'detection', String(d.id), {
      detection: d.id,
      status: d.status,
      field: d.field,
      type: d.type,
      start: d.start,
      end: d.end,
    })
  }
  if (type === 'ATRH')
    add('2026-10-29T03:12:00Z', 'budi', 'mandatory_changed', 'mandatory', 'ATRH', {
      before: ['TEMP', 'DEWP', 'RH'],
      after: ['TEMP', 'RH'],
    })
  if (site === 'middle' && type === 'SOLR')
    add('2026-10-30T02:40:00Z', 'andi', 'in_service_changed', 'component', 'middle:SOLR', {
      in_service_from: '2026-01-15T00:00:00Z',
      in_service_to: null,
    })
  for (const j of load(now).jobs) {
    const a = `${j.params.from}T00:00:00Z`
    const b = new Date(Date.parse(`${j.params.to}T00:00:00Z`) + 86_400_000).toISOString()
    if (overlaps(a, b))
      add(j.created_at, j.created_by, 'job_started', 'job', String(j.id), {
        job: j.id,
        type: j.type,
        from: j.params.from,
        to: j.params.to,
      })
  }
  return out.sort((x, y) => y.time.localeCompare(x.time))
}
