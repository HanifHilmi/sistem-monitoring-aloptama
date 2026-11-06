// AWOS alarms (R3.1, screens approved 2026-11-06). Sample data only: the mapping test re-maps an alarm name, which a
// deployed site must never get from a test run.
import { BOARD, expect, expectNoPageScroll, signIn, test } from './fixtures'

test.skip(!!process.env.SIMOLA_E2E_URL, 'sample data only: never re-maps alarms on a deployed site')

const ALARMS = `${BOARD}/alarms`
const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

test.describe('AWOS alarms', () => {
  test('active alarms come errors first; older ones with no clear logged are set apart', async ({
    page,
    t,
  }) => {
    await page.goto(`/login?next=${encodeURIComponent(ALARMS)}`)
    await signIn(page, t)
    const active = page.getByTestId('active-alarms').first().getByTestId('active-alarm')
    await expect(active).toHaveCount(3)
    await expect(active.first().getByTestId('alarm-type')).toContainText(t('alarms.type.error'))
    await expect(page.getByText(t('alarms.activeRule').split('{h}')[0]!.trim())).toBeVisible()

    const older = page.getByTestId('alarms-not-cleared')
    await expect(older.getByTestId('active-alarm')).toHaveCount(0) // folded away until asked for
    await older.getByRole('button').click()
    await expect(older.getByTestId('active-alarm')).toHaveCount(3)
    await expectNoPageScroll(page)
  })

  test('the history searches the alarm changes', async ({ page, t, isMobile }) => {
    await page.goto(`/login?next=${encodeURIComponent(`${ALARMS}?tab=history`)}`)
    await signIn(page, t)
    // phones get a list, wider screens the table
    const rows = isMobile
      ? page.getByTestId('alarm-history-list').locator('li')
      : page.getByTestId('alarm-history').locator('tbody tr')
    await expect(rows.first()).toBeVisible()
    const all = await rows.count()
    await page.getByPlaceholder(t('alarms.filter.searchHint')).fill('Lightning')
    await expect.poll(() => rows.count()).toBeLessThan(all)
    const texts = await rows.allInnerTexts()
    expect(texts.length).toBeGreaterThan(0)
    expect(texts.filter((r) => !r.includes('Lightning'))).toEqual([])
    await expectNoPageScroll(page)
  })

  test('the public sees how many alarms are active, never the list', async ({ page, t }) => {
    await page.goto(BOARD)
    await page
      .getByRole('button', { name: t('problems.open') })
      .first()
      .click()
    const words = t('problems.code.alarms_active').split('|')[1]!.replace('{n}', '').trim()
    await expect(page.getByRole('dialog').getByText(new RegExp(`3 ${escape(words)}`))).toBeVisible()
    await page.goto(ALARMS)
    await expect(page).toHaveURL(/\/login\?next=/)
  })

  test('an Admin assigns an alarm that arrived not assigned', async ({ page, t }) => {
    await page.goto('/login?next=/admin/alarms')
    await signIn(page, t)
    const filter = page.getByRole('group', { name: t('alarms.mapping.title') })
    await filter.getByRole('button', { name: new RegExp(`^${escape(t('alarms.place.unmapped'))}`) }).click()
    const row = page.getByTestId('alarm-name').filter({ hasText: 'AMHSGatewayTimeoutWarning' })
    await expect(row).toHaveCount(1)
    await row.getByRole('combobox').selectOption('station')
    await row.getByRole('button', { name: t('records.save') }).click()
    await expect(page.getByTestId('alarm-name')).toHaveCount(0) // nothing left to assign
    await filter.getByRole('button', { name: new RegExp(`^${escape(t('alarms.filter.all'))}`) }).click()
    await expect(
      page.getByTestId('alarm-name').filter({ hasText: 'AMHSGatewayTimeoutWarning' }),
    ).toContainText(t('alarms.mapping.byAdmin').split('{who}')[0]!.trim())
  })
})
