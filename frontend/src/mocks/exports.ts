// CSV exports in sample-data mode (R3.4): the same files the server writes (backend/simola/exports.py), built from
// the sample figures, alarms, flags and detections, so the Download button can be tried without a backend.
import type { MinutesResponse } from '@/api/types'
import {
  ALARM_COLUMNS,
  DAILY_COLUMNS,
  MAX_DAYS,
  QUALITY_COLUMNS,
  exportFileName,
  minuteHeader,
  minuteLayout,
  type ExportKind,
} from '@/utils/exports'
import * as alarms from './alarms'
import { SYSTEM, kpis, minuteValue, minutes } from './data'
import { dqState } from './dqStore'
import { allFlags } from './flagStore'
import { DEFINITIONS } from './quality'

const DAY = 86_400_000
const MIN = 60_000
const BOM = '\ufeff'
const STATUS: Record<string, string> = {
  v: 'valid',
  s: 'valid',
  f: 'field_missing',
  n: 'no_data',
  g: 'flagged',
  d: 'detection',
  u: 'not_counted',
}

/** Text a spreadsheet will not run as a formula; quoted when it holds a comma, a quote or a line break. */
function text(v: string | null | undefined): string {
  if (v === null || v === undefined) return ''
  const s = /^[=+\-@\t\r]/.test(v) ? `'${v}` : v
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}
function num(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return ''
  return String(v)
}
const iso = (t: number | string) => new Date(t).toISOString().replace('.000Z', 'Z')
const pct = (v: number, e: number) => (e ? ((Math.round((v / e) * 10000) / 100).toFixed(2) as string) : '')
const siteCode = (slug: string) => SYSTEM.sites.find((s) => s.slug === slug)?.code ?? slug
const line = (cells: string[]) => cells.join(',') + '\r\n'

export interface SampleFile {
  name: string
  body: string
}

// Ten files a minute, as the server allows a person (API-10); kept for this page load only.
const recent: number[] = []
const PER_MINUTE = 10

/** The file for `/systems/{code}/exports/{kind}.csv?…`, or a problem code. */
export function exportFile(kind: string, q: URLSearchParams, now: number): SampleFile | string {
  if (!(kind in MAX_DAYS)) return 'not_found'
  const k = kind as ExportKind
  const from = Date.parse(q.get('from') ?? '')
  const to = Date.parse(q.get('to') ?? '')
  if (!(from < to)) return 'invalid_period'
  if (to - from > MAX_DAYS[k] * DAY) return 'period_too_long'
  if (k === 'minutes' && !SYSTEM.sites.some((s) => s.slug === q.get('site'))) return 'site_not_found'
  while (recent.length && recent[0]! <= now - MIN) recent.shift()
  if (recent.length >= PER_MINUTE) return 'too_many_exports'
  recent.push(now)
  const stamp = [DEFINITIONS.version, iso(Math.floor(now / 1000) * 1000)]
  const out: string[] = []
  let site: string | undefined
  if (k === 'daily') {
    out.push(line(DAILY_COLUMNS.map((c) => c.name)))
    for (let d = Math.floor(from / DAY) * DAY; d < Math.min(to, now); d += DAY) {
      const r = kpis(Math.max(d, from), Math.min(d + DAY, to), now)
      if (!r.sla.expected) continue
      const day = new Date(d).toISOString().slice(0, 10)
      const row = (
        scope: string,
        cdp: string,
        s: string,
        c: string,
        v: number,
        e: number,
        reach = ['', ''],
      ) => line([day, scope, cdp, s, c, String(e), String(v), String(e - v), pct(v, e), ...reach, ...stamp])
      out.push(row('system', '', '', '', r.sla.valid, r.sla.expected))
      for (const c of r.cdps)
        out.push(
          row('cdp', c.code, '', '', c.uptime.valid, c.uptime.expected, [
            String(c.reachability.reachable),
            String(c.reachability.sampled),
          ]),
        )
      for (const s of r.sites) {
        out.push(row('site', '', siteCode(s.slug), '', s.availability.valid, s.availability.expected))
        for (const c of s.components)
          out.push(
            row('component', '', siteCode(s.slug), c.type, c.availability.valid, c.availability.expected),
          )
      }
    }
  } else if (k === 'minutes') {
    site = q.get('site') ?? ''
    const info = SYSTEM.sites.find((s) => s.slug === site)
    if (!info) return 'site_not_found'
    out.push(line(minuteHeader(minuteLayout(SYSTEM, site))))
    const a = Math.max(from, Date.parse(SYSTEM.coverage_start))
    const b = Math.min(to, Math.floor(now / MIN) * MIN)
    const days = new Map<string, Record<string, MinutesResponse>>()
    for (let t = Math.ceil(a / MIN) * MIN; t < b; t += MIN) {
      const day = new Date(t).toISOString().slice(0, 10)
      let maps = days.get(day)
      if (!maps) {
        maps = Object.fromEntries(
          info.components.map((c) => [c.type, minutes(day, `component:${site}:${c.type}`, now)]),
        )
        days.clear()
        days.set(day, maps)
      }
      const i = Math.floor((t - Date.parse(`${day}T00:00:00Z`)) / MIN)
      const dcp = maps.DCP?.codes[i] ?? 'v'
      const cells = [iso(t), dcp === 'n' ? '' : 'CDP1 CDP2']
      for (const c of info.components) {
        const code = maps[c.type]!.codes[i] ?? 'u'
        cells.push(STATUS[code]!)
        for (const f of c.fields) {
          const missing = code === 'n' || code === 'u' || (code === 'f' && c.mandatory.includes(f))
          const v = missing ? null : minuteValue(site, c.type, f, t)
          cells.push(typeof v === 'string' ? text(v) : num(v))
        }
      }
      out.push(line([...cells, ...stamp]))
    }
  } else if (k === 'alarms') {
    out.push(line(ALARM_COLUMNS.map((c) => c.name)))
    for (const e of alarms.filtered(now, q)) {
      const p = e.place
      out.push(
        line([
          iso(e.time),
          text(e.name),
          e.type,
          !e.active ? 'cleared' : e.raised ? 'raised' : 'acknowledged',
          text(e.state),
          p.kind,
          p.site && (p.kind === 'site' || p.kind === 'component') ? siteCode(p.site) : '',
          p.kind === 'component' ? text(p.component) : '',
          text(e.message),
          e.cdps.join(' '),
          ...stamp,
        ]),
      )
    }
  } else {
    out.push(line(QUALITY_COLUMNS.map((c) => c.name)))
    const records = (q.get('records') ?? 'flags,detections').split(',')
    const all = q.get('all') === '1'
    const rows: [number, string][] = []
    if (records.includes('flags'))
      for (const f of allFlags())
        if (!f.removed_at && Date.parse(f.end) > from && Date.parse(f.start) < to)
          for (const c of f.components)
            rows.push([
              Date.parse(f.start),
              line([
                'flag',
                String(f.id),
                siteCode(c.site),
                c.type,
                '',
                iso(f.start),
                iso(f.end),
                String((Date.parse(f.end) - Date.parse(f.start)) / MIN),
                f.reason,
                'active',
                c.type === 'DCP' ? 'false' : 'true',
                '',
                '',
                text(f.note),
                text(f.created_by),
                iso(f.created_at),
                ...stamp,
              ]),
            ])
    if (records.includes('detections'))
      for (const d of dqState().detections)
        if ((all || d.status === 'confirmed') && Date.parse(d.end) > from && Date.parse(d.start) < to)
          rows.push([
            Date.parse(d.start),
            line([
              'detection',
              String(d.id),
              siteCode(d.site),
              d.component,
              text(d.field),
              iso(d.start),
              iso(d.end),
              String((Date.parse(d.end) - Date.parse(d.start)) / MIN),
              d.type,
              d.status,
              d.status === 'confirmed' && d.mandatory ? 'true' : 'false',
              String(d.rule_id),
              String(d.rule_version),
              text(d.note),
              text(d.decided_by),
              d.decided_at ? iso(d.decided_at) : '',
              ...stamp,
            ]),
          ])
    out.push(...rows.sort((x, y) => x[0] - y[0]).map(([, l]) => l))
  }
  return {
    name: exportFileName(SYSTEM.code, k, new Date(from), new Date(to), site ? siteCode(site) : undefined),
    body: BOM + out.join(''),
  }
}
