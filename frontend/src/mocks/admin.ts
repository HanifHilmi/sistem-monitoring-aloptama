// Sample Admin operations for dev:sample and CI (R2.2): jobs (a running one moves along), settings, mandatory
// fields and in-service periods. State lives in this tab's sessionStorage, like the sample accounts.
import type {
  AdminSettings,
  Availability,
  ComponentRow,
  JobDetail,
  JobRow,
  MandatoryPreview,
  MandatoryType,
} from '@/api/types'
import { SYSTEM } from './data'

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

export function components(): ComponentRow[] {
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
  if (!/^\/admin\/(jobs|settings|mandatory-fields|components)/.test(path)) return null
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
  const sm = path.match(/^\/admin\/settings\/(color_thresholds|grace_minutes|problem_thresholds)$/)
  if (sm && method === 'PUT') {
    const key = sm[1] as 'color_thresholds' | 'grace_minutes' | 'problem_thresholds'
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

  if (path === '/admin/components' && method === 'GET')
    return done(
      json(
        components().map((c) => ({
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
