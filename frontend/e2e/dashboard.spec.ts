// Dashboard and top bar: every system at a glance (one panel and one menu per system: room for AWOS CAT. I).
import { BOARD, expect, expectNoPageScroll, hasAccount, signIn, site, test } from './fixtures'

test.describe('Dashboard and system menu', () => {
  test('each system shows right now, the month so far and its sites', async ({ page, t }) => {
    await page.goto('/')
    await expect(page.getByRole('heading', { level: 1 })).toContainText(t('overview.title'))
    const panel = page.getByTestId('system-panel').first()
    await expect(panel.getByTestId('system-now')).toContainText('CDP1')
    await expect(panel.getByTestId('system-now')).toContainText(t('overview.slaToday'))
    const month = panel.getByTestId('system-month')
    await expect(month).toContainText(t('overview.slaMonth'))
    await expect(month.getByText(/\d{1,3}[.,]\d{2}/).first()).toBeVisible()
    await expect(month.getByTestId('strip-sla').first()).toBeVisible()
    await expect(panel.getByTestId('site-card')).toHaveCount(3)
    // public cards only: alarms and the monthly report are for signed-in users
    await expect(page.getByTestId('card-outages')).toBeVisible()
    await expect(page.getByTestId('card-calibration')).toBeVisible()
    await expect(page.getByTestId('card-alarms')).toHaveCount(0)
    await expect(page.getByTestId('card-report')).toHaveCount(0)
    await expectNoPageScroll(page)
    await panel.getByRole('link', { name: t('overview.open') }).click()
    await expect(page).toHaveURL(new RegExp(`${BOARD}(\\?.*)?$`))
    await expect(page.getByRole('heading', { level: 1 })).toContainText(t('board.title'))
  })

  test('a day in the month strip opens the board on that day; a site card opens the site', async ({
    page,
    t,
  }) => {
    await page.goto('/')
    const panel = page.getByTestId('system-panel').first()
    const first = panel.getByTestId('strip-sla').first()
    await expect(first).toBeVisible()
    const day = new Date().toISOString().slice(0, 8) + '01'
    await first.click()
    await expect(page).toHaveURL(new RegExp(`${BOARD}\\?p=day(:|%3A)${day}$`))
    await expect(page.getByRole('heading', { level: 1 })).toContainText(t('board.title'))
    await page.goBack()
    await panel.locator(`a[data-testid="site-card"][href="${site('22')}"]`).click()
    await expect(page).toHaveURL(new RegExp(`${site('22')}(\\?.*)?$`))
  })

  test('signed-in users also see the AWOS alarms and last month’s report', async ({ page, t }) => {
    test.skip(!hasAccount(), 'needs SIMOLA_E2E_USER and SIMOLA_E2E_PASSWORD on a deployed site')
    await page.goto('/login')
    await signIn(page, t, 'siti')
    await page.waitForURL((u) => u.pathname === '/')
    const alarms = page.getByTestId('card-alarms')
    await expect(alarms).toContainText(t('alarms.title'))
    await expect(
      alarms.getByRole('link', { name: new RegExp(t('overview.alarmsCard.open')) }),
    ).toHaveAttribute('href', `${BOARD}/alarms`)
    const report = page.getByTestId('card-report')
    await expect(report.getByTestId('dash-report-id')).toBeVisible()
    await expectNoPageScroll(page)
    // a download is a real report on a deployed site (audit entry, rate limit): sample data only
    if (process.env.SIMOLA_E2E_URL) return
    const now = new Date()
    const last = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - 1, 1)).toISOString().slice(0, 7)
    const [download] = await Promise.all([
      page.waitForEvent('download'),
      report.getByTestId('dash-report-en').click(),
    ])
    expect(download.suggestedFilename()).toBe(`SIMOLA_WIDN-CAT3_${last}_en.pdf`)
    await expect(report.getByRole('alert')).toHaveCount(0)
  })

  test('the system menu lists the board, the sites and the reports', async ({ page, t, isMobile }) => {
    await page.goto(BOARD)
    if (isMobile) await page.getByRole('button', { name: t('nav.menu'), exact: true }).click()
    else await page.getByTestId('system-menu').getByRole('button').click()
    const menu = isMobile ? page.locator('#mobile-nav') : page.getByRole('menu')
    await expect(menu.locator(`a[href="${BOARD}"]`)).toHaveText(t('nav.system'))
    await expect(menu.locator(`a[href^="${BOARD}/sites/"]`)).toHaveCount(3)
    await expect(menu.locator(`a[href="${BOARD}/reports"]`)).toHaveText(t('nav.reports'))
    await menu.locator(`a[href="${site('22')}"]`).click()
    await expect(page).toHaveURL(new RegExp(`${site('22')}(\\?.*)?$`))
  })

  test("the system's live state is in its menu; systems still to come are greyed out", async ({
    page,
    t,
    isMobile,
  }) => {
    await page.goto(BOARD)
    const bar = page.getByRole('banner')
    await expect(bar.getByRole('button', { name: t('problems.open') })).toBeVisible()
    if (isMobile) {
      await page.getByRole('button', { name: t('nav.menu'), exact: true }).click()
      const nav = page.locator('#mobile-nav')
      await expect(nav.getByTestId('system-status')).toContainText('CDP1')
      await expect(nav.getByTestId('system-soon')).toHaveCount(3)
      await expect(nav.getByTestId('system-soon').first()).toContainText(t('nav.comingSoon'))
      return
    }
    await expect(bar.getByText('CDP1')).toHaveCount(0) // not in the bar itself any more
    await page.getByTestId('system-menu').getByRole('button').click()
    const status = page.getByRole('menu').getByTestId('system-status')
    await expect(status).toContainText('CDP1')
    await expect(status).toContainText(t('live.components'))
    await page.keyboard.press('Escape')

    const soon = page.getByTestId('system-soon')
    await expect(soon).toHaveCount(3)
    await expect(soon.getByRole('button')).toHaveText([
      new RegExp(t('nav.upcoming.cat1').replace('.', '\\.')),
      /AWS Digi/,
      /AWS \/ ARG/,
    ])
    await soon.first().getByRole('button').click()
    await expect(page.getByRole('dialog')).toContainText(t('nav.comingSoon'))
    await expectNoPageScroll(page)
  })

  test('old links still work', async ({ page }) => {
    await page.goto('/sites/04')
    await expect(page).toHaveURL(new RegExp(`${site('04')}(\\?.*)?$`))
    await page.goto('/cat3')
    await expect(page).toHaveURL(new RegExp(`${BOARD}(\\?.*)?$`))
  })
})
