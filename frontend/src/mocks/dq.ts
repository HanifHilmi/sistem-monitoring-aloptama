// Sample routes for validity rules and detections (R2.4): the public list, the review queue and decisions, rules
// with their versions, the history behind proposed starting values, and dry runs that apply a draft rule to the
// sample sensor values. Shapes and refusals follow the planned API (docs/design/r2.md §4.4, §4.6).
import { RULE_TYPES } from '@/api/types'
import type {
  Detection,
  DetectionStatus,
  Evidence,
  FieldHistory,
  Rule,
  RuleDryRun,
  RuleParams,
  RuleType,
} from '@/api/types'
import { currentUser, signedIn } from './accounts'
import { enqueueJob, enqueueRecompute } from './admin'
import { sampleValues, SYSTEM } from './data'
import { dqState, MANDATORY, saveDq, type StoredDetection, type StoredRule } from './dqStore'

const DAY = 86_400_000
const MIN = 60_000
const iso = (ms: number) => new Date(ms).toISOString()
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
const problem = (status: number, code: string) => json({ code, title: code, status }, status)

const latest = (r: StoredRule) => r.versions[r.versions.length - 1]!
export function ruleView(r: StoredRule): Rule {
  const v = latest(r)
  return {
    id: r.id,
    component_type: r.component_type,
    field: r.field,
    site: v.site,
    type: r.type,
    params: v.params,
    enabled: v.enabled,
    proposed: r.proposed,
    version: v.version,
    changed_by: v.created_by,
    changed_at: v.created_at,
    mandatory: (MANDATORY[r.component_type] ?? []).includes(r.field),
    suspects: dqState().detections.filter((d) => d.rule_id === r.id && d.status === 'suspect').length,
    detections: dqState().detections.filter((d) => d.rule_id === r.id).length,
  }
}
export function detectionView(d: StoredDetection, full = true): Detection {
  const view: Detection = {
    id: d.id,
    site: d.site,
    component: d.component,
    field: d.field,
    type: d.type,
    rule_id: d.rule_id,
    rule_version: d.rule_version,
    params: d.params,
    start: d.start,
    end: d.end,
    minutes: (Date.parse(d.end) - Date.parse(d.start)) / MIN,
    status: d.status,
    mandatory: d.mandatory,
    evidence: d.evidence,
  }
  return full ? { ...view, decided_by: d.decided_by, decided_at: d.decided_at, note: d.note } : view
}

// ---------------------------------------------------------------------------------- rules on values
interface Hit {
  a: number // first minute index
  b: number // exclusive
  evidence: Evidence
}
/** Applies one rule to consecutive minute values. Missing values never fire and break stuck and spike runs. */
export function applyRule(type: RuleType, p: RuleParams, values: (number | null)[]): Hit[] {
  const hits: Hit[] = []
  const push = (a: number, b: number, evidence: Evidence) => {
    const last = hits[hits.length - 1]
    if (last && last.b === a && type !== 'stuck') {
      last.b = b
      const v = evidence.value
      if (v !== undefined) {
        const first = last.evidence.value ?? v
        last.evidence.low = Math.min(last.evidence.low ?? first, v)
        last.evidence.high = Math.max(last.evidence.high ?? first, v)
      }
      if (evidence.change !== undefined && Math.abs(evidence.change) > Math.abs(last.evidence.change ?? 0))
        last.evidence.change = evidence.change
    } else hits.push({ a, b, evidence: { ...evidence } })
  }
  if (type === 'range')
    values.forEach((v, i) => {
      if (v === null) return
      if (
        (p.min !== null && p.min !== undefined && v < p.min) ||
        (p.max !== null && p.max !== undefined && v > p.max)
      )
        push(i, i + 1, { value: v })
    })
  if (type === 'spike') {
    const w = Math.max(1, p.window ?? 1)
    values.forEach((v, i) => {
      const before = values[i - w]
      if (v === null || before === null || before === undefined) return
      const change = Math.round((v - before) * 10) / 10
      if (Math.abs(change) > (p.max_change ?? Infinity)) push(i, i + 1, { change })
    })
  }
  if (type === 'stuck') {
    const ignore = new Set(p.ignore ?? [])
    let i = 0
    while (i < values.length) {
      const v = values[i]
      let j = i + 1
      if (v !== null && v !== undefined) while (j < values.length && values[j] === v) j++
      if (v !== null && v !== undefined && !ignore.has(v) && j - i >= (p.minutes ?? Infinity))
        hits.push({ a: i, b: j, evidence: { value: v } })
      i = j
    }
  }
  return hits
}

function sitesWith(type: string, only: string | null): string[] {
  return SYSTEM.sites
    .filter((s) => s.components.some((c) => c.type === type && c.fields.length))
    .map((s) => s.slug)
    .filter((s) => !only || s === only)
}

function dryRun(
  type: string,
  field: string,
  site: string | null,
  rt: RuleType,
  p: RuleParams,
  now: number,
  ruleId: number | null = null,
): RuleDryRun {
  const to = Math.floor(now / DAY) * DAY
  const from = to - 30 * DAY
  const examples: RuleDryRun['examples'] = []
  let minutes = 0
  const hitSites = new Set<string>()
  let overlapping = 0
  const overlapTypes = new Set<RuleType>()
  for (const s of sitesWith(type, site)) {
    if (
      !SYSTEM.sites
        .find((x) => x.slug === s)
        ?.components.find((c) => c.type === type)
        ?.fields.includes(field)
    )
      continue
    const others = dqState().detections.filter(
      (d) =>
        d.site === s &&
        d.component === type &&
        d.field === field &&
        d.status !== 'rejected' &&
        d.rule_id !== ruleId,
    )
    for (const h of applyRule(rt, p, sampleValues(s, type, field, from, to))) {
      const a = from + h.a * MIN
      const b = from + h.b * MIN
      const hit = others.filter((d) => Date.parse(d.start) < b && a < Date.parse(d.end))
      if (hit.length) {
        overlapping++
        for (const d of hit) overlapTypes.add(d.type)
      }
      minutes += h.b - h.a
      hitSites.add(s)
      examples.push({
        site: s,
        start: iso(from + h.a * MIN),
        end: iso(from + h.b * MIN),
        minutes: h.b - h.a,
        evidence: h.evidence,
      })
    }
  }
  examples.sort((x, y) => y.minutes - x.minutes || Date.parse(y.start) - Date.parse(x.start))
  return {
    from: iso(from),
    to: iso(to),
    intervals: examples.length,
    minutes,
    sites: hitSites.size,
    examples: examples.slice(0, 5),
    overlapping,
    overlapping_types: [...overlapTypes].sort(),
  }
}

const pct = (sorted: number[], q: number) =>
  sorted[Math.min(sorted.length - 1, Math.floor(q * (sorted.length - 1)))]!
const round = (v: number, digits: number) => Math.round(v * 10 ** digits) / 10 ** digits

function history(type: string, field: string, now: number): FieldHistory {
  const to = Math.floor(now / DAY) * DAY
  const from = to - 30 * DAY
  const all: number[] = []
  const runs: number[] = []
  const steps: number[] = []
  for (const s of sitesWith(type, null)) {
    const vals = sampleValues(s, type, field, from, to)
    let run = 1
    vals.forEach((v, i) => {
      if (v === null) return
      all.push(v)
      const prev = vals[i - 1]
      if (prev !== null && prev !== undefined) steps.push(Math.abs(v - prev))
      if (prev === v) run++
      else {
        if (i) runs.push(run)
        run = 1
      }
    })
  }
  all.sort((a, b) => a - b)
  runs.sort((a, b) => a - b)
  steps.sort((a, b) => a - b)
  const p001 = pct(all, 0.001)
  const p999 = pct(all, 0.999)
  const margin = Math.max(1, (p999 - p001) * 0.25)
  const digits = Math.abs(p999) >= 100 ? 0 : 1
  const unit = SYSTEM.fields[field]?.unit ?? null
  return {
    component_type: type,
    field,
    unit,
    from: iso(from),
    to: iso(to),
    minutes: all.length,
    p001,
    p999,
    min: all[0] ?? 0,
    max: all[all.length - 1] ?? 0,
    longest_run_minutes: runs[runs.length - 1] ?? 0,
    run_p99_minutes: pct(runs, 0.99),
    largest_step: round(steps[steps.length - 1] ?? 0, 1),
    step_p999: round(pct(steps, 0.999), 1),
    proposed: {
      range: {
        min: round(
          Math.max(field === 'RH' || field === 'WS' || unit === '°' ? 0 : -Infinity, p001 - margin),
          digits,
        ),
        max: round(unit === '°' ? Math.min(360, p999 + margin) : p999 + margin, digits),
      },
      stuck: {
        minutes: Math.max(60, Math.ceil(((runs[runs.length - 1] ?? 30) * 1.5) / 30) * 30),
        ...(all[0] === 0 ? { ignore: [0] } : {}),
      },
      spike: { max_change: round(Math.max(pct(steps, 0.999) * 1.5, 0.1), 1) },
    },
  }
}

// ---------------------------------------------------------------------------------- checks
function checkDraft(b: Record<string, unknown>): string | null {
  const type = String(b.component_type ?? '')
  const field = String(b.field ?? '')
  const site = (b.site as string | null) ?? null
  if (!MANDATORY[type]) return 'component_type_not_found'
  const owners = SYSTEM.sites.filter((s) =>
    s.components.some((c) => c.type === type && c.fields.includes(field)),
  )
  if (!owners.length) return 'unknown_field'
  if (site && !owners.some((s) => s.slug === site)) return 'site_has_no_field'
  if (!RULE_TYPES.includes(b.type as RuleType)) return 'invalid_rule_type'
  if (SYSTEM.fields[field]?.type !== 'numeric') return 'text_field'
  const p = (b.params ?? {}) as RuleParams
  if (b.type === 'range' && (p.min ?? null) === null && (p.max ?? null) === null) return 'range_needs_a_limit'
  if (
    b.type === 'range' &&
    p.min !== null &&
    p.max !== null &&
    p.min !== undefined &&
    p.max !== undefined &&
    p.min >= p.max
  )
    return 'invalid_range'
  if (b.type === 'stuck' && !(Number.isInteger(p.minutes) && p.minutes! >= 5 && p.minutes! <= 1440))
    return 'invalid_minutes'
  if (b.type === 'spike' && !((p.max_change ?? 0) > 0)) return 'invalid_change'
  if (
    b.type === 'spike' &&
    p.window !== undefined &&
    !(Number.isInteger(p.window) && p.window >= 1 && p.window <= 60)
  )
    return 'invalid_window'
  return null
}

const daysOf = (start: string, end: string, now: number) => {
  const a = iso(Math.floor(Date.parse(start) / DAY) * DAY).slice(0, 10)
  const b = iso(Math.min(Math.floor((Date.parse(end) - MIN) / DAY) * DAY, Math.floor(now / DAY) * DAY)).slice(
    0,
    10,
  )
  return { a, b }
}

// ---------------------------------------------------------------------------------- routes
/** GET /systems/{code}/detections: confirmed for everyone; suspect and rejected for signed-in users. */
export function publicDetections(url: URL): Response {
  const q = url.searchParams
  const from = Date.parse(q.get('from') ?? '')
  const to = Date.parse(q.get('to') ?? '')
  const scope = (q.get('scope') ?? '').split(':')
  const full = signedIn()
  return json(
    dqState()
      .detections.filter((d) => full || d.status === 'confirmed')
      .filter((d) => Date.parse(d.end) > from && Date.parse(d.start) < to)
      .filter((d) =>
        scope[0] === 'component'
          ? d.site === scope[1] && d.component === scope[2]
          : scope[0] === 'site'
            ? d.site === scope[1]
            : true,
      )
      .sort((a, b) => Date.parse(a.start) - Date.parse(b.start))
      .map((d) => detectionView(d, full)),
  )
}

/** Suspects waiting for review that overlap [from, to) (the data-quality summary's period). */
export function pendingSuspectsIn(from: number, to: number): number {
  return dqState().detections.filter(
    (d) => d.status === 'suspect' && Date.parse(d.start) < to && Date.parse(d.end) > from,
  ).length
}

/** Pending suspects, for the Problems panel (signed-in users only). */
export function pendingSuspects(): number {
  return dqState().detections.filter((d) => d.status === 'suspect').length
}

export function dqRoute(
  path: string,
  url: URL,
  method: string,
  body: unknown,
  user: string,
): Response | null {
  if (!/^\/admin\/(rules|detections)/.test(path)) return null
  const now = Date.now()
  const st = dqState()
  const q = url.searchParams
  const b = (body ?? {}) as Record<string, unknown>

  // Proposed rules start from the history's proposal, as the real ones will (OPEN-08).
  for (const r of st.rules)
    if (r.proposed && r.versions.length === 1 && r.versions[0]!.created_by === 'system' && !r.synced) {
      r.versions[0]!.params =
        history(r.component_type, r.field, now).proposed[r.type] ?? r.versions[0]!.params
      r.synced = true
      saveDq()
    }
  if (path === '/admin/rules' && method === 'GET')
    return json(
      st.rules
        .map(ruleView)
        .sort(
          (x, y) =>
            x.component_type.localeCompare(y.component_type) || x.field.localeCompare(y.field) || x.id - y.id,
        ),
    )
  if (path === '/admin/rules/history' && method === 'GET')
    return json(history(q.get('component_type') ?? '', q.get('field') ?? '', now))
  if (path === '/admin/rules/dry-run' && method === 'GET') {
    let params: RuleParams
    try {
      params = JSON.parse(q.get('params') ?? '{}') as RuleParams
    } catch {
      return problem(422, 'invalid_params')
    }
    const draft = {
      component_type: q.get('component_type'),
      field: q.get('field'),
      site: q.get('site') || null,
      type: q.get('type'),
      params,
    }
    const code = checkDraft(draft)
    if (code) return problem(422, code)
    const rid = q.get('rule_id') ? Number(q.get('rule_id')) : null
    return json(
      dryRun(draft.component_type!, draft.field!, draft.site, draft.type as RuleType, params, now, rid),
    )
  }
  const detectJob = () =>
    enqueueJob('detect', SYSTEM.coverage_start.slice(0, 10), iso(now).slice(0, 10), user, now)
  if (path === '/admin/rules' && method === 'POST') {
    const code = checkDraft(b)
    if (code) return problem(422, code)
    const site = (b.site as string | null) ?? null
    if (
      st.rules.some(
        (r) =>
          r.component_type === b.component_type &&
          r.field === b.field &&
          r.type === b.type &&
          latest(r).site === site,
      )
    )
      return problem(409, 'rule_exists')
    const r: StoredRule = {
      id: Math.max(0, ...st.rules.map((x) => x.id)) + 1,
      component_type: String(b.component_type),
      field: String(b.field),
      site,
      type: b.type as RuleType,
      proposed: false,
      versions: [
        {
          version: 1,
          params: b.params as RuleParams,
          enabled: !!b.enabled,
          site,
          created_by: user,
          created_at: iso(now),
        },
      ],
    }
    st.rules.push(r)
    saveDq()
    return json({ rule: ruleView(r), job: b.enabled ? detectJob() : null, withdrawn: 0 }, 201)
  }
  const rv = path.match(/^\/admin\/rules\/(\d+)(\/versions)?$/)
  if (rv) {
    const r = st.rules.find((x) => x.id === Number(rv[1]))
    if (!r) return problem(404, 'rule_not_found')
    if (rv[2] && method === 'GET') return json([...r.versions].reverse())
    if (!rv[2] && method === 'DELETE') {
      if (st.detections.some((d) => d.rule_id === r.id)) return problem(409, 'rule_has_detections')
      st.rules = st.rules.filter((x) => x.id !== r.id)
      saveDq()
      return json({ deleted: r.id })
    }
    if (method === 'PUT') {
      const code = checkDraft({ ...b, component_type: r.component_type, field: r.field, type: r.type })
      if (code) return problem(422, code)
      const v = latest(r)
      const next = {
        params: b.params as RuleParams,
        enabled: !!b.enabled,
        site: (b.site as string | null) ?? null,
      }
      if (
        JSON.stringify([v.params, v.enabled, v.site]) ===
        JSON.stringify([next.params, next.enabled, next.site])
      )
        return json({ rule: ruleView(r), job: null, withdrawn: 0 })
      r.versions.push({ version: v.version + 1, ...next, created_by: user, created_at: iso(now) })
      r.proposed = false
      // The new version replaces the old ones: their open suspects are withdrawn.
      const before = st.detections.length
      st.detections = st.detections.filter((d) => !(d.rule_id === r.id && d.status === 'suspect'))
      const withdrawn = before - st.detections.length
      saveDq()
      return json({ rule: ruleView(r), job: next.enabled ? detectJob() : null, withdrawn })
    }
  }

  if (path === '/admin/detections' && method === 'GET') {
    const status = (q.get('status') ?? 'suspect') as DetectionStatus
    const match = (d: StoredDetection) =>
      (!q.get('site') || d.site === q.get('site')) &&
      (!q.get('component') || d.component === q.get('component')) &&
      (!q.get('field') || d.field === q.get('field')) &&
      (!q.get('type') || d.type === q.get('type')) &&
      (!q.get('from') || d.end > `${q.get('from')}`) &&
      (!q.get('to') || d.start < `${q.get('to')}T24`)
    const all = st.detections.filter(match)
    const counts = { suspect: 0, confirmed: 0, rejected: 0 }
    for (const d of all) counts[d.status]++
    const list = all
      .filter((d) => d.status === status)
      .sort((x, y) =>
        status === 'suspect'
          ? Date.parse(y.start) - Date.parse(x.start)
          : Date.parse(y.decided_at ?? y.start) - Date.parse(x.decided_at ?? x.start),
      )
    const offset = Number(q.get('offset') ?? 0)
    return json({
      total: list.length,
      counts,
      detections: list.slice(offset, offset + 50).map((d) => detectionView(d)),
    })
  }
  if (path === '/admin/detections/decide' && method === 'POST') {
    const ids = Array.isArray(b.ids) ? (b.ids as number[]) : []
    const decision = b.decision
    if (!ids.length) return problem(422, 'no_detections')
    if (decision !== 'confirm' && decision !== 'reject') return problem(422, 'invalid_decision')
    const found = ids.map((id) => st.detections.find((d) => d.id === id))
    if (found.some((d) => !d)) return problem(404, 'detection_not_found')
    const status: DetectionStatus = decision === 'confirm' ? 'confirmed' : 'rejected'
    const touched: string[] = []
    for (const d of found as StoredDetection[]) {
      if (d.status === status) continue
      // A mandatory field's detection changes the figures when it becomes, or stops being, confirmed.
      if (d.mandatory && (status === 'confirmed' || d.status === 'confirmed')) {
        const { a, b: z } = daysOf(d.start, d.end, now)
        touched.push(a, z)
      }
      d.status = status
      d.decided_by = user
      d.decided_at = iso(now)
      d.note = typeof b.note === 'string' && b.note.trim() ? b.note.trim() : null
    }
    saveDq()
    return json({
      decided: (found as StoredDetection[]).map((d) => detectionView(d)),
      job: touched.length
        ? enqueueRecompute(
            touched.reduce((x, y) => (y < x ? y : x)),
            touched.reduce((x, y) => (y > x ? y : x)),
            user,
            now,
          )
        : null,
    })
  }
  return problem(405, 'method_not_allowed')
}

export const isAdmin = () => currentUser()?.role === 'admin'
