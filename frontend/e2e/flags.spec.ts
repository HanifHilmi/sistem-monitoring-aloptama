// Manual flags (R2.3, screens approved 2026-11-05). Sample data only: these tests create flags, and a deployed
// site must never get test flags from here (staging keeps December and the reference months unflagged).
import type { Page } from '@playwright/test'
import { BOARD, expect, expectNoPageScroll, signIn, site, test } from './fixtures'

test.skip(!!process.env.SIMOLA_E2E_URL, 'sample data only: never flags a deployed site')

async function openRow(page: Page, code: string) {
  const row = page.getByRole('row', { name: new RegExp(`\\b${code}\\b`) }).first()
  await row.click()
  await expect(row).toHaveAttribute('aria-expanded', 'true')
}

test.describe('Manual flags', () => {
  test('an Admin flags data from the Flags page, with its effect shown first', async ({ page, t }) => {
    await page.goto('/login?next=/admin/flags')
    await signIn(page, t)
    const rows = page.getByTestId('flag-row')
    await expect(rows.first()).toBeVisible()
    const before = await rows.count()
    await expectNoPageScroll(page)

    await page.getByRole('button', { name: t('flags.new') }).click()
    const d = page.getByRole('dialog')
    await d
      .getByRole('button', { name: /\(BARO\)/ })
      .first()
      .click()
    const day = new Date(Date.now() - 86_400_000).toISOString().slice(0, 10)
    await d.getByLabel(t('flags.form.from')).fill(`${day}T06:00`)
    await d.getByLabel(t('flags.form.to')).fill(`${day}T06:30`)
    await d.getByRole('radio', { name: t('flags.reason.maintenance') }).click()
    await d.getByLabel(t('flags.form.note')).fill('Barometer port cleaned.')
    const effect = d.getByTestId('flag-effect')
    await expect(effect.getByRole('row')).toHaveCount(2) // header and the one component
    await d.getByRole('button', { name: t('flags.form.save'), exact: true }).click()
    const result = d.getByTestId('flag-result')
    await expect(result).toBeVisible()
    await expect(result.getByRole('link')).toBeVisible() // the recompute job it queued
    await result.getByRole('button', { name: t('flags.form.done') }).click()
    await expect(rows).toHaveCount(before + 1)
  })

  test('a flagged day: minute map, the day’s flags and the cause', async ({ page, t }) => {
    await page.goto(`${BOARD}?p=month:2026-10-01`)
    const grid = page.getByRole('grid', { name: t('board.matrix') })
    await grid.getByRole('gridcell', { name: /22 · Ceilometer · 21 / }).click()
    const panel = page.getByRole('dialog')
    await expect(panel.getByText(t('day.flagsTitle'))).toBeVisible()
    await expect(panel.getByText(t('day.code.g'), { exact: true })).toBeVisible() // legend
    const list = panel.getByTestId('flag-list')
    await expect(list).toContainText(t('flags.reason.sensor_fault'))
    await expect(list).not.toContainText('andi') // who flagged it is for signed-in users
    await expect(panel.getByRole('cell', { name: new RegExp(t('day.causeName.flagged')) })).toBeVisible()
    await expectNoPageScroll(page)
  })

  test('the sensor chart shades a flag; the note is for signed-in users', async ({ page, t }) => {
    await page.goto(site('04'))
    const chip = page.getByTestId('flag-chip').first()
    await expect(chip).toBeVisible()
    await openRow(page, 'TEMP')
    const list = page.getByTestId('flag-list').first()
    await expect(list).toContainText(t('flags.reason.sensor_fault'))
    await expect(list).not.toContainText('andi')
    await expect(page.getByTestId('flag-toolbar')).toHaveCount(0) // visitors cannot flag

    await page.goto(`/login?next=${encodeURIComponent(site('04'))}`)
    await signIn(page, t)
    await openRow(page, 'TEMP')
    await expect(page.getByTestId('flag-list').first()).toContainText('andi')
    const toolbar = page.getByTestId('flag-toolbar').first()
    await toolbar.getByRole('button', { name: t('flags.onChart.select') }).click()
    await expect(toolbar).toContainText(t('flags.onChart.hint'))
    await expectNoPageScroll(page)
  })
})
