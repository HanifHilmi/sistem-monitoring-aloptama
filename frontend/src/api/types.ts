// Response types of the public SIMOLA API (/api/v1). Times are ISO-8601 UTC strings.

export interface Names {
  en: string
  id: string
}

export interface Availability {
  valid: number
  expected: number
  missing: number
  pct: number | null
}

export interface ComponentInfo {
  type: string
  is_dcp: boolean
  name: Names
  fields: string[]
  mandatory: string[]
  in_service_from: string | null
  in_service_to: string | null
}

export interface SiteInfo {
  code: string
  slug: string
  station_code: string
  name: Names
  components: ComponentInfo[]
}

export interface FieldInfo {
  unit: string | null
  type: 'numeric' | 'text'
  name: Names
}

export interface SystemInfo {
  code: string
  type: string
  kpi_profile: string
  name: Names
  icao: string | null
  coverage_start: string
  cdps: { code: string; preference: number }[]
  sites: SiteInfo[]
  fields: Record<string, FieldInfo>
}

export interface SystemSummary {
  code: string
  type: string
  name: Names
  icao: string | null
  sla_today: Availability
  sla_month: Availability
  ola_month: { pct: number | null }
  problems: number
  last_data_minute: string | null
}

export interface KpiResponse {
  system: string
  period: {
    from: string
    to: string
    evaluated_from: string
    evaluated_to: string
    as_of: string
    open: boolean
    coverage_start: string
  }
  sla: Availability
  cdps: {
    code: string
    uptime: Availability
    reachability: {
      reachable: number
      sampled: number
      pct: number | null
      probe_coverage_pct: number | null
      legacy_minutes: number
    }
  }[]
  sites: {
    code: string
    slug: string
    availability: Availability
    components: { type: string; is_dcp: boolean; availability: Availability }[]
  }[]
  ola: { pct: number | null }
  pooled: Availability
}

export type ComponentStatus = 'valid' | 'field_missing' | 'no_data' | 'stale' | 'not_in_service' | 'unknown'

export interface StatusResponse {
  generated_at: string
  grace_minutes: number
  ingestion_stale: boolean
  ingestion: {
    cdp: string | null
    available: boolean
    stale: boolean
    lag_min: number | null
    last_record_time: string | null
  }[]
  cdps: {
    code: string
    data_flow: 'producing' | 'not_producing' | 'unknown'
    last_data_minute: string | null
    reachability: 'reachable' | 'unreachable' | 'degraded' | 'unknown'
    rtt_ms: number | null
  }[]
  sites: {
    code: string
    slug: string
    last_data_minute: string | null
    no_data: boolean
    components_online: number
    components_total: number
    components: { type: string; is_dcp: boolean; status: ComponentStatus; last_valid_minute: string | null }[]
  }[]
  last_data_minute: string | null
}

export type Severity = 'critical' | 'major' | 'minor' | 'info'

export interface Problem {
  code: string
  severity: Severity
  link: string
  params: Record<string, string | number | null>
}

export interface ProblemsResponse {
  generated_at: string
  problems: Problem[]
}

export interface HistoryResponse {
  bucket: string
  rows: {
    start: string
    sla: Availability
    ola: { pct: number | null }
    cdps: Record<string, Availability>
  }[]
}

export interface CalendarResponse {
  year: number
  metric: string
  days: ({ day: string; pct: number | null } & Partial<Availability>)[]
}

export interface NumericSeries {
  t: number[]
  v: (number | null)[]
  downsampled: boolean
}

export interface TextSeries {
  transitions: [number, string | null][]
  truncated: boolean
  counts: { value: string; minutes: number }[]
  missing_minutes: number
}

export interface SeriesField {
  code: string
  unit: string | null
  type: 'numeric' | 'text'
  mandatory: boolean
  series?: NumericSeries
  text?: TextSeries
  stats: FieldStats
}

export interface FieldStats {
  last: { time: string; value: number | string } | null
  count: number
  min?: number | null
  max?: number | null
  mean?: number | null
}

export interface WindSummary {
  rose: ({ sector: number } & Record<string, number>)[]
  max_speed_kt: number | null
  min_speed_kt: number | null
  gust: { count: number; max_speed_kt: number | null; direction_deg: number | null }
}

export interface SeriesResponse {
  component: string
  from: string
  to: string
  fields: SeriesField[]
  availability: Availability
  wind?: WindSummary
}

export interface DisplaySettings {
  color_thresholds: { good: number; warning: number }
  grace_minutes: number
}

export type MatrixBucket = 'day' | 'week' | 'month'

export interface MatrixCell {
  valid?: number
  expected?: number
  missing?: number
  pct: number | null
}

export interface MatrixRow {
  key: string
  kind: 'sla' | 'cdp' | 'ola' | 'site' | 'component'
  cdp?: string
  site?: string
  type?: string
  is_dcp?: boolean
  cells: MatrixCell[]
  total: MatrixCell
}

export interface MatrixResponse {
  system: string
  period: { from: string; to: string; evaluated_to: string; as_of: string; open: boolean }
  bucket: MatrixBucket
  buckets: { start: string; end: string }[]
  rows: MatrixRow[]
}

export interface MinuteInterval {
  start: string
  end: string
  minutes: number
  cause: 'field_missing' | 'no_data'
}

export interface MinutesResponse {
  scope: string
  day: string
  codes: string
  valid: number
  expected: number
  intervals: MinuteInterval[]
}

/** Why minutes were lost (FR-KPI-009). `flagged` and `detection` arrive with data quality in R2. */
export type OutageCause = 'cdp_no_data' | 'no_record' | 'field_missing' | 'flagged' | 'detection'

export interface OutageComponent {
  site: string
  component: string
  /** field_missing only: the mandatory fields missing during the interval (empty for a DCP: every field). */
  fields?: string[]
}

export interface Outage {
  start: string
  end: string
  minutes: number
  cause: OutageCause
  /** minutes × components hit: this interval's share of the scope's lost minutes */
  lost_minutes: number
  /** the interval reaches the end of the evaluated part of an open period */
  ongoing: boolean
  /** component scopes (component, site, ola) only; identical intervals of several components are listed once */
  components?: OutageComponent[]
}

export interface OutagesResponse {
  system: string
  scope: string
  period: {
    from: string
    to: string
    evaluated_from: string
    evaluated_to: string
    as_of: string
    open: boolean
  }
  availability: Availability
  /** over every interval, also past the list's limit: adds up to availability.missing */
  by_cause: Record<OutageCause, number>
  intervals_total: number
  truncated: boolean
  intervals: Outage[]
}
