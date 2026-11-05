// Records and calibration (R2.5, screens approved 2026-11-05). Sample data only: these tests record calibrations
// and change records, which a deployed site must never get from a test run.
import type { Page } from '@playwright/test'
import { BOARD, expect, expectNoPageScroll, signIn, site, test } from './fixtures'

test.skip(!!process.env.SIMOLA_E2E_URL, 'sample data only: never changes records on a deployed site')

const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

async function overdueCount(page: Page, t: (key: string) => string): Promise<number> {
  const button = page
    .getByRole('group', { name: t('calibration.filter') })
    .getByRole('button', { name: new RegExp(`^${escape(t('calibration.status.overdue'))}`) })
  return Number((await button.textContent())?.match(/\d+/)?.[0])
}

test.describe('Records and calibration', () => {
  test('an Admin records a calibration and the sensor is no longer overdue', async ({ page, t }) => {
    await page.goto('/login?next=/admin/calibration')
    await signIn(page, t)
    const rows = page.getByTestId('calibration-row')
    await expect(rows.first()).toBeVisible()
    await expect(rows.first().getByTestId('calibration-chip')).toContainText(/\d/) // overdue first
    const name = (await rows.first().locator('span').first().innerText()).split('\n')[0]!.trim()
    const before = await overdueCount(page, t)
    expect(before).toBeGreaterThan(0)
    await expectNoPageScroll(page)

    await rows
      .first()
      .getByRole('button', { name: t('calibration.record') })
      .click()
    const d = page.getByRole('dialog')
    await expect(d.getByTestId('calibration-history')).toBeVisible()
    await d.getByRole('button', { name: t('calibration.record') }).click()
    await d.getByLabel(t('calibration.performedBy')).fill('Calibration lab')
    await d.getByLabel(t('calibration.certificate')).fill('CAL/2026/0412')
    await expect(d.getByTestId('next-due-preview')).toBeVisible()
    await d.getByRole('button', { name: t('calibration.save') }).click()
    await expect(d.getByTestId('calibration-history')).toContainText('CAL/2026/0412')
    await page.keyboard.press('Escape')
    await expect.poll(() => overdueCount(page, t)).toBe(before - 1)
    await expect(rows.filter({ hasText: name }).getByTestId('calibration-chip')).toContainText(
      t('calibration.chip.ok'),
    )
  })

  test('a calibration in the future is refused before it is sent', async ({ page, t }) => {
    await page.goto('/login?next=/admin/calibration')
    await signIn(page, t)
    await page
      .getByTestId('calibration-row')
      .first()
      .getByRole('button', { name: t('calibration.record') })
      .click()
    const d = page.getByRole('dialog')
    await d.getByRole('button', { name: t('calibration.record') }).click()
    const tomorrow = new Date(Date.now() + 86_400_000).toISOString().slice(0, 10)
    await d.getByLabel(t('calibration.date')).fill(tomorrow)
    await d.getByLabel(t('calibration.performedBy')).fill('Calibration lab')
    await expect(d.getByText(t('records.error.date_in_future'))).toBeVisible()
    await expect(d.getByRole('button', { name: t('calibration.save') })).toBeDisabled()
  })

  test('the public sees a sensor’s record without its serial number; signed-in users see it', async ({
    page,
    t,
  }) => {
    await page.goto(site('22'))
    let cel = page.getByRole('region', { name: 'Ceilometer' })
    await expect(cel.getByTestId('calibration-chip')).toBeVisible()
    await cel.getByRole('button', { name: t('records.details') }).click()
    await expect(cel.getByTestId('sensor-details')).toContainText('CL31')
    await expect(cel.getByTestId('sensor-details')).not.toContainText(t('records.meta.serial_number'))
    await expectNoPageScroll(page)

    await page.goto(`/login?next=${encodeURIComponent(site('22'))}`)
    await signIn(page, t)
    cel = page.getByRole('region', { name: 'Ceilometer' })
    await cel.getByRole('button', { name: t('records.details') }).click()
    await expect(cel.getByTestId('sensor-details')).toContainText(t('records.meta.serial_number'))
  })

  test('an overdue calibration is a Problems item for everyone', async ({ page, t }) => {
    await page.goto(BOARD)
    await page
      .getByRole('button', { name: t('problems.open') })
      .first()
      .click()
    const panel = page.getByRole('dialog')
    const words = t('problems.code.calibration_overdue').split('{component}')[1]!.split('{due}')[0]!.trim()
    await expect(panel.getByText(new RegExp(escape(words))).first()).toBeVisible()
  })

  test('the change trace is for signed-in users', async ({ page, t }) => {
    await page.goto(`${BOARD}?p=month:2026-10-01`)
    const grid = page.getByRole('grid', { name: t('board.matrix') })
    await grid.getByRole('rowheader', { name: 'ATRH', exact: true }).first().click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await expect(page.getByTestId('trace')).toHaveCount(0)

    await page.goto(`/login?next=${encodeURIComponent(`${BOARD}?p=month:2026-10-01`)}`)
    await signIn(page, t)
    await grid.getByRole('rowheader', { name: 'ATRH', exact: true }).first().click()
    const trace = page.getByRole('dialog').getByTestId('trace')
    await expect(trace).toContainText(t('trace.title'))
    await expect(trace.getByRole('listitem').first()).toBeVisible() // the sample's mandatory-field change
  })

  test('the station record refuses a WMO number that is not 5 digits', async ({ page, t }) => {
    await page.goto('/login?next=/admin/components')
    await signIn(page, t)
    const station = page.getByTestId('station')
    await station.getByRole('button', { name: t('flags.edit') }).click()
    const form = page.getByTestId('place-form')
    await form.getByLabel(t('records.station.wmo_number')).fill('1234')
    await expect(form.getByText(t('records.error.invalid_wmo'))).toBeVisible()
    await expect(form.getByRole('button', { name: t('records.save') })).toBeDisabled()
    await form.getByLabel(t('records.station.wmo_number')).fill('12345')
    await expect(form.getByRole('button', { name: t('records.save') })).toBeEnabled()
  })
})
