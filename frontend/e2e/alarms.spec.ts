// AWOS alarms (R3.1, screens approved 2026-11-06). Sample data only: the mapping test re-maps an alarm name, which a
// deployed site must never get from a test run.
import { BOARD, expect, expectNoPageScroll, signIn, test } from './fixtures'

test.skip(!!process.env.SIMOLA_E2E_URL, 'sample data only: never re-maps alarms on a deployed site')

const ALARMS = `${BOARD}/alarms`
const MIDDLE = /Runway Middle|Landasan Tengah/
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

  test('a site lists only its own alarms, also after moving to another site', async ({
    page,
    t,
    isMobile,
  }) => {
    await page.goto(`/login?next=${encodeURIComponent(`${BOARD}/sites/22`)}`)
    await signIn(page, t)
    const chip = page.getByTestId('site-alarms')
    await chip.click()
    const list = page.getByTestId('site-alarm-list')
    await expect(list).toContainText('Sensor 22')
    await expect(list).not.toContainText('Lightning')
    await page.keyboard.press('Escape')
    await expect(list).toHaveCount(0)

    // Move within the app (the page stays mounted): Runway Middle shows its own alarm, not Runway 22's.
    if (isMobile) {
      await page.locator('[aria-controls="mobile-nav"]').click()
      await page.locator('#mobile-nav').getByRole('link', { name: MIDDLE }).click()
    } else {
      await page.getByRole('button', { name: /AWOS (CAT|KAT)/ }).click()
      await page.getByRole('menu').getByRole('menuitem', { name: MIDDLE }).click()
    }
    await expect(page).toHaveURL(/\/sites\/middle$/)
    await chip.click()
    await expect(list).toContainText('Lightning')
    await expect(list).not.toContainText('Sensor 22')
    await expectNoPageScroll(page)
  })

  test('menus open above the cards', async ({ page, t, isMobile }) => {
    test.skip(isMobile, 'phones use the full-width menu')
    await page.goto(`/login?next=${encodeURIComponent(`${BOARD}/sites/22`)}`)
    await signIn(page, t)
    await expect(page.getByTestId('site-alarms')).toBeVisible() // the page has loaded
    await page.getByRole('button', { name: /AWOS (CAT|KAT)/ }).click()
    for (const item of await page.getByRole('menu').getByRole('menuitem').all()) {
      const box = (await item.boundingBox())!
      const onTop = await page.evaluate(
        ([x, y]) => !!document.elementFromPoint(x!, y!)?.closest('[role=menu]'),
        [box.x + 12, box.y + box.height / 2],
      )
      expect(onTop, await item.innerText()).toBe(true)
    }
  })

  test('the place filter picks a site, then one of its sensors', async ({ page, t, isMobile }) => {
    await page.goto(`/login?next=${encodeURIComponent(`${ALARMS}?tab=history`)}`)
    await signIn(page, t)
    await expect(page.getByTestId('alarm-sensor')).toHaveCount(0)
    const place = page.getByTestId('alarm-place')
    // runways first, then the station and alarms not assigned yet; sensors only once a runway is chosen
    await expect(place.locator('option')).toHaveCount(6)
    const values = await place
      .locator('option')
      .evaluateAll((o) => o.map((x) => (x as HTMLOptionElement).value))
    expect(values).toEqual(['', 'site:04', 'site:middle', 'site:22', 'station', 'unmapped'])
    await place.selectOption('site:22')
    const sensor = page.getByTestId('alarm-sensor')
    await expect(sensor.locator('option').first()).toHaveText(t('alarms.filter.allSensors'))
    await sensor.selectOption('PWX')
    const rows = isMobile
      ? page.getByTestId('alarm-history-list').locator('li')
      : page.getByTestId('alarm-history').locator('tbody tr')
    const elsewhere = async () =>
      (await rows.allInnerTexts()).filter((r) => !(r.includes('Present Weather Sensor') && r.includes('22')))
        .length
    await expect.poll(elsewhere).toBe(0) // once the list has reloaded, every row is that sensor's
    expect(await rows.count()).toBeGreaterThan(0)
    await place.selectOption('station')
    await expect(page.getByTestId('alarm-sensor')).toHaveCount(0)
  })
})
