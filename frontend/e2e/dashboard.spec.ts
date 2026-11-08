// Dashboard and top bar: every system at a glance, one menu per system (room for AWOS CAT. I).
import { BOARD, expect, expectNoPageScroll, site, test } from './fixtures'

test.describe('Dashboard and system menu', () => {
  test('the dashboard lists the system and opens its board', async ({ page, t }) => {
    await page.goto('/')
    await expect(page.getByRole('heading', { level: 1 })).toContainText(t('overview.title'))
    const card = page.getByRole('article').first()
    await expect(card).toContainText(t('overview.slaMonth'))
    await expect(card.getByText(/\d{1,3}[.,]\d{2}/).first()).toBeVisible()
    await expectNoPageScroll(page)
    await card.getByRole('link', { name: t('overview.open') }).click()
    await expect(page).toHaveURL(new RegExp(`${BOARD}(\\?.*)?$`))
    await expect(page.getByRole('heading', { level: 1 })).toContainText(t('board.title'))
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
