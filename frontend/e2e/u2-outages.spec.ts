// U2 (PRD §15.3): explain a dip in last month's OLA with the outage breakdown (FR-KPI-009).
import type { Locator, Page } from '@playwright/test'
import { BOARD, test, expect, expectNoPageScroll } from './fixtures'

const PCT = /^\d{1,3}[.,]\d{2}\s?%$/

/** The first whole number in a text, with either thousands separator (1,533 in English, 1.533 in Indonesian). */
function firstNumber(text: string): number {
  const m = text.match(/\d[\d.,]*/)
  return m ? Number(m[0].replace(/[.,]/g, '')) : Number.NaN
}

function lastMonth(): string {
  const now = new Date()
  return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - 1, 1)).toISOString().slice(0, 10)
}

async function openBoard(page: Page, t: (key: string) => string, period = `month:${lastMonth()}`) {
  await page.goto(`${BOARD}?p=${period}`)
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

/** No figure in a breakdown list is wider than its column ("44.640 menit hilang" once spilled out). */
async function expectNothingOverflows(list: Locator): Promise<void> {
  const spills = await list
    .locator('li button > span')
    .evaluateAll((els) =>
      els
        .filter((el) => el.scrollWidth > el.clientWidth + 1 && !el.classList.contains('truncate'))
        .map((el) => el.textContent),
    )
  expect(spills).toEqual([])
}

/** The outage section of the open panel, once it has loaded (a summary, or "nothing lost"). */
async function outageSection(page: Page, t: (key: string) => string): Promise<Locator> {
  const section = page.getByRole('dialog').getByRole('region', { name: t('outages.title') })
  await expect(section.getByTestId('outage-summary').or(section.getByText(t('outages.none')))).toBeVisible()
  return section
}

async function lostInSummary(section: Locator): Promise<number> {
  const summary = section.getByTestId('outage-summary')
  return (await summary.count()) ? firstNumber(await summary.innerText()) : 0
}

test.describe('U2 explain a dip', () => {
  test('the SLA outages add up to the minutes the SLA figure lost', async ({ page, t }) => {
    await openBoard(page, t)
    const slaCard = page
      .getByRole('region', { name: t('board.kpis') })
      .locator(':scope > div')
      .first()
    await expect(slaCard).toContainText('SLA')
    const lost = firstNumber(await slaCard.locator('p').last().innerText())

    await page
      .getByRole('grid', { name: t('board.matrix') })
      .getByRole('rowheader', { name: 'SLA', exact: true })
      .click()
    const section = await outageSection(page, t)
    expect(await lostInSummary(section)).toBe(lost)
    if (lost) {
      // every SLA minute is lost because no CDP produced data
      await expect(section.getByTestId('outage-cause')).toHaveCount(1)
      await expect(section.getByTestId('outage-cause')).toContainText(t('outages.cause.cdp_no_data'))
    }
  })

  test('the OLA outages show their causes, open a day, and the way back keeps the list', async ({
    page,
    t,
  }) => {
    await openBoard(page, t)
    await page
      .getByRole('grid', { name: t('board.matrix') })
      .getByRole('rowheader', { name: 'OLA', exact: true })
      .click()
    const section = await outageSection(page, t)
    const items = section.getByTestId('outage')
    test.skip((await items.count()) === 0, 'nothing was lost last month')

    // The causes add up to the minutes lost.
    const causes = await section.getByTestId('outage-cause').allInnerTexts()
    expect(causes.reduce((n, c) => n + firstNumber(c), 0)).toBe(await lostInSummary(section))
    const known = ['cdp_no_data', 'no_record', 'field_missing', 'flagged', 'detection'].map((c) =>
      t(`outages.cause.${c}`),
    )
    for (const c of causes) expect(known.some((k) => c.includes(k))).toBe(true)

    await expectNoPageScroll(page)
    expect(await section.evaluate((el) => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(1)

    const first = (await items.first().getAttribute('aria-label')) ?? ''
    await items.first().click()
    const panel = page.getByRole('dialog')
    await expect(panel.getByText(t('day.minuteMap'))).toBeVisible()
    await panel.getByRole('button', { name: t('common.back'), exact: true }).click()
    await expect(section.getByTestId('outage').first()).toHaveAttribute('aria-label', first)
  })

  test('a component row: outages add up to the minutes its days lost', async ({ page, t }) => {
    await openBoard(page, t)
    const losses = page.getByRole('region', { name: t('board.losses') }).getByRole('button')
    test.skip((await losses.count()) === 0, 'nothing was lost last month')
    await losses.first().click()
    const section = await outageSection(page, t)

    const days = page.getByRole('dialog').getByRole('region', { name: t('outages.byBucket.day') })
    const perDay = t('board.missing').replace('{n}', '')
    const texts = await days.getByText(perDay.trim()).allInnerTexts()
    expect(texts.length).toBeGreaterThan(0)
    expect(texts.reduce((n, s) => n + firstNumber(s), 0)).toBe(await lostInSummary(section))
    await expectNothingOverflows(days)
  })

  test('a year is explained month by month', async ({ page, t }) => {
    await openBoard(page, t, `year:${new Date().getUTCFullYear()}-01-01`)
    await page
      .getByRole('grid', { name: t('board.matrix') })
      .getByRole('rowheader', { name: 'SLA', exact: true })
      .click()
    const panel = page.getByRole('dialog')
    await expect(panel.getByRole('region', { name: t('outages.title') })).toContainText(
      t('outages.tooLong').replace('{days}', '93'),
    )
    const months = panel.getByRole('region', { name: t('outages.byBucket.month') }).getByRole('button')
    await months.and(page.locator(':enabled')).first().click()
    await outageSection(page, t)
    await expect(panel.getByRole('region', { name: t('outages.byBucket.day') })).toBeVisible()
    await expectNothingOverflows(panel.getByRole('region', { name: t('outages.byBucket.day') }))
    await expect(panel.getByRole('button', { name: t('common.back'), exact: true })).toBeVisible()
    await expectNoPageScroll(page)
  })
})
