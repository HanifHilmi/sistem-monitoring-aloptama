import type {
  AdminSettings,
  Assets,
  Calibration,
  CalibrationDraft,
  ComponentMeta,
  SiteMeta,
  StationMeta,
  TraceEvent,
  AuditFilter,
  AuditPage,
  ComponentRow,
  Decision,
  DecisionResult,
  Detection,
  DetectionFilter,
  DetectionPage,
  FieldHistory,
  Flag,
  FlagChange,
  FlagDraft,
  FlagPreview,
  FlagRow,
  JobDetail,
  Rule,
  RuleChange,
  RuleDraft,
  RuleDryRun,
  RuleVersion,
  JobRow,
  MandatoryPreview,
  MandatoryType,
  NewJob,
  SettingKey,
  CalendarResponse,
  MatrixBucket,
  MatrixResponse,
  MinutesResponse,
  OutagesResponse,
  DisplaySettings,
  HistoryResponse,
  KpiResponse,
  Me,
  NewUser,
  ProblemsResponse,
  SeriesResponse,
  StatusResponse,
  SystemInfo,
  SystemSummary,
  TemporaryPassword,
  UserRow,
} from './types'

/** RFC 9457 problem returned by the API; `code` is stable and translatable. */
export class ApiProblem extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
  ) {
    super(message)
  }
}

const BASE = '/api/v1'

async function problem(res: Response): Promise<ApiProblem> {
  let code = 'http_error'
  let title = res.statusText
  try {
    const body = (await res.json()) as { code?: string; title?: string }
    code = body.code ?? code
    title = body.title ?? title
  } catch {
    /* not JSON */
  }
  return new ApiProblem(res.status, code, title)
}

type Params = Record<string, string | number | undefined>
const query = (params: Params) => {
  const qs = new URLSearchParams(
    Object.entries(params)
      .filter(([, v]) => v !== undefined && v !== '')
      .map(([k, v]) => [k, String(v)]),
  ).toString()
  return qs ? `?${qs}` : ''
}

async function get<T>(path: string, params: Params = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}${query(params)}`, { headers: { Accept: 'application/json' } })
  if (!res.ok) throw await problem(res)
  return (await res.json()) as T
}

/** CSRF double-submit (PRD §11.6): every change sends the value of the `simola_csrf` cookie in a header. */
function csrfToken(): string {
  const m = document.cookie.match(/(?:^|;\s*)simola_csrf=([^;]+)/)
  return m ? decodeURIComponent(m[1]!) : ''
}

async function send<T>(
  method: 'POST' | 'PATCH' | 'PUT' | 'DELETE',
  path: string,
  body?: unknown,
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: {
      Accept: 'application/json',
      'X-CSRF-Token': csrfToken(),
      ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: 'same-origin',
  })
  if (!res.ok) throw await problem(res)
  return (res.status === 204 ? undefined : await res.json()) as T
}

const period = (from: Date, to: Date) => ({ from: from.toISOString(), to: to.toISOString() })

/** The API lists outages for up to 93 days at a time (FR-KPI-009); longer periods go month by month. */
export const MAX_OUTAGE_DAYS = 93
const OUTAGE_LIMIT = 200

export const api = {
  displaySettings: () => get<DisplaySettings>('/settings/display'),
  systems: () => get<SystemSummary[]>('/systems'),
  system: (code: string) => get<SystemInfo>(`/systems/${encodeURIComponent(code)}`),
  kpis: (code: string, from: Date, to: Date) =>
    get<KpiResponse>(`/systems/${encodeURIComponent(code)}/kpis`, period(from, to)),
  status: (code: string) => get<StatusResponse>(`/systems/${encodeURIComponent(code)}/status`),
  problems: (code: string) => get<ProblemsResponse>(`/systems/${encodeURIComponent(code)}/problems`),
  history: (code: string, from: Date, to: Date, bucket: string) =>
    get<HistoryResponse>(`/systems/${encodeURIComponent(code)}/history`, { ...period(from, to), bucket }),
  calendar: (code: string, year: number, metric: string) =>
    get<CalendarResponse>(`/systems/${encodeURIComponent(code)}/calendar`, { year, metric }),
  series: (code: string, site: string, component: string, from: Date, to: Date) =>
    get<SeriesResponse>(
      `/systems/${encodeURIComponent(code)}/sites/${encodeURIComponent(site)}/components/${encodeURIComponent(component)}/series`,
      period(from, to),
    ),
  matrix: (code: string, from: Date, to: Date, bucket: MatrixBucket) =>
    get<MatrixResponse>(`/systems/${encodeURIComponent(code)}/matrix`, { ...period(from, to), bucket }),
  minutes: (code: string, day: string, scope: string) =>
    get<MinutesResponse>(`/systems/${encodeURIComponent(code)}/minutes`, { day, scope }),
  outages: (code: string, from: Date, to: Date, scope: string, limit = OUTAGE_LIMIT) =>
    get<OutagesResponse>(`/systems/${encodeURIComponent(code)}/outages`, {
      ...period(from, to),
      scope,
      limit,
    }),
  /** Flags touching a scope (`component:<site>:<type>`, `site:<site>` or all) in a period (FR-DQ-007). */
  flags: (code: string, from: Date, to: Date, scope?: string) =>
    get<Flag[]>(`/systems/${encodeURIComponent(code)}/flags`, { ...period(from, to), scope }),
  /** Detections touching a scope in a period: confirmed for everyone, suspect and rejected for signed-in users. */
  detections: (code: string, from: Date, to: Date, scope?: string) =>
    get<Detection[]>(`/systems/${encodeURIComponent(code)}/detections`, { ...period(from, to), scope }),
  /** Station, site and sensor records with calibration status (serial and part numbers for signed-in users). */
  assets: (code: string) => get<Assets>(`/systems/${encodeURIComponent(code)}/assets`),
  /** Changes that moved a scope's figures in a period (signed-in users). */
  trace: (code: string, scope: string, from: Date, to: Date) =>
    get<TraceEvent[]>(`/systems/${encodeURIComponent(code)}/trace`, { ...period(from, to), scope }),
  internalHealth: () => get<Record<string, unknown>>('/internal/health'),

  // Accounts (R2.1)
  /** null for a visitor */
  me: () => get<Me | null>('/auth/me'),
  login: (username: string, password: string) => send<Me>('POST', '/auth/login', { username, password }),
  logout: () => send<void>('POST', '/auth/logout'),
  changePassword: (current_password: string, new_password: string) =>
    send<Me>('POST', '/auth/password', { current_password, new_password }),
  users: () => get<UserRow[]>('/admin/users'),
  createUser: (user: NewUser) => send<TemporaryPassword>('POST', '/admin/users', user),
  updateUser: (id: number, patch: Partial<Pick<UserRow, 'display_name' | 'email' | 'role' | 'active'>>) =>
    send<UserRow>('PATCH', `/admin/users/${id}`, patch),
  resetPassword: (id: number) => send<TemporaryPassword>('POST', `/admin/users/${id}/reset-password`),
  audit: (filter: AuditFilter, before?: number) =>
    get<AuditPage>('/admin/audit', { ...filter, before, limit: 50 }),
  auditCsvUrl: (filter: AuditFilter) => `${BASE}/admin/audit${query({ ...filter, format: 'csv' })}`,

  // Admin operations (R2.2)
  jobs: () => get<JobRow[]>('/admin/jobs'),
  job: (id: number) => get<JobDetail>(`/admin/jobs/${id}`),
  startJob: (job: NewJob) => send<JobRow>('POST', '/admin/jobs', job),
  cancelJob: (id: number) => send<JobRow>('POST', `/admin/jobs/${id}/cancel`),
  adminSettings: () => get<AdminSettings>('/admin/settings'),
  saveSetting: <K extends SettingKey>(key: K, value: AdminSettings[K]) =>
    send<AdminSettings>('PUT', `/admin/settings/${key}`, { value }),
  mandatoryFields: (system: string) => get<MandatoryType[]>('/admin/mandatory-fields', { system }),
  previewMandatory: (system: string, type: string, fields: string[]) =>
    get<MandatoryPreview>(`/admin/mandatory-fields/${encodeURIComponent(type)}/preview`, {
      system,
      fields: fields.join(','),
    }),
  saveMandatory: (system: string, type: string, fields: string[]) =>
    send<{ job: JobRow }>('PUT', `/admin/mandatory-fields/${encodeURIComponent(type)}`, { system, fields }),
  components: (system: string) => get<ComponentRow[]>('/admin/components', { system }),
  saveInService: (id: number, from: string | null, to: string | null) =>
    send<{ component: ComponentRow; job: JobRow | null }>('PATCH', `/admin/components/${id}`, {
      in_service_from: from,
      in_service_to: to,
    }),

  // Manual flags (R2.3)
  adminFlags: (system: string, removed: boolean) =>
    get<FlagRow[]>('/admin/flags', { system, removed: removed ? 1 : undefined }),
  previewFlag: (draft: Pick<FlagDraft, 'system' | 'component_ids' | 'start' | 'end'>, exclude?: number) =>
    get<FlagPreview>('/admin/flags/preview', {
      system: draft.system,
      components: draft.component_ids.join(','),
      from: draft.start,
      to: draft.end,
      exclude,
    }),
  createFlag: (draft: FlagDraft) => send<FlagChange>('POST', '/admin/flags', draft),
  updateFlag: (id: number, draft: FlagDraft) => send<FlagChange>('PATCH', `/admin/flags/${id}`, draft),
  removeFlag: (id: number) => send<FlagChange>('DELETE', `/admin/flags/${id}`),

  // Rules and detections (R2.4)
  rules: (system: string) => get<Rule[]>('/admin/rules', { system }),
  ruleVersions: (id: number) => get<RuleVersion[]>(`/admin/rules/${id}/versions`),
  fieldHistory: (system: string, componentType: string, field: string) =>
    get<FieldHistory>('/admin/rules/history', { system, component_type: componentType, field }),
  dryRun: (draft: RuleDraft, ruleId?: number) =>
    get<RuleDryRun>('/admin/rules/dry-run', {
      system: draft.system,
      component_type: draft.component_type,
      field: draft.field,
      site: draft.site ?? undefined,
      type: draft.type,
      params: JSON.stringify(draft.params),
      rule_id: ruleId,
    }),
  createRule: (draft: RuleDraft) => send<RuleChange>('POST', '/admin/rules', draft),
  updateRule: (id: number, draft: RuleDraft) => send<RuleChange>('PUT', `/admin/rules/${id}`, draft),
  deleteRule: (id: number) => send<{ deleted: number }>('DELETE', `/admin/rules/${id}`),

  // Records and calibration (R2.5)
  station: (system: string) => get<StationMeta>('/admin/station', { system }),
  saveStation: (system: string, meta: Omit<StationMeta, 'name'>) =>
    send<StationMeta>('PUT', `/admin/station?system=${encodeURIComponent(system)}`, meta),
  saveSiteMeta: (system: string, slug: string, meta: SiteMeta) =>
    send<SiteMeta>(
      'PUT',
      `/admin/sites/${encodeURIComponent(slug)}?system=${encodeURIComponent(system)}`,
      meta,
    ),
  saveComponentMeta: (id: number, meta: ComponentMeta) =>
    send<ComponentMeta>('PUT', `/admin/components/${id}/meta`, meta),
  calibrations: (componentId: number) => get<Calibration[]>(`/admin/components/${componentId}/calibrations`),
  addCalibration: (draft: CalibrationDraft) => send<Calibration>('POST', '/admin/calibrations', draft),
  updateCalibration: (id: number, draft: CalibrationDraft) =>
    send<Calibration>('PATCH', `/admin/calibrations/${id}`, draft),
  removeCalibration: (id: number) => send<{ removed: number }>('DELETE', `/admin/calibrations/${id}`),
  reviewQueue: (system: string, filter: DetectionFilter, offset = 0) =>
    get<DetectionPage>('/admin/detections', { system, ...filter, offset, limit: 50 }),
  decide: (decision: Decision) => send<DecisionResult>('POST', '/admin/detections/decide', decision),
}
