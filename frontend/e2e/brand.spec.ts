// The SIMOLA logo (docs/brand): the sign-in page shows the full logo with the lettering for the current theme, and the
// top bar shows the mark next to the name. The theme follows the device unless the user picked one ('simola.theme').
import { expect, test } from './fixtures'

const CASES = [
  { device: 'light', chosen: null, shown: 'logo-on-light' },
  { device: 'dark', chosen: null, shown: 'logo-on-dark' },
  { device: 'dark', chosen: 'light', shown: 'logo-on-light' },
  { device: 'light', chosen: 'dark', shown: 'logo-on-dark' },
] as const

for (const c of CASES) {
  test(`sign-in shows one logo, device ${c.device}${c.chosen ? `, chosen ${c.chosen}` : ''}`, async ({
    page,
  }) => {
    await page.emulateMedia({ colorScheme: c.device })
    if (c.chosen) await page.addInitScript((v) => localStorage.setItem('simola.theme', v), c.chosen)
    await page.goto('/login')
    const logo = page.locator('[data-testid="brand-logo"]:visible')
    await expect(logo).toHaveCount(1)
    await expect(logo).toHaveClass(new RegExp(c.shown))
    await expect(logo).toHaveAttribute('alt', /SIMOLA/)
    // the file itself loaded: a broken image has no natural width
    await expect.poll(() => logo.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0)
  })
}

test('the top bar shows the mark next to the name', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByTestId('brand-mark')).toBeVisible()
})
