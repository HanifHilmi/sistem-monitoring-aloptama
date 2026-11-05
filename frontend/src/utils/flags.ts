// Shared wording for manual flags (R2.3): time ranges, durations and the days a change recalculates.
import type { Locale } from '@/i18n'

type T = (key: string, values?: Record<string, unknown>) => string

const dayFmt = (lc: Locale, year = false) =>
  new Intl.DateTimeFormat(lc === 'id' ? 'id-ID' : 'en-GB', {
    day: 'numeric',
    month: 'short',
    ...(year ? { year: 'numeric' } : {}),
    timeZone: 'UTC',
  })
const hhmm = (iso: string) => iso.slice(11, 16)

/** "21 Oct 08:00–10:30", or with both days when the range crosses midnight. The end is exclusive. */
export function formatRange(start: string, end: string, lc: Locale, year = false): string {
  const fmt = dayFmt(lc, year)
  const a = new Date(start)
  const last = new Date(Date.parse(end) - 60_000)
  const from = `${fmt.format(a)} ${hhmm(start)}`
  if (a.toISOString().slice(0, 10) === last.toISOString().slice(0, 10))
    return `${from}–${hhmm(end) === '00:00' ? '24:00' : hhmm(end)}`
  return `${from} – ${fmt.format(new Date(end))} ${hhmm(end)}`
}

export function formatDuration(minutes: number, t: T): string {
  const d = Math.floor(minutes / 1440)
  const h = Math.floor((minutes % 1440) / 60)
  const m = minutes % 60
  if (d) return t('outages.durDays', { d, h })
  if (h && !m) return t('outages.durHoursOnly', { h })
  if (h) return t('outages.durHours', { h, m })
  return t('outages.durMinutes', { m })
}

/** "21 Oct" or "21–23 Oct 2026" for the UTC days a change recalculates. */
export function formatDays(days: { from: string; to: string }, lc: Locale): string {
  const fmt = dayFmt(lc, true)
  const a = new Date(`${days.from}T00:00:00Z`)
  const b = new Date(`${days.to}T00:00:00Z`)
  return days.from === days.to ? fmt.format(a) : fmt.formatRange(a, b)
}

/** <input type="datetime-local"> holds UTC here (labels say so): nothing is converted. */
export const toInput = (iso: string | null | undefined) => (iso ? iso.slice(0, 16) : '')
export const fromInput = (v: string) => (v ? `${v}:00Z` : '')
