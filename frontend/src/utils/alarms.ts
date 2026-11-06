import type { AlarmEvent, AlarmPlace, SystemInfo } from '@/api/types'
import type { Locale } from '@/i18n'

type T = (key: string, params?: Record<string, unknown>) => string

/** "Runway 22 · Visibility" / "Runway 04" / "Station" / "Not assigned" (FR-ING-008 mapping). */
export function placeLabel(p: AlarmPlace, info: SystemInfo | null, lc: Locale, t: T): string {
  if (p.kind === 'station') return t('alarms.place.station')
  if (p.kind === 'unmapped') return t('alarms.place.unmapped')
  const site = info?.sites.find((s) => s.slug === p.site)
  const siteName = site?.name[lc] ?? p.site ?? '?'
  if (p.kind === 'site') return siteName
  const comp = site?.components.find((c) => c.type === p.component)
  return `${siteName} · ${comp?.name[lc] ?? p.component}`
}

/** "2 d 5 h", "6 h 12 min", "42 min" since a moment. */
export function since(fromIso: string, now: number, t: T): string {
  const min = Math.max(0, Math.floor((now - Date.parse(fromIso)) / 60_000))
  const d = Math.floor(min / 1440)
  const h = Math.floor((min % 1440) / 60)
  const m = min % 60
  if (d) return t('alarms.for.dh', { d, h })
  if (h) return t('alarms.for.hm', { h, m })
  return t('alarms.for.m', { m })
}

/** The AWOS's own state word, translated when known, else shown as written. */
export function stateLabel(state: string, t: T, te: (k: string) => boolean): string {
  return te(`alarms.state.${state}`) ? t(`alarms.state.${state}`) : state
}

/** What a change did: raised the alarm, acknowledged one already raised, or cleared it. */
export function changeLabel(e: Pick<AlarmEvent, 'active' | 'raised'>, t: T): string {
  if (!e.active) return `▽ ${t('alarms.change.cleared')}`
  return e.raised ? `▲ ${t('alarms.change.raised')}` : `◆ ${t('alarms.change.acknowledged')}`
}
