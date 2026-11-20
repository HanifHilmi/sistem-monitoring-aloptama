// Sensor parts (R3.7). Sample data only: these tests add and replace parts, which a deployed site must never get from
// a test run.
import type { Page } from '@playwright/test'
import { expect, expectNoPageScroll, signIn, test } from './fixtures'

test.skip(!!process.env.SIMOLA_E2E_URL, 'sample data only: never changes parts on a deployed site')

async function openParts(page: Page, t: (key: string) => string, sensor: string, which: 'first' | 'last') {
  await page.goto('/login?next=/admin/components')
  await signIn(page, t)
  const rows = page.getByTestId('component-row').filter({ hasText: sensor })
  await rows[which]()
    .getByRole('button', { name: t('records.open') })
    .click()
  const d = page.getByRole('dialog')
  await d.getByRole('button', { name: t('records.tab.parts'), exact: true }).click()
  await expect(d.getByTestId('parts-installed')).toBeVisible()
  return d
}

test.describe('Sensor parts', () => {
  test('replacing a receiver keeps the old one in the history', async ({ page, t }) => {
    const d = await openParts(page, t, 'Runway Visual Range', 'first') // Runway 04
    const receiver = d.getByTestId('part-row').filter({ hasText: 'Receiver 1' })
    await expect(receiver).toHaveCount(1)
    const oldSerial = (await receiver.innerText()).match(/K\d+/)![0]
    await receiver.getByRole('button', { name: t('parts.replace') }).click()
    const form = d.getByTestId('part-form')
    await form.getByLabel(t('parts.reason')).fill('Lens heater fault')
    await form.getByLabel(t('records.meta.serial_number')).fill('K9900001')
    await form.getByRole('button', { name: t('parts.saveReplace') }).click()

    await expect(receiver).toContainText('K9900001')
    await expect(receiver).toContainText(oldSerial)
    await d.getByRole('button', { name: new RegExp(t('parts.showRemoved').split('(')[0]!.trim()) }).click()
    await expect(d.getByTestId('parts-removed')).toContainText(oldSerial)
    await expect(d.getByTestId('parts-removed')).toContainText('Lens heater fault')
    await expectNoPageScroll(page)
  })

  test('a usual part not recorded yet is offered, and a removal before installation is refused', async ({
    page,
    t,
  }) => {
    const d = await openParts(page, t, 'Runway Visual Range', 'last') // Runway 22
    const missing = d.getByTestId('part-missing').filter({ hasText: 'Receiver 2' })
    await missing.getByRole('button', { name: t('parts.addOne'), exact: true }).click()
    const form = d.getByTestId('part-form')
    await expect(form.getByLabel(t('parts.role'), { exact: true })).toHaveValue('Receiver 2')
    await form.getByLabel(t('records.meta.serial_number')).fill('K9900002')
    await form.getByRole('button', { name: t('parts.save') }).click()
    await expect(d.getByTestId('part-row').filter({ hasText: 'Receiver 2' })).toContainText('K9900002')
    await expect(d.getByTestId('part-missing')).toHaveCount(0)

    // a part cannot come out before it went in
    await d
      .getByTestId('part-row')
      .filter({ hasText: 'Receiver 2' })
      .getByRole('button', { name: t('parts.remove') })
      .click()
    await form.getByLabel(t('parts.removedOn')).fill('2001-01-01')
    await expect(form.getByText(t('records.error.removed_before_installed'))).toBeVisible()
    await expect(form.getByRole('button', { name: t('parts.saveRemove') })).toBeDisabled()
  })

  test('a calibration names the part it covered', async ({ page, t }) => {
    const d = await openParts(page, t, 'Air Temperature', 'first') // Runway 04
    await d.getByRole('button', { name: t('records.tab.calibration'), exact: true }).click()
    await expect(d.getByTestId('calibration-history')).toContainText('Thermohygrometer')
    await d.getByRole('button', { name: t('calibration.record') }).click()
    const part = d.getByLabel(t('parts.calPart'))
    await expect(part.locator('option:checked')).toContainText('Thermohygrometer') // the last calibration's part
    await d.getByLabel(t('calibration.performedBy')).fill('Calibration lab')
    await d.getByRole('button', { name: t('calibration.save') }).click()
    await expect(d.getByTestId('calibration-part').first()).toContainText('Thermohygrometer')
  })
})
