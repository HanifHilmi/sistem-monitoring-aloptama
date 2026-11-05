// Sensor views agreed on 2026-11-05: gust events, dots for direction and cloud base, sky layers,
// present weather and lightning ribbons.
import type { Page } from '@playwright/test'
import { expect, expectNoPageScroll, site, test } from './fixtures'

async function openRow(page: Page, code: string) {
  const row = page.getByRole('row', { name: new RegExp(`\\b${code}\\b`) }).first()
  await row.click()
  await expect(row).toHaveAttribute('aria-expanded', 'true')
}

test.describe('Sensor views', () => {
  test('wind: gusts as events, direction as dots', async ({ page, t }) => {
    await page.goto(site('04'))
    await expect(page.getByRole('region', { name: t('gust.title') })).toBeVisible()
    await expect(page.getByRole('row', { name: /\bWGS\b/ })).toHaveCount(0)
    await openRow(page, 'WD')
    await expect(page.locator('canvas').first()).toBeVisible()
    await expectNoPageScroll(page)
  })

  test('cloud base and sky condition', async ({ page, t }) => {
    await page.goto(site('04'))
    await openRow(page, 'LR1')
    await expect(page.getByText(t('sensor.noCloudShare').split('{')[0]!.trim())).toBeVisible()
    await openRow(page, 'SKY')
    await expect(page.getByRole('img', { name: t('sky.chartLabel') })).toBeVisible()
    await expect(page.getByText(t('sky.band.middle'), { exact: true }).first()).toBeVisible()
    await expectNoPageScroll(page)
  })

  test('present weather ribbon', async ({ page, t }) => {
    await page.goto(site('22'))
    await openRow(page, 'PW')
    const group = page.getByRole('group', { name: t('wx.title') })
    await expect(group).toBeVisible()
    await expect(group.getByText(t('wx.row.thunderstorm'))).toBeVisible()
    await expectNoPageScroll(page)
  })

  test('lightning ribbon and directions', async ({ page, t }) => {
    await page.goto(site('middle'))
    await openRow(page, 'LTX')
    await expect(page.getByRole('group', { name: t('ltg.title') })).toBeVisible()
    await expect(page.getByRole('img', { name: t('ltg.directions') })).toBeVisible()
    await expectNoPageScroll(page)
  })
})
