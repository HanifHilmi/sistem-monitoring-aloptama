// METAR, MET REPORT and TAF (R3.2, FR-RPT-001…003): public. The sample is random per day except yesterday's
// thunderstorm (a SPECI and a SPECIAL at 07:16, a TAF AMD at about 07:45), which these tests rely on.
import { BOARD, expect, expectNoPageScroll, test } from './fixtures'

test.skip(!!process.env.SIMOLA_E2E_URL, 'sample data only: the tests rely on the sample thunderstorm')

const REPORTS = `${BOARD}/reports`
const yesterday = () => new Date(Date.now() - 86_400_000).toISOString().slice(0, 10)

test.describe('Reports', () => {
  test('everyone sees the latest of each report, copyable, with the ones before', async ({ page, t }) => {
    await page.goto(REPORTS)
    for (const type of ['metar', 'metreport', 'taf']) {
      const card = page.getByTestId(`latest-${type}`)
      await expect(card.getByTestId('report-text').first()).toBeVisible()
      await expect(card.getByRole('button', { name: new RegExp(t('reports.copy')) }).first()).toBeVisible()
    }
    await expect(page.getByTestId('latest-metar').getByTestId('report-text').first()).toHaveText(
      /^(METAR|SPECI) WIDN \d{6}Z .*=$/,
    )
    await expect(page.getByTestId('latest-taf').getByTestId('report-text').first()).toContainText(/^TAF/)
    const earlier = page.getByTestId('latest-metar').getByRole('button', { expanded: false }).first()
    await earlier.click()
    await expect(page.getByTestId('latest-metar').getByTestId('report-text')).toHaveCount(2)
    await expectNoPageScroll(page)
  })

  test("a day's archive by kind, with the AWOS's notes and the CDPs", async ({ page, t }) => {
    await page.goto(`${REPORTS}?tab=archive&day=${yesterday()}`)
    const list = page.getByTestId('report-day-list')
    const speci = list.getByTestId('report-row').filter({ hasText: 'thunderstorm onset' })
    await expect(speci).toHaveCount(1)
    await expect(speci.getByTestId('report-kind')).toHaveText('SPECI')
    await expect(speci).toContainText(/07:16:\d\d/)
    await expect(speci.getByTestId('report-text')).toContainText('TSRA')
    await expect(speci).toContainText('CDP1')

    await page.getByLabel(t('reports.specialsOnly')).check()
    const kinds = await list.getByTestId('report-kind').allInnerTexts()
    expect(kinds.length).toBeGreaterThan(0)
    expect(kinds.every((k) => k === 'SPECI')).toBe(true)

    const kindGroup = page.getByRole('group', { name: t('reports.kind') })
    await kindGroup.getByRole('button', { name: /^TAF/ }).click()
    await page.getByLabel(t('reports.amendmentsOnly')).check()
    await expect(list.getByTestId('report-kind')).toHaveText(['TAF AMD'])
    await expect(list).toContainText(/FTID32 WIDN \d{6}/)

    await page.getByRole('button', { name: t('reports.next') }).click()
    await expect(page.getByTestId('report-day')).toHaveValue(new Date().toISOString().slice(0, 10))
    await expect(page.getByRole('button', { name: t('reports.next') })).toBeDisabled()
    await expectNoPageScroll(page)
  })

  test('search finds text within a kind and a period, and marks it', async ({ page, t }) => {
    await page.goto(`${REPORTS}?tab=search`)
    await page.getByTestId('report-search-text').fill('TSRA')
    const rows = page.getByTestId('report-search-list').getByTestId('report-row')
    await expect(rows.filter({ hasText: 'thunderstorm onset' }).filter({ hasText: yesterday() })).toHaveCount(
      1,
    )
    await expect(rows.first().locator('mark').first()).toHaveText('TSRA')
    await page.getByTestId('report-search-type').selectOption('taf')
    await expect(rows.filter({ hasText: 'TAF AMD' }).first()).toBeVisible()
    await page.getByLabel(t('jobs.from')).fill('2026-01-01')
    await expect(page.getByText(t('reports.tooLong').replace('{n}', '31'))).toBeVisible()
  })

  test('the system menu opens the reports', async ({ page, t, isMobile }) => {
    await page.goto(BOARD)
    if (isMobile) await page.locator('[aria-controls="mobile-nav"]').click()
    else await page.getByTestId('system-menu').getByRole('button').click()
    const menu = isMobile ? page.locator('#mobile-nav') : page.getByRole('menu')
    await menu.getByRole(isMobile ? 'link' : 'menuitem', { name: t('nav.reports') }).click()
    await expect(page).toHaveURL(new RegExp(`${REPORTS}$`))
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(t('reports.title'))
  })
})
