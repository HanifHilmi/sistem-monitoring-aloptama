import { defineConfig, devices } from '@playwright/test'
import type { Options } from './e2e/fixtures'

/**
 * Browser tests (PRD §15.3): desktop 1440 px and phone 390 px, in Indonesian and English.
 *
 * - Without SIMOLA_E2E_URL they run against the sample-data build (VITE_MOCK=1), as in CI.
 * - With SIMOLA_E2E_URL they run against a deployed site, e.g. staging's web container
 *   (see docs/runbooks/testing.md). Never commit that address: the repository is public.
 */
const target = process.env.SIMOLA_E2E_URL
const port = 4173

const desktop = { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } }
const phone = { ...devices['Pixel 7'], viewport: { width: 390, height: 844 } }

export default defineConfig<Options>({
  testDir: 'e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 2 : 4,
  // In CI, 'github' turns each failure into an annotation that is readable without signing in.
  reporter: process.env.CI ? [['github'], ['list'], ['html', { open: 'never' }]] : 'list',
  timeout: 30_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: target ?? `http://127.0.0.1:${port}`,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'desktop-id', use: { ...desktop, locale: 'id-ID', lang: 'id' } },
    { name: 'desktop-en', use: { ...desktop, locale: 'en-GB', lang: 'en' } },
    { name: 'phone-id', use: { ...phone, locale: 'id-ID', lang: 'id' } },
    { name: 'phone-en', use: { ...phone, locale: 'en-GB', lang: 'en' } },
  ],
  webServer: target
    ? undefined
    : {
        command: `VITE_MOCK=1 npx vite build --outDir dist-e2e --emptyOutDir && npx vite preview --outDir dist-e2e --host 127.0.0.1 --port ${port} --strictPort`,
        url: `http://127.0.0.1:${port}`,
        reuseExistingServer: !process.env.CI,
        timeout: 180_000,
      },
})
