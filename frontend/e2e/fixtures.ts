import { test as base, expect, type Page } from '@playwright/test'
import en from '../src/i18n/en.json' with { type: 'json' }
import id from '../src/i18n/id.json' with { type: 'json' }

export type Lang = 'en' | 'id'
const messages: Record<Lang, unknown> = { en, id }

/** Text of an i18n key in a language; fails loudly on a missing key so a renamed key breaks the test, not the UI. */
export function text(lang: Lang, key: string): string {
  const v = key
    .split('.')
    .reduce<unknown>((o, k) => (o as Record<string, unknown> | undefined)?.[k], messages[lang])
  if (typeof v !== 'string') throw new Error(`missing i18n key "${key}" (${lang})`)
  return v
}

export interface Options {
  lang: Lang
}

interface Fixtures {
  t: (key: string) => string
  errors: string[]
}

export const test = base.extend<Options & Fixtures>({
  lang: ['id', { option: true }],
  t: async ({ lang }, use) => use((key) => text(lang, key)),
  page: async ({ page, lang }, use) => {
    await page.addInitScript((l) => localStorage.setItem('simola.locale', l), lang)
    await use(page)
  },
  // Every test also fails on an uncaught script error or a console error (CSP violations included).
  errors: [
    async ({ page }, use) => {
      const errors: string[] = []
      page.on('pageerror', (e) => errors.push(e.message))
      page.on('console', (m) => {
        if (m.type() === 'error') errors.push(m.text())
      })
      await use(errors)
      expect(errors, 'browser errors').toEqual([])
    },
    { auto: true },
  ],
})

export { expect }

/** The page itself never scrolls sideways (wide tables scroll inside their own box). */
export async function expectNoPageScroll(page: Page): Promise<void> {
  const { scroll, client } = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    client: document.documentElement.clientWidth,
  }))
  expect(scroll, 'page width').toBeLessThanOrEqual(client + 1)
}

/** The system board (the Dashboard at / lists every system). */
export const BOARD = '/systems/WIDN-CAT3'
export const site = (slug: string) => `${BOARD}/sites/${slug}`
