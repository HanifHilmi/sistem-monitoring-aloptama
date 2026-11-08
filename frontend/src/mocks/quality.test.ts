import { describe, expect, it } from 'vitest'
import { outages, SYSTEM } from './data'
import { summary } from './quality'

// R3.3 acceptance, on the sample: the summary's minutes equal the flagged and detection minutes of each sensor's
// outage list for the same period.
describe('sample data-quality summary', () => {
  it("equals each sensor's outage list", () => {
    const now = Date.now()
    const from = Date.parse('2026-10-01T00:00:00Z')
    const to = Date.parse('2026-11-01T00:00:00Z')
    const s = summary(from, to, now, null)
    if (typeof s === 'string') throw new Error(s)
    for (const site of SYSTEM.sites)
      for (const c of site.components.filter((x) => !x.is_dcp)) {
        const o = outages(from, to, `component:${site.slug}:${c.type}`, now, 10_000)
        const row = s.components.find((x) => x.site === site.slug && x.component === c.type)
        expect(row?.flagged_minutes ?? 0).toBe(o.by_cause.flagged)
        expect(row?.detection_minutes ?? 0).toBe(o.by_cause.detection)
      }
    expect(s.flagged_minutes).toBe(420)
    expect(s.detection_minutes).toBe(481)
  })
})
