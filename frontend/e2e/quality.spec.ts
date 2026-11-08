// Data quality and definitions (R3.3, FR-DQ-008, FR-KPI-010): public. Sample data: October 2026 holds fixed flags and
// confirmed detections, September 2026 none.
import { BOARD, expect, expectNoPageScroll, signIn, test } from './fixtures'

test.skip(
  !!process.env.SIMOLA_E2E_URL,
  'sample data only: the tests rely on the sample flags of October 2026',
)

const QUALITY = `${BOARD}/data-quality`

test.describe('Data quality and definitions', () => {
  test('a month: what flags and detections cost each sensor, and why', async ({ page, t }) => {
    await page.goto(`${QUALITY}?p=month:2026-10-01`)
    await expect(page.getByTestId('quality-flagged')).toContainText('420')
    await expect(page.getByTestId('quality-detections')).toContainText('481')
    await expect(page.getByTestId('quality-suspects')).toHaveCount(0) // the public sees no suspect count (D7)
    const rows = page.getByTestId('quality-component')
    await expect(rows).toHaveCount(7)
    await expect(rows.first()).toContainText(t('rules.type.stuck'))
    await expect(page.getByTestId('quality-flags-reasons')).toContainText(t('flags.reason.maintenance'))
    await expect(page.getByTestId('quality-detections-reasons')).toContainText(t('rules.type.spike'))
    await expectNoPageScroll(page)
  })

  test('signed-in users also see the suspects waiting for review', async ({ page, t }) => {
    await page.goto(`/login?next=${encodeURIComponent(`${QUALITY}?p=month:2026-10-01`)}`)
    await signIn(page, t)
    await expect(page.getByTestId('quality-suspects')).toBeVisible()
    await expect(page.getByTestId('quality-suspects').getByRole('link')).toHaveText(
      new RegExp(t('quality.review')),
    )
  })

  test('a month without flags says so, and a year is too long', async ({ page, t }) => {
    await page.goto(`${QUALITY}?p=month:2026-09-01`)
    await expect(page.getByTestId('quality-none')).toHaveText(t('quality.none'))
    await page.goto(`${QUALITY}?p=year:2026-01-01`)
    await expect(page.getByText(t('quality.tooLong'))).toBeVisible()
  })

  test('the definitions: version, every figure, the mandatory fields now', async ({ page, t }) => {
    await page.goto(BOARD)
    await page
      .getByRole('contentinfo')
      .getByRole('link', { name: t('app.definitions') })
      .click()
    await expect(page).toHaveURL(new RegExp(`${BOARD}/definitions$`))
    await expect(page.getByTestId('definitions-version')).toContainText('1.0')
    for (const k of ['sla', 'uptime', 'reach', 'component', 'dcp', 'site', 'ola', 'pooled'])
      await expect(page.getByTestId(`kpi-${k}`)).toContainText(t(`definitions.kpi.${k}.name`))
    const atrh = page.getByTestId('definitions-mandatory').getByRole('row').filter({ hasText: 'ATRH' })
    await expect(atrh.getByRole('cell').nth(1)).toContainText('TEMP')
    await expect(atrh.getByRole('cell').nth(1)).toContainText('RH')
    await expect(atrh.getByRole('cell').nth(2)).not.toContainText('TEMP')
    await expectNoPageScroll(page)
  })

  test('the system menu opens both pages', async ({ page, t, isMobile }) => {
    await page.goto(BOARD)
    if (isMobile) await page.locator('[aria-controls="mobile-nav"]').click()
    else await page.getByTestId('system-menu').getByRole('button').click()
    const menu = isMobile ? page.locator('#mobile-nav') : page.getByRole('menu')
    await expect(menu.locator(`a[href="${BOARD}/definitions"]`)).toHaveText(t('nav.definitions'))
    await menu.locator(`a[href="${QUALITY}"]`).click()
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(t('quality.title'))
  })
})
