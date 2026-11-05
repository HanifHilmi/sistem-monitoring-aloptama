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

  test('the system menu lists the board, the sites and what comes later', async ({ page, t, isMobile }) => {
    await page.goto(BOARD)
    if (isMobile) await page.getByRole('button', { name: t('nav.menu'), exact: true }).click()
    else await page.getByRole('button', { name: /AWOS/ }).click()
    const menu = isMobile ? page.locator('#mobile-nav') : page.getByRole('menu')
    await expect(menu.locator(`a[href="${BOARD}"]`)).toHaveText(t('nav.system'))
    await expect(menu.locator(`a[href^="${BOARD}/sites/"]`)).toHaveCount(3)
    await expect(menu.getByText(t('nav.metar'))).toBeVisible()
    await menu.locator(`a[href="${site('22')}"]`).click()
    await expect(page).toHaveURL(new RegExp(`${site('22')}(\\?.*)?$`))
  })

  test('old links still work', async ({ page }) => {
    await page.goto('/sites/04')
    await expect(page).toHaveURL(new RegExp(`${site('04')}(\\?.*)?$`))
    await page.goto('/cat3')
    await expect(page).toHaveURL(new RegExp(`${BOARD}(\\?.*)?$`))
  })
})
