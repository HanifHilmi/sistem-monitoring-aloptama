// NFR-PERF-003: first page load. Measured only against a deployed site (real nginx with gzip).
import { expect, test } from './fixtures'

test('first load: LCP ≤ 2.5 s and initial JS ≤ 400 KB gzip', async ({ page }, info) => {
  test.skip(!process.env.SIMOLA_E2E_URL, 'needs a deployed site (SIMOLA_E2E_URL)')
  test.skip(!info.project.name.startsWith('desktop'), 'the target is for desktop')

  await page.goto('/', { waitUntil: 'networkidle' })
  const lcp = await page.evaluate(
    () =>
      new Promise<number>((resolve) => {
        new PerformanceObserver((list) => {
          const entries = list.getEntries()
          resolve(entries[entries.length - 1]?.startTime ?? -1)
        }).observe({ type: 'largest-contentful-paint', buffered: true })
        setTimeout(() => resolve(-1), 5_000)
      }),
  )
  // Every script the first page needed, including its lazily loaded chunks; encodedBodySize is the gzip size.
  const js = await page.evaluate(() =>
    (performance.getEntriesByType('resource') as PerformanceResourceTiming[])
      .filter((r) => new URL(r.name).pathname.endsWith('.js'))
      .reduce((n, r) => n + r.encodedBodySize, 0),
  )
  info.annotations.push({ type: 'LCP', description: `${Math.round(lcp)} ms` })
  info.annotations.push({ type: 'initial JS', description: `${(js / 1024).toFixed(1)} KB gzip` })
  console.log(`LCP ${Math.round(lcp)} ms, initial JS ${(js / 1024).toFixed(1)} KB gzip`)

  expect(lcp).toBeGreaterThan(0)
  expect(lcp).toBeLessThanOrEqual(2_500)
  expect(js).toBeGreaterThan(0)
  expect(js).toBeLessThanOrEqual(400 * 1024)
})
