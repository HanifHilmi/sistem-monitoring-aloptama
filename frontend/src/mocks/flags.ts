// Sample flag routes (R2.3): the public list, and the Admin list, preview, create, edit and remove. Checks follow
// the planned API (docs/design/r2.md §4.6) so the screens show the same refusals the server will give.
import { FLAG_REASONS } from '@/api/types'
import type { Flag, FlagPreview, FlagReason, FlagRow } from '@/api/types'
import { signedIn } from './accounts'
import { components, enqueueRecompute } from './admin'
import { minutes, SYSTEM } from './data'
import { addFlag, allFlags, saveFlags, withoutFlag, type StoredFlag } from './flagStore'

const DAY = 86_400_000
const MIN = 60_000
const iso = (ms: number) => new Date(ms).toISOString()
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
const problem = (status: number, code: string) => json({ code, title: code, status }, status)

const idOf = (site: string, type: string) =>
  components().find((c) => c.site === site && c.type === type)?.id ?? 0
const row = (f: StoredFlag): FlagRow => ({
  ...f,
  component_ids: f.components.map((c) => idOf(c.site, c.type)),
})
function view(f: StoredFlag, full: boolean): Flag {
  const base = { id: f.id, reason: f.reason, start: f.start, end: f.end, components: f.components }
  return full ? { ...base, note: f.note, created_by: f.created_by, created_at: f.created_at } : base
}

/** The UTC days a range touches, up to today: the days a change recalculates. */
function days(start: number, end: number, now: number): { from: string; to: string } | null {
  const a = Math.floor(start / DAY) * DAY
  const b = Math.min(Math.floor((end - 1) / DAY) * DAY, Math.floor(now / DAY) * DAY)
  return a <= b ? { from: iso(a).slice(0, 10), to: iso(b).slice(0, 10) } : null
}
function union(
  a: { from: string; to: string } | null,
  b: { from: string; to: string } | null,
): { from: string; to: string } | null {
  if (!a || !b) return a ?? b
  return { from: a.from < b.from ? a.from : b.from, to: a.to > b.to ? a.to : b.to }
}

interface Draft {
  components: { site: string; type: string }[]
  start: number
  end: number
  reason: FlagReason
  note: string
}
function check(b: Record<string, unknown>, now: number): Draft | Response {
  const ids = Array.isArray(b.component_ids) ? (b.component_ids as number[]) : []
  if (!ids.length) return problem(422, 'no_components')
  const comps = ids.map((id) => components().find((c) => c.id === id))
  if (comps.some((c) => !c)) return problem(404, 'component_not_found')
  if (comps.some((c) => c!.is_dcp)) return problem(422, 'dcp_cannot_be_flagged')
  const start = Math.floor(Date.parse(String(b.start)) / MIN) * MIN
  const end = Math.floor(Date.parse(String(b.end)) / MIN) * MIN
  if (!Number.isFinite(start) || !Number.isFinite(end) || start >= end) return problem(422, 'invalid_period')
  if (end > Math.ceil(now / MIN) * MIN) return problem(422, 'flag_in_future')
  if (start < Date.parse(SYSTEM.coverage_start)) return problem(422, 'before_coverage')
  if (!FLAG_REASONS.includes(b.reason as FlagReason)) return problem(422, 'invalid_reason')
  const note = String(b.note ?? '').trim()
  if (note.length < 3) return problem(422, 'note_required')
  if (note.length > 500) return problem(422, 'note_too_long')
  return {
    components: comps.map((c) => ({ site: c!.site, type: c!.type })),
    start,
    end,
    reason: b.reason as FlagReason,
    note,
  }
}

function preview(ids: number[], start: number, end: number, exclude: number | null, now: number) {
  const out: FlagPreview = { start: iso(start), end: iso(end), components: [], days: days(start, end, now) }
  for (const id of ids) {
    const c = components().find((x) => x.id === id)
    if (!c || c.is_dcp) continue
    let total = 0
    let lost = 0
    withoutFlag(exclude, () => {
      for (let d = Math.floor(start / DAY) * DAY; d < end; d += DAY) {
        const m = minutes(iso(d).slice(0, 10), `component:${c.site}:${c.type}`, now)
        const a = Math.max(0, (start - d) / MIN)
        const b = Math.min(1440, (end - d) / MIN)
        for (let i = a; i < b; i++) {
          const code = m.codes[i]
          if (code === 'u' || code === undefined) continue
          total++
          if (code === 'v') lost++
        }
      }
    })
    out.components.push({ id, site: c.site, type: c.type, minutes: total, lost, already: total - lost })
  }
  return out
}

/** GET /systems/{code}/flags: reason for everyone, note and author for signed-in users (FR-DQ-007). */
export function publicFlags(url: URL): Response {
  const q = url.searchParams
  const from = Date.parse(q.get('from') ?? '')
  const to = Date.parse(q.get('to') ?? '')
  const scope = (q.get('scope') ?? '').split(':')
  const full = signedIn()
  return json(
    allFlags()
      .filter((f) => !f.removed_at && Date.parse(f.end) > from && Date.parse(f.start) < to)
      .filter((f) =>
        scope[0] === 'component'
          ? f.components.some((c) => c.site === scope[1] && c.type === scope[2])
          : scope[0] === 'site'
            ? f.components.some((c) => c.site === scope[1])
            : true,
      )
      .sort((a, b) => Date.parse(a.start) - Date.parse(b.start))
      .map((f) => view(f, full)),
  )
}

/** /admin/flags…; null for other paths. */
export function flagsRoute(
  path: string,
  url: URL,
  method: string,
  body: unknown,
  user: string,
): Response | null {
  if (!path.startsWith('/admin/flags')) return null
  const now = Date.now()
  const b = (body ?? {}) as Record<string, unknown>
  const q = url.searchParams

  if (path === '/admin/flags' && method === 'GET') {
    const removed = q.get('removed') === '1'
    return json(
      allFlags()
        .filter((f) => removed || !f.removed_at)
        .sort((a, c) => Date.parse(c.start) - Date.parse(a.start))
        .map(row),
    )
  }
  if (path === '/admin/flags/preview' && method === 'GET') {
    const ids = (q.get('components') ?? '').split(',').filter(Boolean).map(Number)
    const start = Math.floor(Date.parse(q.get('from') ?? '') / MIN) * MIN
    const end = Math.floor(Date.parse(q.get('to') ?? '') / MIN) * MIN
    if (!Number.isFinite(start) || !Number.isFinite(end) || start >= end)
      return problem(422, 'invalid_period')
    const exclude = q.get('exclude') ? Number(q.get('exclude')) : null
    return json(preview(ids, start, Math.min(end, Math.ceil(now / MIN) * MIN), exclude, now))
  }
  if (path === '/admin/flags' && method === 'POST') {
    const d = check(b, now)
    if (d instanceof Response) return d
    const f = addFlag({
      components: d.components,
      start: iso(d.start),
      end: iso(d.end),
      reason: d.reason,
      note: d.note,
      created_by: user,
      created_at: iso(now),
      updated_by: null,
      updated_at: null,
      removed_by: null,
      removed_at: null,
    })
    const range = days(d.start, d.end, now)
    const job = range ? enqueueRecompute(range.from, range.to, user, now) : null
    return json({ flag: row(f), job }, 201)
  }
  const m = path.match(/^\/admin\/flags\/(\d+)$/)
  if (m) {
    const f = allFlags().find((x) => x.id === Number(m[1]))
    if (!f) return problem(404, 'flag_not_found')
    if (f.removed_at) return problem(409, 'flag_removed')
    const before = days(Date.parse(f.start), Date.parse(f.end), now)
    if (method === 'PATCH') {
      const d = check(b, now)
      if (d instanceof Response) return d
      Object.assign(f, {
        components: d.components,
        start: iso(d.start),
        end: iso(d.end),
        reason: d.reason,
        note: d.note,
        updated_by: user,
        updated_at: iso(now),
      })
      saveFlags()
      const range = union(before, days(d.start, d.end, now))
      return json({ flag: row(f), job: range ? enqueueRecompute(range.from, range.to, user, now) : null })
    }
    if (method === 'DELETE') {
      f.removed_by = user
      f.removed_at = iso(now)
      saveFlags()
      return json({
        flag: row(f),
        job: before ? enqueueRecompute(before.from, before.to, user, now) : null,
      })
    }
  }
  return problem(405, 'method_not_allowed')
}
