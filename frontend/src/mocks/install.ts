// Fetch interceptor for sample-data mode (VITE_MOCK=1). Only bundled when that flag is set at build time.
import type { MatrixBucket } from '@/api/types'
import { accountsRoute, currentUser, signedIn } from './accounts'
import { adminRoute } from './admin'
import * as data from './data'

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
}

function route(url: URL, method: string, body: unknown): Response {
  const now = Date.now()
  const p = url.pathname.replace(/^\/api\/v1/, '')
  const accounts = accountsRoute(p, url, method, body)
  if (accounts) return accounts
  if (p.startsWith('/admin/')) {
    const me = currentUser()
    if (!me) return json({ code: 'not_authenticated', title: 'Sign in first', status: 401 }, 401)
    if (me.role !== 'admin') return json({ code: 'forbidden', title: 'Admins only', status: 403 }, 403)
    const admin = adminRoute(p, url, method, body, me.username)
    if (admin) return admin
  }
  const q = url.searchParams
  const from = Date.parse(q.get('from') ?? '')
  const to = Date.parse(q.get('to') ?? '')
  if (p === '/settings/display')
    return json({ color_thresholds: { good: 99, warning: 95 }, grace_minutes: 3 })
  if (p === '/systems') return json(data.systems(now))
  if (p === `/systems/${data.SYSTEM.code}`) return json(data.SYSTEM)
  if (p.endsWith('/kpis')) return json(data.kpis(from, to, now))
  if (p.endsWith('/matrix'))
    return json(data.matrix(from, to, (q.get('bucket') ?? 'day') as MatrixBucket, now))
  if (p.endsWith('/minutes')) return json(data.minutes(q.get('day') ?? '', q.get('scope') ?? 'sla', now))
  if (p.endsWith('/outages')) {
    if (to - from > data.MAX_OUTAGE_SPAN)
      return json({ code: 'period_too_long', title: 'period longer than 93 days', status: 422 }, 422)
    return json(data.outages(from, to, q.get('scope') ?? 'sla', now, Number(q.get('limit') ?? 100)))
  }
  if (p.endsWith('/status')) return json(data.status(now))
  if (p.endsWith('/problems'))
    return json({
      generated_at: new Date(now).toISOString(),
      problems: [
        {
          code: 'component_field_missing',
          severity: 'minor',
          link: '/systems/WIDN-CAT3/sites/04',
          params: { site: 'RWY04', component: 'PWX', since: new Date(now - 3_600_000).toISOString() },
        },
      ],
    })
  const m = p.match(/^\/systems\/[^/]+\/sites\/([^/]+)\/components\/([^/]+)\/series$/)
  if (m) return json(data.series(decodeURIComponent(m[1]!), decodeURIComponent(m[2]!), from, to, now))
  if (p === '/internal/health' && !signedIn())
    return json({ code: 'not_authenticated', title: 'Sign in first', status: 401 }, 401)
  if (p === '/internal/health')
    return json({
      version: 'sample-data',
      environment: 'development',
      probe_method: 'tcp:445',
      workers: [
        {
          worker: 'worker-1',
          version: 'sample',
          leader: true,
          last_beat: new Date(now - 12_000).toISOString(),
        },
      ],
      database: { size_bytes: 138 * 1_048_576 },
      backups: [
        {
          started_at: new Date(now - 9 * 3_600_000).toISOString(),
          ok: true,
          size_bytes: 61 * 1_048_576,
          message: 'local copy only',
        },
      ],
      jobs: [
        {
          id: 2,
          type: 'reprocess',
          status: 'done',
          progress: 1,
          message: 'reprocessed 316 day(s)',
          created_at: new Date(now - 86_400_000).toISOString(),
        },
      ],
      systems: [
        {
          code: data.SYSTEM.code,
          ingestion: data.status(now).ingestion.map((i) => ({
            ...i,
            parse_warnings: 0,
            oldest_file_date: '2025-12-24',
            path: '/mnt/cdp',
            last_error: null,
          })),
          cdps: data.status(now).cdps.map((c) => ({ ...c, address: '192.0.2.10' })),
        },
      ],
    })
  return json({ code: 'not_found', title: 'Not found', status: 404 }, 404)
}

export function installMocks(): void {
  const real = window.fetch.bind(window)
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(
      typeof input === 'string' ? input : input instanceof URL ? input.href : input.url,
      window.location.origin,
    )
    if (!url.pathname.startsWith('/api/v1/')) return real(input, init)
    await new Promise((r) => setTimeout(r, 80))
    const method = (init?.method ?? 'GET').toUpperCase()
    let body: unknown = undefined
    try {
      body = typeof init?.body === 'string' ? JSON.parse(init.body) : undefined
    } catch {
      /* not JSON */
    }
    return route(url, method, body)
  }
  console.info('[SIMOLA] sample-data mode: all API responses are generated in the browser')
}
