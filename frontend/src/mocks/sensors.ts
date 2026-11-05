// Sample-data versions of the backend's sensor summaries (backend/simola/kpi/sensors.py), for dev:sample and CI.
import type {
  CloudBand,
  Cover,
  GustEvent,
  LightningRow,
  LightningSummary,
  Segment,
  SkySummary,
  WeatherRow,
  WeatherSummary,
} from '@/api/types'

const M = 60_000
const iso = (ms: number) => new Date(ms).toISOString()

export function dots(ts: number[], vs: (number | null)[], windowMin: number, zeroIsNone: boolean) {
  const pts = ts
    .map((t, i) => [t, vs[i] ?? null] as const)
    .filter(([, v]) => v !== null && !(zeroIsNone && v === 0))
  if (windowMin <= 1440 || pts.length <= 2000)
    return { t: pts.map((p) => p[0]), v: pts.map((p) => p[1] as number), downsampled: false }
  const first = pts[0]![0]
  const span = pts[pts.length - 1]![0] - first + 1
  const buckets = new Map<number, [readonly [number, number | null], readonly [number, number | null]]>()
  for (const p of pts) {
    const b = Math.floor(((p[0] - first) * 1000) / span)
    const lh = buckets.get(b)
    if (!lh) buckets.set(b, [p, p])
    else buckets.set(b, [p[1]! < lh[0][1]! ? p : lh[0], p[1]! > lh[1][1]! ? p : lh[1]])
  }
  const kept = [...buckets.values()].flatMap(([lo, hi]) =>
    lo === hi ? [lo] : [lo, hi].sort((a, b) => a[0] - b[0]),
  )
  return { t: kept.map((p) => p[0]), v: kept.map((p) => p[1] as number), downsampled: true }
}

export function gusts(ts: number[], gs: (number | null)[], gd: (number | null)[]) {
  const events: GustEvent[] = []
  let run: [number, number, number | null][] = []
  const close = () => {
    if (!run.length) return
    const top = run.reduce((a, b) => (b[1] > a[1] ? b : a))
    events.push({ start: iso(run[0]![0]), minutes: run.length, max_kt: top[1], direction_deg: top[2] })
    run = []
  }
  ts.forEach((t, i) => {
    const g = gs[i]
    if (g === null || g === undefined || g <= 0 || (run.length && t - run[run.length - 1]![0] !== M)) close()
    if (g !== null && g !== undefined && g > 0) run.push([t, g, gd[i] ?? null])
  })
  close()
  const strongest = events.reduce<GustEvent | null>((a, b) => (!a || b.max_kt > a.max_kt ? b : a), null)
  return {
    event_count: events.length,
    minutes: events.reduce((n, e) => n + e.minutes, 0),
    strongest,
    events,
    events_truncated: false,
  }
}

function segments<R extends string>(
  ts: number[],
  labels: Partial<Record<R, [number, string]>>[],
  rows: readonly R[],
  windowMin: number,
): Record<R, Segment[]> {
  const join = Math.max(1, Math.floor(windowMin / 600)) * M
  const out = Object.fromEntries(rows.map((r) => [r, [] as Segment[]])) as Record<R, Segment[]>
  ts.forEach((t, i) => {
    for (const r of rows) {
      const lab = labels[i]![r]
      if (!lab) continue
      const segs = out[r]
      const last = segs[segs.length - 1]
      if (last && t - last[1] < join) {
        last[1] = t + M
        last[2] = Math.max(last[2], lab[0])
      } else segs.push([t, t + M, lab[0], lab[1]])
    }
  })
  return out
}

const COVERS: Cover[] = ['FEW', 'SCT', 'BKN', 'OVC']
const band = (h: number): CloudBand => (h < 6500 ? 'low' : h < 20000 ? 'middle' : 'high')
function parseSky(text: string) {
  const layers: [Cover, number, string | null][] = []
  let vv: number | null = null
  let obscured = false
  let clear = false
  for (const tok of text.split(/\s+/)) {
    const m = /^(FEW|SCT|BKN|OVC)(\d{3})(CB|TCU)?$/.exec(tok)
    const v = /^VV(\d{3})$/.exec(tok)
    if (['NCD', 'NSC', 'SKC', 'CLR', 'CAVOK'].includes(tok)) clear = true
    else if (m) layers.push([m[1] as Cover, Number(m[2]) * 100, m[3] ?? null])
    else if (v) {
      obscured = true
      vv = Number(v[1]) * 100
    }
  }
  return { layers, vv, obscured, clear: clear && !layers.length && !obscured }
}

export function sky(ts: number[], vs: (string | null)[], windowMin: number): SkySummary {
  const bucketMin = Math.max(1, Math.ceil(windowMin / 240))
  const bandMinutes = Object.fromEntries(
    (['low', 'middle', 'high'] as CloudBand[]).map((b) => [b, { FEW: 0, SCT: 0, BKN: 0, OVC: 0 }]),
  ) as SkySummary['band_minutes']
  let clear = 0
  let obscured = 0
  let reported = 0
  let ceiling: SkySummary['lowest_ceiling'] = null
  const buckets = new Map<number, Map<string, number>>()
  const first = ts[0] ?? 0
  ts.forEach((t, i) => {
    const v = vs[i]
    if (v === null || v === undefined) return
    reported++
    const s = parseSky(v)
    clear += Number(s.clear)
    obscured += Number(s.obscured)
    const top = new Map<CloudBand, number>()
    for (const [c, h] of s.layers) {
      top.set(band(h), Math.max(top.get(band(h)) ?? -1, COVERS.indexOf(c)))
      if ((c === 'BKN' || c === 'OVC') && (!ceiling || h < ceiling.height_ft))
        ceiling = { height_ft: h, cover: c, time: iso(t) }
    }
    for (const [b, ci] of top) bandMinutes[b][COVERS[ci]!]++
    if (s.vv !== null && (!ceiling || s.vv < ceiling.height_ft))
      ceiling = { height_ft: s.vv, cover: 'VV', time: iso(t) }
    const k = Math.floor((t - first) / (bucketMin * M))
    const counts = buckets.get(k) ?? new Map<string, number>()
    counts.set(v, (counts.get(v) ?? 0) + 1)
    buckets.set(k, counts)
  })
  const timeline = [...buckets.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([k, counts]) => {
      const text = [...counts.entries()].sort((a, b) => b[1] - a[1])[0]![0]
      const s = parseSky(text)
      return {
        t: first + k * bucketMin * M,
        layers: s.layers,
        vv: s.vv,
        obscured: s.obscured,
        clear: s.clear,
      }
    })
  return {
    bucket_minutes: bucketMin,
    bands: { low_top_ft: 6500, middle_top_ft: 20000 },
    band_minutes: bandMinutes,
    clear_minutes: clear,
    obscured_minutes: obscured,
    reported_minutes: reported,
    lowest_ceiling: ceiling,
    timeline,
  }
}

const WX_ROWS: WeatherRow[] = ['thunderstorm', 'rain', 'drizzle', 'mist_fog', 'haze', 'other']
const PHEN: Record<string, WeatherRow> = {
  RA: 'rain',
  DZ: 'drizzle',
  BR: 'mist_fog',
  FG: 'mist_fog',
  HZ: 'haze',
  FU: 'haze',
}
function parseWeather(code: string): Partial<Record<WeatherRow, number>> {
  const rows: Partial<Record<WeatherRow, number>> = {}
  const put = (r: WeatherRow, l: number) => (rows[r] = Math.max(rows[r] ?? 0, l))
  for (const tok of code.split(/\s+/).filter(Boolean)) {
    const m = /^([+-]?)(VC)?((?:SH|TS)*)((?:[A-Z]{2})*)$/.exec(tok)
    if (!m) {
      put('other', 2)
      continue
    }
    const level = m[2] ? 1 : m[1] === '-' ? 1 : m[1] === '+' ? 3 : 2
    if (m[3]?.includes('TS')) put('thunderstorm', level)
    for (let i = 0; i < (m[4] ?? '').length; i += 2) put(PHEN[m[4]!.slice(i, i + 2)] ?? 'other', level)
  }
  return rows
}

export function weather(ts: number[], vs: (string | null)[], windowMin: number): WeatherSummary {
  const labels = vs.map((v) => {
    const rows = v ? parseWeather(v) : {}
    return Object.fromEntries(Object.entries(rows).map(([r, l]) => [r, [l, v!] as [number, string]]))
  }) as Partial<Record<WeatherRow, [number, string]>>[]
  const segs = segments(ts, labels, WX_ROWS, windowMin)
  return {
    rows: WX_ROWS.map((r) => ({ key: r, minutes: labels.filter((l) => l[r]).length, segments: segs[r] })),
    weather_minutes: vs.filter((v) => v).length,
    reported_minutes: vs.filter((v) => v !== null).length,
  }
}

const LTG_ROWS: LightningRow[] = ['airport', 'vicinity', 'distant']
export function lightning(ts: number[], vs: (string | null)[], windowMin: number): LightningSummary {
  const directions: Record<string, number> = { N: 0, NE: 0, E: 0, SE: 0, S: 0, SW: 0, W: 0, NW: 0, ALQDS: 0 }
  let episodes = 0
  let lastSeen: number | null = null
  let firstT: string | null = null
  let lastT: string | null = null
  const labels = vs.map((v, i) => {
    if (!v) return {}
    const up = v.toUpperCase()
    const level: LightningRow = up.includes('AT AIRPORT')
      ? 'airport'
      : up.includes('IN VICINITY')
        ? 'vicinity'
        : 'distant'
    for (const d of (up.split('DSNT')[1] ?? '').split(/\s+|AND/)) if (d in directions) directions[d]!++
    const t = ts[i]!
    if (lastSeen === null || t - lastSeen > 15 * M) episodes++
    lastSeen = t
    firstT ??= iso(t)
    lastT = iso(t)
    return { [level]: [1, v] as [number, string] }
  }) as Partial<Record<LightningRow, [number, string]>>[]
  const segs = segments(ts, labels, LTG_ROWS, windowMin)
  return {
    rows: LTG_ROWS.map((r) => ({ key: r, minutes: labels.filter((l) => l[r]).length, segments: segs[r] })),
    directions,
    episodes,
    first: firstT,
    last: lastT,
    reported_minutes: vs.filter((v) => v !== null).length,
  }
}
