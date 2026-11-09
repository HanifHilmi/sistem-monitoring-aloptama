// U9 (PRD §15.7): all visible text switches language. Every page is opened in one language and its visible text
// must hold no phrase that only the other language has (a text left untranslated, or written into a screen
// without going through the translations); switching the language keeps the page and its state (UX-012).
import type { Page } from '@playwright/test'
import en from '../src/i18n/en.json' with { type: 'json' }
import id from '../src/i18n/id.json' with { type: 'json' }
import { BOARD, expect, hasAccount, signIn, site, test, type Lang } from './fixtures'

type Tree = { [k: string]: string | string[] | Tree }
const strings = (t: Tree): string[] =>
  Object.values(t).flatMap((v) => (typeof v === 'string' ? [v] : Array.isArray(v) ? v : strings(v)))

/** The fixed parts of every text: split at plural bars and placeholders, two words or more. */
function fragments(t: Tree): string[] {
  return strings(t)
    .flatMap((s) => s.split(' | '))
    .flatMap((s) => s.split(/\{\w+\}/))
    .map((s) => s.replace(/^[\s.,:;·–—()]+|[\s.,:;·–—()]+$/g, ''))
    .filter((s) => s.length >= 10 && /\p{L}{2,}\s+\p{L}{2,}/u.test(s))
}
const ALL: Record<Lang, string[]> = { en: strings(en as Tree), id: strings(id as Tree) }
/** Phrases only `lang` has: none of them may show on a page in the other language. */
const only = (lang: Lang): string[] => {
  const other = lang === 'en' ? ALL.id : ALL.en
  return [...new Set(fragments((lang === 'en' ? en : id) as Tree))].filter(
    (f) => !other.some((s) => s.includes(f)),
  )
}

async function foreignOn(page: Page, lang: Lang): Promise<string[]> {
  await page.waitForLoadState('networkidle')
  await page.waitForTimeout(400)
  const text = await page.locator('body').innerText()
  return only(lang === 'en' ? 'id' : 'en').filter((f) => text.includes(f))
}

const PUBLIC = [
  '/',
  BOARD,
  site('04'),
  `${BOARD}/reports`,
  `${BOARD}/data-quality`,
  `${BOARD}/definitions`,
  '/login',
]
const VIEWER = ['/', `${BOARD}/alarms`, `${BOARD}/exports`, '/internal/health', '/account/password']
const ADMIN = [
  '/admin/users',
  '/admin/audit',
  '/admin/jobs',
  '/admin/flags',
  '/admin/review',
  '/admin/rules',
  '/admin/alarms',
  '/admin/calibration',
  '/admin/settings',
  '/admin/mandatory',
  '/admin/components',
]

test.describe('U9 language', () => {
  test.beforeEach(({ isMobile }) => {
    test.skip(isMobile, 'the same texts as on the desktop')
  })

  test('public pages show no text of the other language', async ({ page, lang }) => {
    const found: Record<string, string[]> = {}
    for (const path of PUBLIC) {
      await page.goto(path)
      const f = await foreignOn(page, lang)
      if (f.length) found[path] = f
    }
    expect(found).toEqual({})
  })

  for (const [who, user, paths] of [
    ['Viewer', 'siti', VIEWER],
    ['Admin', 'andi', ADMIN],
  ] as const) {
    test(`${who} pages show no text of the other language`, async ({ page, t, lang }) => {
      test.skip(!hasAccount(), 'needs SIMOLA_E2E_USER and SIMOLA_E2E_PASSWORD on a deployed site')
      test.skip(
        !!process.env.SIMOLA_E2E_URL && who === 'Admin',
        'sample data: needs the sample Admin account',
      )
      test.setTimeout(90_000)
      await page.goto('/login')
      await signIn(page, t, user)
      await page.waitForURL((u) => u.pathname === '/')
      const found: Record<string, string[]> = {}
      for (const path of paths) {
        await page.goto(path)
        const f = await foreignOn(page, lang)
        if (f.length) found[path] = f
      }
      expect(found).toEqual({})
    })
  }

  test('switching the language keeps the page and its period', async ({ page, t, lang }) => {
    const other: Lang = lang === 'en' ? 'id' : 'en'
    const url = `${BOARD}?p=month:2026-10-01`
    await page.goto(url)
    await expect(page.getByRole('heading', { level: 1 })).toContainText(t('board.title'))
    await page
      .getByRole('banner')
      .getByRole('button', { name: new RegExp(`^${t('nav.language')}`) })
      .click()
    const otherTitle = ((other === 'en' ? en : id) as { board: { title: string } }).board.title
    await expect(page.getByRole('heading', { level: 1 })).toContainText(otherTitle)
    await expect(page).toHaveURL(new RegExp(`${BOARD}\\?p=month(:|%3A)2026-10-01$`))
    expect(await page.evaluate(() => document.documentElement.lang)).toBe(other)
    expect(await foreignOn(page, other)).toEqual([])
  })
})
