// Problems (FR-DSH-010) as text, shared by the Problems panel and the dashboard.
import type { Problem, Severity } from '@/api/types'

type T = (key: string, values?: Record<string, unknown>, plural?: number) => string

/** "CDP2 isn't producing data", from the problem's code and parameters. */
export function problemMessage(p: Problem, t: T): string {
  const params: Record<string, string | number> = {}
  for (const [k, v] of Object.entries(p.params))
    if (v !== null && v !== undefined) params[k === 'lag_min' ? 'lag' : k] = v
  return typeof params.n === 'number'
    ? t(`problems.code.${p.code}`, params, params.n)
    : t(`problems.code.${p.code}`, params)
}

/** Severity label colours, the same in the panel and on the dashboard. */
export const SEVERITY_TONE: Record<Severity, string> = {
  critical: 'bg-bad text-white',
  major: 'bg-bad/15 text-bad',
  minor: 'bg-warn/15 text-warn',
  info: 'bg-sunken text-ink-2',
}
