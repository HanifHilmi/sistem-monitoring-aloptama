// The Admin area's system chooser (2026-11-20): every Admin page says which monitored system it changes, or that it
// is for all of SIMOLA; systems still to come are listed as "coming soon". Read-only, so it can run on a deployed site.
import { expect, expectNoPageScroll, hasAccount, signIn, test } from './fixtures'

const CAT3 = /AWOS CAT\.\s?III/

test.describe('Admin system chooser', () => {
  test.skip(!hasAccount(), 'needs SIMOLA_E2E_USER and SIMOLA_E2E_PASSWORD on a deployed site')

  test('each Admin page names the system it changes; systems still to come are listed', async ({
    page,
    t,
  }) => {
    await page.goto('/login?next=/admin/components')
    await signIn(page, t)
    await expect(page).toHaveURL(/\/admin\/components/)
    const scope = page.getByTestId('admin-scope')
    await expect(scope).toContainText(CAT3)
    await expect(scope).toContainText(t('admin.scope.system'))
    await expectNoPageScroll(page)

    await page.locator('[data-testid="admin-system"]:visible').click()
    const menu = page.getByRole('menu', { name: t('admin.system.choose') })
    await expect(menu.getByRole('menuitemradio', { checked: true })).toContainText(CAT3)
    await expect(menu.getByTestId('admin-system-soon')).toHaveCount(3)
    await expect(menu.getByTestId('admin-system-soon').first()).toContainText(t('nav.comingSoon'))
    await page.keyboard.press('Escape')
    await expect(menu).toHaveCount(0)

    await page.locator('nav a[href="/admin/users"]:visible').click()
    await expect(scope).toContainText('SIMOLA')
    await expect(scope).toContainText(t('admin.scope.shared'))
    await expect(scope).not.toContainText(CAT3)
  })

  test('on phones the open section is in view and the station card keeps its name readable', async ({
    page,
    t,
  }) => {
    test.skip(page.viewportSize()!.width >= 1024, 'phones only: wide screens list every section')
    await page.goto('/login?next=/admin/components')
    await signIn(page, t)
    await expect(page).toHaveURL(/\/admin\/components/)
    // Registry sits past the right edge of the section row unless the row scrolls to it
    await expect(page.getByTestId('admin-sections-row').locator('a[aria-current="page"]')).toBeInViewport({
      ratio: 1,
    })
    // the station's details wrap below its name instead of squeezing it into a narrow column
    const station = page.getByTestId('station')
    await expect(station).toBeVisible()
    const name = (await station.locator('div').first().boundingBox())!
    const details = (await station.locator('dl').boundingBox())!
    expect(details.y).toBeGreaterThanOrEqual(name.y + name.height - 1)
    expect(name.width).toBeGreaterThan(250)
    await expectNoPageScroll(page)
  })
})
