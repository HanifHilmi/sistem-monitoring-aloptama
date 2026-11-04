import { createI18n } from 'vue-i18n'
import en from './en.json'
import id from './id.json'

export type Locale = 'id' | 'en'
const STORAGE_KEY = 'simola.locale'

function initialLocale(): Locale {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved === 'id' || saved === 'en') return saved
  } catch {
    /* storage may be unavailable (private mode) */
  }
  return 'id' // Indonesian is the default (decision C5)
}

export const i18n = createI18n({
  legacy: false,
  locale: initialLocale(),
  fallbackLocale: 'en',
  messages: { en, id },
})

export function setLocale(locale: Locale): void {
  i18n.global.locale.value = locale
  document.documentElement.lang = locale
  try {
    localStorage.setItem(STORAGE_KEY, locale)
  } catch {
    /* ignore */
  }
}

export function currentLocale(): Locale {
  return i18n.global.locale.value as Locale
}
