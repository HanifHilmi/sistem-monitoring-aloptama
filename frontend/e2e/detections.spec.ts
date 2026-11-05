// Validity rules and detections (R2.4, screens approved 2026-11-05). Sample data only: these tests decide
// detections and change rules, which a deployed site must never get from a test run.
import { expect, expectNoPageScroll, signIn, site, test } from './fixtures'

test.skip(!!process.env.SIMOLA_E2E_URL, 'sample data only: never decides detections on a deployed site')

test.describe('Review queue and rules', () => {
  test('an Admin opens a suspect, sees its chart, and confirms it', async ({ page, t }) => {
    await page.goto('/login?next=/admin/review')
    await signIn(page, t)
    const rows = page.getByTestId('detection-row')
    await expect(rows.first()).toBeVisible()
    const before = await rows.count()
    await expectNoPageScroll(page)

    await rows
      .first()
      .getByRole('button', { name: t('detections.review') })
      .click()
    const panel = page.getByTestId('detection-panel')
    await expect(panel.locator('canvas').first()).toBeVisible()
    await panel.getByLabel(t('detections.note')).fill('Checked on site.')
    await panel.getByRole('button', { name: t('detections.confirm') }).click()
    await expect(page.getByTestId('decided')).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(rows).toHaveCount(before - 1)
  })

  test('several suspects are rejected at once', async ({ page, t }) => {
    await page.goto('/login?next=/admin/review')
    await signIn(page, t)
    const rows = page.getByTestId('detection-row')
    await expect(rows.nth(1)).toBeVisible()
    const before = await rows.count()
    await rows.nth(0).getByRole('checkbox').check()
    await rows.nth(1).getByRole('checkbox').check()
    const bar = page.getByTestId('bulk-bar')
    await bar.getByRole('button', { name: t('review.rejectSelected') }).click()
    await expect(page.getByTestId('decided')).toBeVisible()
    await expect(rows).toHaveCount(before - 2)
  })

  test('a proposed rule shows its history and a dry run before it is approved', async ({ page, t }) => {
    await page.goto('/login?next=/admin/rules')
    await signIn(page, t)
    await expect(page.getByTestId('proposed-banner')).toBeVisible()
    await page
      .getByTestId('rule-chip')
      .filter({ hasText: t('rules.state.proposed') })
      .first()
      .click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByTestId('dry-run')).toBeVisible()
    await expect(dialog.getByText(t('rules.form.history'))).toBeVisible()
    await expect(dialog.getByRole('checkbox', { name: new RegExp(t('rules.form.approve')) })).toBeVisible()
    await expectNoPageScroll(page)
  })

  test('a new version replaces the old one and withdraws its open suspects', async ({ page, t }) => {
    await page.goto('/login?next=/admin/rules')
    await signIn(page, t)
    const temp = page.getByTestId('rule-field').filter({ hasText: 'TEMP' }).first()
    await temp
      .getByTestId('rule-chip')
      .filter({ hasText: t('rules.type.spike') })
      .click()
    const dialog = page.getByRole('dialog')
    const save = dialog.getByRole('button', { name: new RegExp(t('rules.form.saveVersion').split('{')[0]!) })
    await expect(save).toBeDisabled() // nothing changed yet
    await dialog.getByLabel(new RegExp(t('rules.form.change'))).fill('7')
    await expect(save).toBeEnabled()
    await save.click()
    await expect(dialog.getByTestId('withdrawn')).toBeVisible()
    await dialog.getByRole('button', { name: t('flags.form.done') }).click()
    await temp
      .getByTestId('rule-chip')
      .filter({ hasText: t('rules.type.spike') })
      .click()
    const versions = page.getByRole('dialog').getByTestId('versions')
    await expect(versions.getByRole('listitem').first()).toContainText(t('rules.version.inEffect'))
    await expect(versions.getByRole('listitem').nth(1)).toContainText(
      t('rules.version.replaced').split('{')[0]!.trim(),
    )
  })

  test('a rule that never raised anything can be deleted; overlaps are pointed out', async ({ page, t }) => {
    await page.goto('/login?next=/admin/rules')
    await signIn(page, t)
    const temp = page.getByTestId('rule-field').filter({ hasText: 'TEMP' }).first()
    await temp
      .getByTestId('rule-chip')
      .filter({ hasText: t('rules.type.range') })
      .first()
      .click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByTestId('overlap-warning')).toBeVisible() // a site keeps its own range rule
    await page.keyboard.press('Escape')

    const chips = temp.getByTestId('rule-chip')
    const before = await chips.count()
    await chips
      .filter({ hasText: t('rules.state.proposed') })
      .first()
      .click()
    await dialog.getByRole('button', { name: t('rules.form.delete') }).click()
    await dialog.getByRole('button', { name: t('rules.form.deleteYes'), exact: true }).click()
    await expect(chips).toHaveCount(before - 1)
  })

  test('visitors see confirmed detections only; signed-in users also see suspects', async ({ page, t }) => {
    await page.goto(site('04'))
    await expect(page.getByTestId('detection-chip').first()).toBeVisible()
    await expect(page.getByTestId('suspect-chip')).toHaveCount(0)

    await page.goto(`/login?next=${encodeURIComponent(site('04'))}`)
    await signIn(page, t)
    await expect(page.getByTestId('suspect-chip').first()).toBeVisible()
  })
})
