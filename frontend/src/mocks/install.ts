// Fetch interceptor for sample-data mode (VITE_MOCK=1). Only bundled when that flag is set at build time.
import type { MatrixBucket } from '@/api/types'
import { accountsRoute, currentUser, signedIn } from './accounts'
import { adminRoute, assets, calibrationProblems, recalculating, trace } from './admin'
import * as alarms from './alarms'
import * as quality from './quality'
import * as reports from './reports'
import * as data from './data'
import { exportFile, reportFile } from './exports'
import { dqRoute, isAdmin, pendingSuspects, pendingSuspectsIn, publicDetections } from './dq'
import { flagsRoute, publicFlags } from './flags'

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
    const flags = flagsRoute(p, url, method, body, me.username)
    if (flags) return flags
    const dq = dqRoute(p, url, method, body, me.username)
    if (dq) return dq
    const admin = adminRoute(p, url, method, body, me.username)
    if (admin) return admin
    if (p === '/admin/alarm-names' && method === 'GET') return json(alarms.names(Date.now()))
    const an = p.match(/^\/admin\/alarm-names\/([^/]+)$/)
    if (an && method === 'PUT') {
      const saved = alarms.setPlace(decodeURIComponent(an[1]!), body as never, me.username, Date.now())
      return typeof saved === 'string'
        ? json(
            { code: saved, title: saved, status: saved === 'alarm_not_found' ? 404 : 422 },
            saved === 'alarm_not_found' ? 404 : 422,
          )
        : json(saved)
    }
  }
  const q = url.searchParams
  const from = Date.parse(q.get('from') ?? '')
  const to = Date.parse(q.get('to') ?? '')
  // CSV exports are for signed-in users (FR-EXP-003).
  const ex = p.match(/^\/systems\/[^/]+\/exports\/([a-z]+)\.csv$/)
  if (ex) {
    if (!signedIn()) return json({ code: 'not_authenticated', title: 'Sign in first', status: 401 }, 401)
    const file = exportFile(ex[1]!, q, now)
    if (typeof file === 'string') {
      const status = file.endsWith('not_found') ? 404 : file === 'too_many_exports' ? 429 : 422
      return json({ code: file, title: file, status }, status)
    }
    return new Response(file.body, {
      headers: {
        'content-type': 'text/csv; charset=utf-8',
        'content-disposition': `attachment; filename="${file.name}"`,
      },
    })
  }
  // The monthly PDF (R3.5): signed-in users; the server draws it, sample mode answers with a placeholder.
  if (/^\/systems\/[^/]+\/exports\/monthly-report$/.test(p) && method === 'POST') {
    if (!signedIn()) return json({ code: 'not_authenticated', title: 'Sign in first', status: 401 }, 401)
    const file = reportFile(body, now)
    if (typeof file === 'string') {
      const status = file === 'too_many_exports' ? 429 : 422
      return json({ code: file, title: file, status }, status)
    }
    return new Response(file.body, {
      headers: {
        'content-type': 'application/pdf',
        'content-disposition': `attachment; filename="${file.name}"`,
      },
    })
  }
  if (p === '/settings/display')
    return json({ color_thresholds: { good: 99, warning: 95 }, grace_minutes: 3 })
  if (p === '/systems') return json(data.systems(now))
  if (p === `/systems/${data.SYSTEM.code}`) return json(data.SYSTEM)
  if (p.endsWith('/kpis')) return json(data.kpis(from, to, now))
  if (p.endsWith('/matrix')) {
    const m = data.matrix(from, to, (q.get('bucket') ?? 'day') as MatrixBucket, now)
    const busy = recalculating(now).filter(
      (r) => Date.parse(r.from) < to && Date.parse(r.to) + 86_400_000 > from,
    )
    return json(busy.length ? { ...m, period: { ...m.period, recalculating: busy } } : m)
  }
  if (p.endsWith('/flags')) return publicFlags(url)
  if (p.endsWith('/detections')) return publicDetections(url)
  if (p.endsWith('/assets')) return json(assets(signedIn(), now))
  // Data quality is public; the pending suspect count only for signed-in users (D7). Definitions are public.
  if (p === '/definitions') return json(quality.DEFINITIONS)
  if (p.endsWith('/data-quality')) {
    const s = quality.summary(from, to, now, signedIn() ? pendingSuspectsIn(from, to) : null)
    return typeof s === 'string' ? json({ code: s, title: s, status: 422 }, 422) : json(s)
  }
  // METAR, MET REPORT and TAF are public (FR-RPT).
  if (p.endsWith('/reports/latest')) return json(reports.latest(now))
  if (p.endsWith('/reports/search')) return json(reports.search(now, q))
  if (p.endsWith('/reports'))
    return json(reports.day(now, q.get('day') ?? '', (q.get('type') ?? 'metar') as never))
  // AWOS alarms are for signed-in users only; the public does not even see the count (OPEN-13).
  if (/\/alarms(\/active)?$/.test(p)) {
    if (!signedIn()) return json({ code: 'not_authenticated', title: 'Sign in first', status: 401 }, 401)
    if (p.endsWith('/active')) return json(alarms.active(now, q.get('scope')))
    return json(alarms.history(now, q))
  }
  if (p.endsWith('/trace')) {
    if (!signedIn()) return json({ code: 'not_authenticated', title: 'Sign in first', status: 401 }, 401)
    return json(trace(q.get('scope') ?? '', from, to, now))
  }
  if (p.endsWith('/minutes'))
    return json(data.minutes(q.get('day') ?? '', q.get('scope') ?? 'sla', now, signedIn()))
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
        ...alarms.alarmProblems(now, signedIn()),
        ...calibrationProblems(now),
        // Pending suspect detections are for signed-in users only (PRD FR-DSH-010, OPEN-13).
        ...(signedIn() && pendingSuspects()
          ? [
              {
                code: 'suspects_pending',
                severity: 'info',
                link: isAdmin() ? '/admin/review' : '/systems/WIDN-CAT3',
                params: { n: pendingSuspects() },
              },
            ]
          : []),
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
    // a report takes a moment on the server too, so the page's progress shows
    const slow = url.pathname.endsWith('/monthly-report')
    await new Promise((r) => setTimeout(r, slow ? 1500 : 80))
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
