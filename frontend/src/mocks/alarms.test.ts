import { describe, expect, it } from 'vitest'
import { active, history } from './alarms'

// The browser tests count the sample's active alarms: the count must not depend on the day or the hour.
const HOUR = 3_600_000
const start = Date.parse('2026-11-01T00:00:00Z')
const moments = Array.from({ length: 90 }, (_, i) => start + i * 9 * HOUR + (i % 7) * 13 * 60_000)

describe('sample alarms', () => {
  it('always have the same active alarms, and older ones with no clear logged', () => {
    for (const now of moments) {
      const list = active(now)
      expect(list.active.map((a) => a.name).sort(), new Date(now).toISOString()).toEqual([
        'DCP6498CpsbDegradedWarning',
        'DCPA_VISA_DataIncompleteError',
        'DCPB_LightningCommWarning',
      ])
      expect(list.not_cleared).toHaveLength(3)
    }
  })

  it("always have yesterday's DCP outage at Runway 22 in the last 30 days", () => {
    for (const now of moments) {
      const q = new URLSearchParams({
        from: new Date(now - 30 * 24 * HOUR).toISOString(),
        to: new Date(now).toISOString(),
        scope: 'component:22:DCP',
      })
      const page = history(now, q)
      expect(page.total).toBeGreaterThan(0)
      expect(page.events.every((e) => e.name === 'DCPC_Missing')).toBe(true)
    }
  })
})
