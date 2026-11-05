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
  /** How a numeric field is drawn: a line, dots (wind direction, cloud base) or as gust events (WGS, WGD). */
  chart?: 'line' | 'dots' | 'gust'
  series?: NumericSeries
  text?: TextSeries
  sky?: SkySummary
  weather?: WeatherSummary
  lightning?: LightningSummary
  stats: FieldStats
}

export type Cover = 'FEW' | 'SCT' | 'BKN' | 'OVC'
export type CloudBand = 'low' | 'middle' | 'high'

export interface SkySummary {
  bucket_minutes: number
  bands: { low_top_ft: number; middle_top_ft: number }
  /** Minutes in which a band's densest layer had this coverage. */
  band_minutes: Record<CloudBand, Record<Cover, number>>
  clear_minutes: number
  obscured_minutes: number
  reported_minutes: number
  lowest_ceiling: { height_ft: number; cover: Cover | 'VV'; time: string } | null
  /** Each time bucket's most frequent sky: layers as [cover, height_ft, CB/TCU or null]. */
  timeline: {
    t: number
    layers: [Cover, number, string | null][]
    vv: number | null
    obscured: boolean
    clear: boolean
  }[]
}

/** [start_ms, end_ms (exclusive), level 1 light / in the vicinity, 2 moderate, 3 heavy, most frequent code] */
export type Segment = [number, number, number, string]

export type WeatherRow = 'thunderstorm' | 'rain' | 'drizzle' | 'mist_fog' | 'haze' | 'other'
export interface WeatherSummary {
  rows: { key: WeatherRow; minutes: number; segments: Segment[] }[]
  weather_minutes: number
  reported_minutes: number
}

export type LightningRow = 'airport' | 'vicinity' | 'distant'
export interface LightningSummary {
  rows: { key: LightningRow; minutes: number; segments: Segment[] }[]
  /** Minutes with distant lightning seen in each direction (ALQDS: all around). */
  directions: Record<string, number>
  episodes: number
  first: string | null
  last: string | null
  reported_minutes: number
}

export interface GustEvent {
  start: string
  minutes: number
  max_kt: number
  direction_deg: number | null
}

export interface FieldStats {
  last: { time: string; value: number | string } | null
  count: number
  min?: number | null
  max?: number | null
  mean?: number | null
  /** Cloud base: minutes reading 0 (no cloud detected), left out of count/min/max/mean. */
  zero_minutes?: number
}

export interface WindSummary {
  rose: ({ sector: number } & Record<string, number>)[]
  max_speed_kt: number | null
  min_speed_kt: number | null
  gust: {
    count: number
    max_speed_kt: number | null
    direction_deg: number | null
    event_count?: number
    minutes?: number
    strongest?: GustEvent | null
    events?: GustEvent[]
    events_truncated?: boolean
  }
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
  period: {
    from: string
    to: string
    evaluated_to: string
    as_of: string
    open: boolean
    /** days in this period still being recalculated after a flag or rule change (R2.3) */
    recalculating?: { from: string; to: string }[]
  }
  bucket: MatrixBucket
  buckets: { start: string; end: string }[]
  rows: MatrixRow[]
}

export interface MinuteInterval {
  start: string
  end: string
  minutes: number
  cause: 'field_missing' | 'no_data' | 'flagged' | 'detection'
  /** flagged only: the flags that cover the interval */
  flags?: FlagRef[]
  /** detection only: the confirmed detection behind the interval */
  detections?: DetectionRef[]
}

export interface MinutesResponse {
  scope: string
  day: string
  /**
   * One letter per minute: v valid, f mandatory field missing, n no data, g flagged, d confirmed detection,
   * s valid but a suspect detection covers it (signed-in users only), u not counted.
   */
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
  /** flagged only: the flags that cover the interval */
  flags?: FlagRef[]
  /** detection only: the confirmed detection behind the interval */
  detections?: DetectionRef[]
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

// ---------------------------------------------------------------- accounts and audit (R2.1, FR-AUTH, FR-AUD)

export type Role = 'viewer' | 'admin'

/** The signed-in user (GET /auth/me). */
export interface Me {
  id: number
  username: string
  display_name: string
  role: Role
  must_change_password: boolean
}

export interface UserRow {
  id: number
  username: string
  display_name: string
  email: string | null
  role: Role
  active: boolean
  /** set while the account is locked after failed sign-ins (FR-AUTH-004) */
  locked_until: string | null
  /** a temporary password from an Admin is still waiting to be changed at the first sign-in */
  password_temporary: boolean
  last_login_at: string | null
  created_at: string
}

export interface NewUser {
  username: string
  display_name: string
  email: string | null
  role: Role
}

/** A new account or a reset: the temporary password is shown once and must be changed at first sign-in. */
export interface TemporaryPassword {
  user: UserRow
  temporary_password: string
}

export interface AuditEvent {
  id: number
  time: string
  actor: string | null
  action: string
  entity_type: string | null
  entity_id: string | null
  before: Record<string, unknown> | null
  after: Record<string, unknown> | null
  source_ip: string | null
}

export interface AuditPage {
  events: AuditEvent[]
  /** id to pass as `before` for the next (older) page, or null at the end */
  next_before: number | null
  actors: string[]
  actions: string[]
}

export interface AuditFilter {
  from?: string
  to?: string
  actor?: string
  action?: string
  entity_type?: string
}

// ---------------------------------------------------------------- admin operations (R2.2, FR-ADM-002/003, FR-REG-003/006)

export type JobType = 'reprocess' | 'recompute' | 'import_legacy' | 'detect'
export type JobStatus = 'queued' | 'running' | 'done' | 'failed' | 'cancelled' | 'interrupted'

export interface JobRow {
  id: number
  type: JobType
  params: { system?: string; from?: string; to?: string }
  status: JobStatus
  progress: number
  message: string | null
  created_by: string
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export interface JobDetail extends JobRow {
  log: string
}

export interface NewJob {
  type: 'reprocess' | 'recompute'
  system: string
  from: string
  to: string
}

export interface ProblemThresholds {
  cdp_no_data_min: number
  cdp_unreachable_min: number
  site_no_data_min: number
  field_missing_min: number
  ingest_lag_min: number
}

export interface AdminSettings {
  color_thresholds: { good: number; warning: number }
  grace_minutes: number
  problem_thresholds: ProblemThresholds
  /** who last changed each setting, and when */
  changed: Record<string, { at: string; by: string }>
}

export type SettingKey = 'color_thresholds' | 'grace_minutes' | 'problem_thresholds'

export interface MandatoryField {
  code: string
  name: Names
  mandatory: boolean
}

export interface MandatoryType {
  type: string
  name: Names
  is_dcp: boolean
  fields: MandatoryField[]
}

/** This month's availability per site for a component type, now and with the proposed mandatory fields. */
export interface MandatoryPreview {
  type: string
  from: string
  to: string
  sites: { slug: string; name: Names; current: Availability; proposed: Availability }[]
}

export interface ComponentRow {
  id: number
  site: string
  site_name: Names
  type: string
  name: Names
  is_dcp: boolean
  in_service_from: string | null
  in_service_to: string | null
}

// ---------------------------------------------------------------- manual flags (R2.3, FR-DQ-006/007)

export const FLAG_REASONS = ['sensor_fault', 'maintenance', 'calibration', 'environmental', 'other'] as const
export type FlagReason = (typeof FLAG_REASONS)[number]

/** What everyone may see about a flag: its time range and reason. */
export interface FlagRef {
  id: number
  reason: FlagReason
}

/** A flag as charts and the minute view show it. Note and author are for signed-in users only. */
export interface Flag extends FlagRef {
  start: string
  /** exclusive */
  end: string
  components: { site: string; type: string }[]
  note?: string
  created_by?: string
  created_at?: string
}

/** A flag in the Admin list, with its components' ids and its history. */
export interface FlagRow extends Flag {
  component_ids: number[]
  note: string
  created_by: string
  created_at: string
  updated_by: string | null
  updated_at: string | null
  removed_by: string | null
  removed_at: string | null
}

export interface FlagDraft {
  system: string
  component_ids: number[]
  start: string
  end: string
  reason: FlagReason
  note: string
}

/** What a flag would change, per component: minutes in the range that are valid now and would count as lost. */
export interface FlagPreview {
  start: string
  end: string
  components: {
    id: number
    site: string
    type: string
    /** expected minutes inside the range */
    minutes: number
    /** valid now and lost once flagged: the drop in the component's valid minutes */
    lost: number
    /** already lost for another reason (no data, field missing, another flag) */
    already: number
  }[]
  /** UTC days whose figures will be recalculated */
  days: { from: string; to: string } | null
}

export interface FlagChange {
  flag: FlagRow
  job: JobRow | null
}

// ---------------------------------------------------------------- rules and detections (R2.4, FR-DQ-001..005)

export const RULE_TYPES = ['range', 'stuck', 'spike'] as const
export type RuleType = (typeof RULE_TYPES)[number]

/** range: min/max · stuck: minutes (+ values to ignore) · spike: max_change (+ window in minutes) */
export interface RuleParams {
  min?: number | null
  max?: number | null
  minutes?: number
  ignore?: number[]
  max_change?: number
  window?: number
}

export interface Rule {
  id: number
  component_type: string
  field: string
  /** null: every site with this component type; a slug: only there, replacing the type-wide rule of this type */
  site: string | null
  type: RuleType
  params: RuleParams
  enabled: boolean
  /** proposed from history and never approved: stays off until an Admin turns it on (OPEN-08) */
  proposed: boolean
  version: number
  changed_by: string
  changed_at: string
  /** the field decides availability: a confirmed detection invalidates the component (FR-DQ-005) */
  mandatory: boolean
  suspects: number
}

export interface RuleVersion {
  version: number
  params: RuleParams
  enabled: boolean
  site: string | null
  created_by: string
  created_at: string
}

export interface RuleDraft {
  system: string
  component_type: string
  field: string
  site: string | null
  type: RuleType
  params: RuleParams
  enabled: boolean
}

/** What the history says about a field (OPEN-08), and the starting values proposed from it. */
export interface FieldHistory {
  component_type: string
  field: string
  unit: string | null
  from: string | null
  to: string | null
  /** when the statistics were worked out (stored; refreshed weekly) */
  computed_at?: string
  minutes: number
  /** 0.1 % and 99.9 % of the values, and the extremes */
  p001: number
  p999: number
  min: number
  max: number
  /** longest run of one unchanged value, and the 99th percentile of runs */
  longest_run_minutes: number
  run_p99_minutes: number
  /** largest change between consecutive minutes, and its 99.9th percentile */
  largest_step: number
  step_p999: number
  /** no spike proposal for fields that jump by nature (direction, rain, light) */
  proposed: Partial<Record<RuleType, RuleParams>>
}

/** What a rule would have raised over a recent period, before saving it. */
export interface RuleDryRun {
  from: string
  to: string
  intervals: number
  minutes: number
  sites: number
  examples: { site: string; start: string; end: string; minutes: number; evidence: Evidence }[]
}

export type DetectionStatus = 'suspect' | 'confirmed' | 'rejected'

/** Why a rule fired, in numbers: the value (range, stuck) or the jump (spike). */
export interface Evidence {
  value?: number
  low?: number
  high?: number
  change?: number
}

export interface DetectionRef {
  id: number
  field: string
  type: RuleType
}

export interface Detection extends DetectionRef {
  site: string
  component: string
  rule_id: number
  rule_version: number
  /** the rule's parameters when it fired (FR-DQ-003): later edits do not change them */
  params: RuleParams
  start: string
  /** exclusive */
  end: string
  minutes: number
  status: DetectionStatus
  mandatory: boolean
  evidence: Evidence
  decided_by?: string | null
  decided_at?: string | null
  note?: string | null
}

export interface DetectionFilter {
  status: DetectionStatus
  site?: string
  component?: string
  field?: string
  type?: RuleType | ''
  from?: string
  to?: string
}

export interface DetectionPage {
  total: number
  counts: Record<DetectionStatus, number>
  detections: Detection[]
}

export interface Decision {
  ids: number[]
  decision: 'confirm' | 'reject'
  note?: string
}

export interface RuleChange {
  rule: Rule
  /** the detection run over the history that the change queued, if any */
  job: JobRow | null
}

export interface DecisionResult {
  decided: Detection[]
  job: JobRow | null
}
