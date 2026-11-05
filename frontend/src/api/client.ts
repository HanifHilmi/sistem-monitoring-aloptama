import type {
  CalendarResponse,
  MatrixBucket,
  MatrixResponse,
  MinutesResponse,
  OutagesResponse,
  DisplaySettings,
  HistoryResponse,
  KpiResponse,
  ProblemsResponse,
  SeriesResponse,
  StatusResponse,
  SystemInfo,
  SystemSummary,
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

async function get<T>(path: string, params: Record<string, string | number> = {}): Promise<T> {
  const qs = new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)])).toString()
  const res = await fetch(`${BASE}${path}${qs ? `?${qs}` : ''}`, { headers: { Accept: 'application/json' } })
  if (!res.ok) {
    let code = 'http_error'
    let title = res.statusText
    try {
      const body = (await res.json()) as { code?: string; title?: string }
      code = body.code ?? code
      title = body.title ?? title
    } catch {
      /* not JSON */
    }
    throw new ApiProblem(res.status, code, title)
  }
  return (await res.json()) as T
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
  internalHealth: () => get<Record<string, unknown>>('/internal/health'),
}
