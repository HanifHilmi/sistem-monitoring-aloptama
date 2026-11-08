// Sample data-quality summary (R3.3) for dev:sample and CI: built from the sample outage list of each component, so
// its minutes equal the flagged and detection minutes there (the R3.3 acceptance). The definitions version is fixed.
import type { DataQualitySummary, Definitions, DqComponent, DqReason } from '@/api/types'
import { MAX_OUTAGE_SPAN, outages, SYSTEM } from './data'

export const DEFINITIONS: Definitions = {
  version: '1.0',
  effective_from: SYSTEM.coverage_start.slice(0, 10),
  source: 'PRD v1.1 §7.3.1',
}

function add(
  list: DqReason[],
  kind: DqReason['kind'],
  reason: string,
  minutes: number,
  ref: number,
  seen: Set<string>,
) {
  let r = list.find((x) => x.kind === kind && x.reason === reason)
  if (!r) list.push((r = { kind, reason, minutes: 0, count: 0 }))
  r.minutes += minutes
  if (!seen.has(`${kind}:${reason}:${ref}`)) {
    seen.add(`${kind}:${reason}:${ref}`)
    r.count++
  }
}

/** FR-DQ-008 for [from, to); `pending` is the suspect count for a signed-in user, null for the public. */
export function summary(
  from: number,
  to: number,
  now: number,
  pending: number | null,
): DataQualitySummary | string {
  if (!(from < to)) return 'invalid_period'
  if (to - from > MAX_OUTAGE_SPAN) return 'period_too_long'
  const components: DqComponent[] = []
  const reasons: DqReason[] = []
  const seenAll = new Set<string>()
  const flags = new Set<number>()
  const detections = new Set<number>()
  let period: DataQualitySummary['period'] | null = null
  for (const site of SYSTEM.sites) {
    for (const c of site.components) {
      if (c.is_dcp) continue // flags and detections never touch a DCP
      const o = outages(from, to, `component:${site.slug}:${c.type}`, now, 100_000)
      period ??= o.period
      const row: DqComponent = {
        site: site.slug,
        component: c.type,
        flagged_minutes: 0,
        flags: 0,
        detection_minutes: 0,
        detections: 0,
        expected: o.availability.expected,
        reasons: [],
      }
      const seen = new Set<string>()
      const mine = { flags: new Set<number>(), detections: new Set<number>() }
      for (const i of o.intervals) {
        if (i.cause === 'flagged') {
          row.flagged_minutes += i.minutes
          for (const f of i.flags ?? []) {
            mine.flags.add(f.id)
            flags.add(f.id)
            add(row.reasons, 'flag', f.reason, i.minutes, f.id, seen)
            add(reasons, 'flag', f.reason, i.minutes, f.id, seenAll)
          }
        } else if (i.cause === 'detection') {
          row.detection_minutes += i.minutes
          for (const d of i.detections ?? []) {
            mine.detections.add(d.id)
            detections.add(d.id)
            add(row.reasons, 'detection', d.type, i.minutes, d.id, seen)
            add(reasons, 'detection', d.type, i.minutes, d.id, seenAll)
          }
        }
      }
      row.flags = mine.flags.size
      row.detections = mine.detections.size
      if (row.flagged_minutes || row.detection_minutes) components.push(row)
    }
  }
  components.sort(
    (a, b) => b.flagged_minutes + b.detection_minutes - (a.flagged_minutes + a.detection_minutes),
  )
  const byMinutes = (a: DqReason, b: DqReason) => b.minutes - a.minutes
  return {
    system: SYSTEM.code,
    period: period!,
    definitions_version: DEFINITIONS.version,
    flagged_minutes: components.reduce((n, c) => n + c.flagged_minutes, 0),
    flags: flags.size,
    detection_minutes: components.reduce((n, c) => n + c.detection_minutes, 0),
    detections: detections.size,
    pending_suspects: pending,
    components: components.map((c) => ({ ...c, reasons: c.reasons.sort(byMinutes) })),
    reasons: reasons.sort(byMinutes),
  }
}
