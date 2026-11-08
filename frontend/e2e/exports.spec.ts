// Exports (R3.4, FR-EXP-002/003): Viewers and Admins only. The sample-data tests follow the registry of
// src/mocks/data.ts (three sites, 21 sensors); the download test also runs against a deployed site, where the
// server writes the file.
import { readFile } from 'node:fs/promises'
import { BOARD, expect, expectNoPageScroll, hasAccount, signIn, test } from './fixtures'

const EXPORTS = `${BOARD}/exports`
const OCTOBER = `${EXPORTS}?p=month:2026-10-01`
const sample = !process.env.SIMOLA_E2E_URL

/** The header row of a downloaded file, and how many rows follow it. */
async function csv(path: string): Promise<{ header: string[]; rows: number; bom: boolean }> {
  const body = await readFile(path, 'utf8')
  const lines = body
    .replace(/^\ufeff/, '')
    .split('\r\n')
    .filter(Boolean)
  return { header: lines[0]!.split(','), rows: lines.length - 1, bom: body.startsWith('\ufeff') }
}

test.describe('Exports: the file', () => {
  test.skip(!hasAccount(), 'needs SIMOLA_E2E_USER and SIMOLA_E2E_PASSWORD on a deployed site')

  test('the daily file holds the columns the page lists', async ({ page, t }) => {
    // one download per browser project, so a deployed site's limit of ten files a minute is never reached
    await page.goto(`/login?next=${encodeURIComponent(OCTOBER)}`)
    await signIn(page, t, 'siti')
    const columns = page.getByTestId('export-columns').locator('tbody tr')
    await columns.first().waitFor()
    const shown = (
      await page.getByTestId('export-columns').locator('tbody tr td:first-child').allInnerTexts()
    ).map((s) => s.trim())
    const [download] = await Promise.all([
      page.waitForEvent('download'),
      page.getByTestId('export-download').click(),
    ])
    expect(download.suggestedFilename()).toBe('SIMOLA_WIDN-CAT3_daily_2026-10-01_2026-10-31.csv')
    const file = await csv((await download.path())!)
    expect(file.bom).toBe(true)
    expect(file.header).toEqual(shown)
    if (sample) expect(file.rows).toBe(31 * 27)
    else expect(file.rows % 31).toBe(0) // every day of October, the same scopes each day
  })
})

test.describe('Exports', () => {
  test.skip(!sample, 'sample data only: the row counts follow the sample registry')

  test('a Viewer finds the page in the system menu; the public is sent to sign in', async ({
    page,
    t,
    isMobile,
  }) => {
    await page.goto(EXPORTS)
    await expect(page).toHaveURL(/\/login\?next=/)
    await signIn(page, t, 'siti')
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(t('exports.title'))

    await page.goto(BOARD)
    if (isMobile) await page.locator('[aria-controls="mobile-nav"]').click()
    else await page.getByTestId('system-menu').getByRole('button').click()
    const menu = isMobile ? page.locator('#mobile-nav') : page.getByRole('menu')
    await menu.locator(`a[href="${EXPORTS}"]`).click()
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(t('exports.title'))
  })

  test('daily availability: one row per day and scope, with the way back to the monthly figures', async ({
    page,
    t,
  }) => {
    await page.goto(`/login?next=${encodeURIComponent(OCTOBER)}`)
    await signIn(page, t, 'siti')
    await expect(page.getByTestId('export-kind-daily')).toHaveAttribute('aria-checked', 'true')
    await expect(page.getByTestId('export-filename')).toHaveText(
      'SIMOLA_WIDN-CAT3_daily_2026-10-01_2026-10-31.csv',
    )
    await expect(page.getByTestId('export-size')).toContainText('837') // 31 days × 27 scopes
    await expect(page.getByTestId('export-columns').locator('tbody tr')).toHaveCount(13)
    await expect(page.getByTestId('export-recompute')).toContainText('expected_min')
    // the monthly PDF arrives with R3.5
    await expect(
      page.getByTestId('export-pdf').getByRole('button', { name: t('exports.pdf.download') }),
    ).toBeDisabled()
    await expectNoPageScroll(page)
  })

  test('1-minute data: one site, a status column per sensor, at most 31 days', async ({ page, t }) => {
    await page.goto(`/login?next=${encodeURIComponent(`${OCTOBER}&kind=minutes`)}`)
    await signIn(page, t, 'siti')
    await expect(page.getByTestId('export-sensor')).toHaveCount(7)
    await expect(page.getByTestId('export-columns')).toContainText('ATRH.TEMP (°C)')
    await expect(page.getByTestId('export-size')).toContainText(/44[.,]640/)
    await page.getByTestId('export-site').selectOption('middle')
    await expect(page.getByTestId('export-filename')).toHaveText(
      'SIMOLA_WIDN-CAT3_minutes_RWYMID_2026-10-01_2026-10-31.csv',
    )
    await expect(page.getByTestId('export-columns')).toContainText('LIGH.status')

    await page.getByRole('button', { name: t('period.quarter') }).click()
    await expect(page.getByTestId('export-too-long')).toBeVisible()
    await expect(page.getByTestId('export-download')).toBeDisabled()
    await expectNoPageScroll(page)
  })

  test('a site’s minute file: one row per minute, the sensors the page lists', async ({ page, t }) => {
    await page.goto(`/login?next=${encodeURIComponent(`${EXPORTS}?p=day:2026-10-03&kind=minutes`)}`)
    await signIn(page, t, 'siti')
    await page.getByTestId('export-site').selectOption('22')
    const [download] = await Promise.all([
      page.waitForEvent('download'),
      page.getByTestId('export-download').click(),
    ])
    expect(download.suggestedFilename()).toBe('SIMOLA_WIDN-CAT3_minutes_RWY22_2026-10-03_2026-10-03.csv')
    const file = await csv((await download.path())!)
    expect(file.rows).toBe(1440)
    expect(file.header.filter((h) => h.endsWith('.status'))).toHaveLength(7)
    expect(file.header).toContain('RVR.VIS (m)')
  })

  test('a refused download is explained on the page', async ({ page, t }) => {
    // like the server, sample mode gives a person ten files a minute (API-10)
    await page.goto(`/login?next=${encodeURIComponent(`${OCTOBER}&kind=quality`)}`)
    await signIn(page, t, 'siti')
    const button = page.getByTestId('export-download')
    for (let i = 0; i < 10; i++) {
      await Promise.all([page.waitForEvent('download'), button.click()])
      await expect(button).toBeEnabled()
    }
    await button.click()
    await expect(page.getByTestId('export-failed')).toHaveText(t('exports.error.too_many_exports'))
  })

  test('flags and detections: at least one kind of record', async ({ page, t }) => {
    await page.goto(`/login?next=${encodeURIComponent(`${OCTOBER}&kind=quality`)}`)
    await signIn(page, t, 'siti')
    await page.getByLabel(t('exports.quality.flags')).uncheck()
    await page.getByLabel(t('exports.quality.detections'), { exact: true }).uncheck()
    await expect(page.getByText(t('exports.quality.none'))).toBeVisible()
    await expect(page.getByTestId('export-download')).toBeDisabled()
    await expect(page.getByLabel(t('exports.quality.all'))).toBeDisabled()
  })
})
