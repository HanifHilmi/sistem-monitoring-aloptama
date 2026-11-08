import type { AlarmType, SystemInfo } from '@/api/types'

// CSV exports (FR-EXP-002): what each file holds, its name and its download link. The server writes the files;
// these lists are what the Exports page shows, and a test keeps them equal to the server's header rows.

export const EXPORT_KINDS = ['daily', 'minutes', 'alarms', 'quality'] as const
export type ExportKind = (typeof EXPORT_KINDS)[number]

/** Longest period in one file, in days. 1-minute data: 31 days (FR-EXP-002); the rest: a year, like the alarm list. */
export const MAX_DAYS: Record<ExportKind, number> = { daily: 366, minutes: 31, alarms: 366, quality: 366 }

export interface ExportOptions {
  /** minutes: the site's slug */
  site?: string
  /** alarms: the same filters as the alarm history */
  type?: AlarmType
  scope?: string
  /** quality: also suspect and rejected detections (they do not count in any figure) */
  all?: boolean
  /** quality: which records */
  flags?: boolean
  detections?: boolean
}

/** One column: its header as written in the file, and an example value. The meaning is `exports.col.<key>`. */
export interface Column {
  name: string
  key: string
  example: string
}

/** Every file ends with these two (FR-KPI-008: exports carry the definitions version and when they were made). */
const TRAILER: Column[] = [
  { name: 'definitions_version', key: 'definitions_version', example: '1.0' },
  { name: 'generated_at_utc', key: 'generated_at_utc', example: '2026-11-08T05:30:12Z' },
]

export const DAILY_COLUMNS: Column[] = [
  { name: 'date_utc', key: 'date_utc', example: '2026-11-01' },
  { name: 'scope', key: 'scope', example: 'component' },
  { name: 'cdp', key: 'cdp', example: '' },
  { name: 'site', key: 'site', example: 'RWY04' },
  { name: 'component', key: 'component', example: 'ATRH' },
  { name: 'expected_min', key: 'expected_min', example: '1440' },
  { name: 'valid_min', key: 'valid_min', example: '1432' },
  { name: 'missing_min', key: 'missing_min', example: '8' },
  { name: 'availability_pct', key: 'availability_pct', example: '99.44' },
  { name: 'reachable_min', key: 'reachable_min', example: '' },
  { name: 'probed_min', key: 'probed_min', example: '' },
  ...TRAILER,
]

export const ALARM_COLUMNS: Column[] = [
  { name: 'time_utc', key: 'alarm_time', example: '2026-11-03T10:43:12Z' },
  { name: 'alarm_name', key: 'alarm_name', example: 'DCPA_Missing' },
  { name: 'type', key: 'alarm_type', example: 'error' },
  { name: 'change', key: 'alarm_change', example: 'raised' },
  { name: 'state', key: 'alarm_state', example: 'pending' },
  { name: 'place', key: 'alarm_place', example: 'component' },
  { name: 'site', key: 'site', example: 'RWY04' },
  { name: 'component', key: 'component', example: 'DCP' },
  { name: 'message', key: 'alarm_message', example: 'Missing data from DCP A' },
  { name: 'cdps', key: 'alarm_cdps', example: 'CDP1 CDP2' },
  ...TRAILER,
]

export const QUALITY_COLUMNS: Column[] = [
  { name: 'kind', key: 'q_kind', example: 'flag' },
  { name: 'id', key: 'q_id', example: '12' },
  { name: 'site', key: 'site', example: 'RWY04' },
  { name: 'component', key: 'component', example: 'BARO' },
  { name: 'field', key: 'q_field', example: '' },
  { name: 'start_utc', key: 'q_start', example: '2026-11-03T10:00:00Z' },
  { name: 'end_utc', key: 'q_end', example: '2026-11-03T11:00:00Z' },
  { name: 'minutes', key: 'q_minutes', example: '60' },
  { name: 'reason', key: 'q_reason', example: 'maintenance' },
  { name: 'status', key: 'q_status', example: 'active' },
  { name: 'counts', key: 'q_counts', example: 'true' },
  { name: 'rule_id', key: 'q_rule', example: '' },
  { name: 'rule_version', key: 'q_rule_version', example: '' },
  { name: 'note', key: 'q_note', example: 'Barometer swapped' },
  { name: 'by', key: 'q_by', example: 'andi' },
  { name: 'at_utc', key: 'q_at', example: '2026-11-03T11:05:40Z' },
  ...TRAILER,
]

/** The 1-minute file of a site: the time, the CDPs, then per sensor its status and its fields with their units. */
export interface MinuteLayout {
  lead: Column[]
  sensors: { type: string; status: string; fields: string[] }[]
  trailer: Column[]
}

export function minuteLayout(info: SystemInfo, slug: string): MinuteLayout {
  const site = info.sites.find((s) => s.slug === slug)
  return {
    lead: [
      { name: 'time_utc', key: 'minute_time', example: '2026-11-01T00:00:00Z' },
      { name: 'cdps', key: 'minute_cdps', example: 'CDP1 CDP2' },
    ],
    sensors: (site?.components ?? []).map((c) => ({
      type: c.type,
      status: `${c.type}.status`,
      fields: c.fields.map((f) => {
        const unit = info.fields[f]?.unit
        return unit ? `${c.type}.${f} (${unit})` : `${c.type}.${f}`
      }),
    })),
    trailer: TRAILER,
  }
}

export function minuteHeader(l: MinuteLayout): string[] {
  return [
    ...l.lead.map((c) => c.name),
    ...l.sensors.flatMap((s) => [s.status, ...s.fields]),
    ...l.trailer.map((c) => c.name),
  ]
}

/** What a sensor's status column can say for a minute (the minute map's letters, spelled out). */
export const MINUTE_STATUSES = [
  'valid',
  'field_missing',
  'no_data',
  'flagged',
  'detection',
  'not_counted',
] as const

const MIN = 60_000
const DAY = 86_400_000

/** One row per UTC day and scope: the system, each CDP, each site and each sensor. */
export function dailyRowsPerDay(info: SystemInfo): number {
  return 1 + info.cdps.length + info.sites.length + info.sites.reduce((n, s) => n + s.components.length, 0)
}

/** Rows a file will have; `count` is the number of records for alarms and data quality (from the API). */
export function estimateRows(
  kind: ExportKind,
  info: SystemInfo,
  from: Date,
  to: Date,
  now: number,
  count: number | null,
): number | null {
  const end = Math.min(to.getTime(), now)
  if (kind === 'daily') return Math.max(0, Math.ceil((end - from.getTime()) / DAY)) * dailyRowsPerDay(info)
  if (kind === 'minutes') return Math.max(0, Math.floor((end - from.getTime()) / MIN))
  return count
}

/** Rough bytes per row, measured on sample files; only for the "about 3 MB" hint. */
export function estimateBytes(kind: ExportKind, rows: number, columns: number): number {
  const perRow = { daily: 78, minutes: 30 + columns * 5, alarms: 150, quality: 140 }[kind]
  return rows * perRow
}

const stamp = (d: Date) =>
  d.getUTCHours() || d.getUTCMinutes()
    ? `${d.toISOString().slice(0, 13)}${d.toISOString().slice(14, 16)}Z`
    : d.toISOString().slice(0, 10)

/**
 * `SIMOLA_<system>_<kind>[_<site>]_<first>_<last>.csv`, like the monthly PDF's name. Whole days are named by the
 * first and last day included (the period's end is exclusive); other bounds by their minute.
 */
export function exportFileName(
  system: string,
  kind: ExportKind,
  from: Date,
  to: Date,
  siteCode?: string,
): string {
  const whole = !to.getUTCHours() && !to.getUTCMinutes()
  const last = whole ? new Date(to.getTime() - DAY) : to
  return `SIMOLA_${system}_${kind}${siteCode ? `_${siteCode}` : ''}_${stamp(from)}_${stamp(last)}.csv`
}

/** The download link; the server checks the role, the limits and records the export in the audit log. */
export function exportUrl(
  system: string,
  kind: ExportKind,
  from: Date,
  to: Date,
  o: ExportOptions = {},
): string {
  const q = new URLSearchParams({ from: from.toISOString(), to: to.toISOString() })
  if (kind === 'minutes' && o.site) q.set('site', o.site)
  if (kind === 'alarms') {
    if (o.type) q.set('type', o.type)
    if (o.scope) q.set('scope', o.scope)
  }
  if (kind === 'quality') {
    const records = [o.flags !== false && 'flags', o.detections !== false && 'detections'].filter(Boolean)
    q.set('records', records.join(','))
    if (o.all) q.set('all', '1')
  }
  return `/api/v1/systems/${encodeURIComponent(system)}/exports/${kind}.csv?${q.toString()}`
}
