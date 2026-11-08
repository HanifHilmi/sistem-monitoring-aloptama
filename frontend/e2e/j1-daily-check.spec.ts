// J1 daily check (PRD §6.4, §15.3): board → figures and problems → a site → a component chart.
import type { Page } from '@playwright/test'
import { BOARD, expect, expectNoPageScroll, hasAccount, signIn, test, text, type Lang } from './fixtures'

const PCT = /^\d{1,3}[.,]\d{2}\s?%$/

/** Opens the board and waits for its figures and matrix, so later clicks do not land on a moving page. */
async function openBoard(page: Page, t: (key: string) => string): Promise<void> {
  await page.goto(BOARD)
  await expect(
    page
      .getByRole('region', { name: t('board.kpis') })
      .getByText(PCT)
      .first(),
  ).toBeVisible()
  await expect(
    page
      .getByRole('grid', { name: t('board.matrix') })
      .getByRole('gridcell')
      .first(),
  ).toBeVisible()
}

test.describe('J1 daily check', () => {
  test('board shows the headline figures and the availability matrix', async ({ page, t }) => {
    await page.goto(BOARD)
    await expect(page.getByRole('heading', { level: 1 })).toContainText(t('board.title'))

    const kpis = page.getByRole('region', { name: t('board.kpis') })
    await expect(kpis).toContainText('SLA')
    await expect(kpis).toContainText('OLA')
    await expect(kpis.getByText(PCT).first()).toBeVisible()

    const grid = page.getByRole('grid', { name: t('board.matrix') })
    await expect(grid).toBeVisible()
    await expect(grid.getByRole('rowheader', { name: 'SLA', exact: true })).toBeVisible()
    await expect(grid.getByRole('rowheader', { name: 'OLA', exact: true })).toBeVisible()
    await expectNoPageScroll(page)
  })

  test('a day in the matrix opens its detail, which closes again', async ({ page, t }) => {
    await openBoard(page, t)
    const grid = page.getByRole('grid', { name: t('board.matrix') })
    await grid.getByRole('gridcell').first().click()

    const panel = page.getByRole('dialog')
    await expect(panel).toBeVisible()
    await panel.getByRole('button', { name: t('common.close') }).click()
    await expect(panel).toBeHidden()
  })

  test('switching to a year shows one column per month', async ({ page, t }) => {
    await openBoard(page, t)
    const year = page.getByRole('button', { name: t('period.year'), exact: true })
    await year.click()
    await expect(year).toHaveAttribute('aria-pressed', 'true')

    const grid = page.getByRole('grid', { name: t('board.matrix') })
    // The header row reads: label, the 12 months, then % (and lost minutes, hidden on phones).
    await expect
      .poll(async () =>
        (await grid.getByRole('columnheader').allInnerTexts()).map((h) => h.trim()).indexOf('%'),
      )
      .toBe(13)
    await expectNoPageScroll(page)
  })

  test('the problems panel opens', async ({ page, t }) => {
    await openBoard(page, t)
    await page
      .getByRole('button', { name: t('problems.open') })
      .first()
      .click()
    const panel = page.getByRole('dialog')
    await expect(panel).toBeVisible()
    await expect(panel).toContainText(t('problems.title'))
  })

  test('a site shows its sensors, and a field opens its chart', async ({ page, t }) => {
    await openBoard(page, t)
    // Sites are in the system's menu in the top bar; on a phone, in the ☰ menu.
    const menu = page.getByRole('button', { name: t('nav.menu'), exact: true })
    if (await menu.isVisible()) await menu.click()
    else await page.getByTestId('system-menu').getByRole('button').click()
    await page.locator(`a[href^="${BOARD}/sites/"]:visible`).first().click()
    await expect(page).toHaveURL(/\/sites\/[^/]+$/)
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible()

    const block = page.locator('main section[aria-label]').first()
    await expect(block.getByRole('table')).toBeVisible()
    const row = block.locator('tr[aria-expanded="false"]').first()
    await row.click()
    await expect(block.locator('tr[aria-expanded="true"]')).toHaveCount(1)
    await expect(block.locator('canvas').first()).toBeVisible()

    const d31 = page.getByRole('button', { name: t('window.preset.31d'), exact: true })
    await d31.click()
    await expect(d31).toHaveAttribute('aria-pressed', 'true')
    await expect(block.locator('canvas').first()).toBeVisible()
    await expectNoPageScroll(page)
  })

  test('the language switch changes the page and is remembered', async ({ page, lang }) => {
    const other: Lang = lang === 'id' ? 'en' : 'id'
    await openBoard(page, (key) => text(lang, key))
    await page
      .getByRole('button', { name: `${text(lang, 'nav.language')}: ${text(lang, 'nav.switchTo')}` })
      .click()
    await expect(page.getByRole('heading', { level: 1 })).toContainText(text(other, 'board.title'))
    expect(await page.evaluate(() => localStorage.getItem('simola.locale'))).toBe(other)
  })

  test('the system health page asks for a sign-in, then loads', async ({ page, t }) => {
    test.skip(!hasAccount(), 'needs SIMOLA_E2E_USER and SIMOLA_E2E_PASSWORD on a deployed site')
    await page.goto('/internal/health')
    await expect(page).toHaveURL(/\/login\?next=/)
    await signIn(page, t, 'siti')
    await expect(page.getByRole('heading', { level: 1 })).toContainText(t('health.title'))
  })
})
