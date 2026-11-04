// Theme handling and token access. The device decides by default; the user may override (FR "follow device").

export type ThemeChoice = 'system' | 'light' | 'dark'
const KEY = 'simola.theme'

export function savedTheme(): ThemeChoice {
  try {
    const v = localStorage.getItem(KEY)
    if (v === 'light' || v === 'dark' || v === 'system') return v
  } catch {
    /* storage unavailable */
  }
  return 'system'
}

export function applyTheme(choice: ThemeChoice): void {
  const root = document.documentElement
  if (choice === 'system') root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', choice)
  try {
    localStorage.setItem(KEY, choice)
  } catch {
    /* ignore */
  }
  window.dispatchEvent(new Event('simola-theme'))
}

export function isDark(): boolean {
  const attr = document.documentElement.getAttribute('data-theme')
  if (attr) return attr === 'dark'
  return window.matchMedia('(prefers-color-scheme: dark)').matches
}

/** Resolved value of a design token, e.g. token('ink-3') -> '#7b8597'. Charts cannot read CSS variables. */
export function token(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(`--s-${name}`).trim() || '#888888'
}

/** Base ECharts options in the current theme. */
export function chartBase() {
  const ink3 = token('ink-3')
  const line = token('line')
  return {
    textStyle: {
      color: token('ink-2'),
      fontFamily: getComputedStyle(document.body).fontFamily,
      fontSize: 11,
    },
    tooltip: {
      backgroundColor: token('surface'),
      borderColor: token('line-strong'),
      textStyle: { color: token('ink'), fontSize: 12 },
    },
    axisLabel: { color: ink3, fontSize: 11 },
    axisLine: { lineStyle: { color: line } },
    splitLine: { lineStyle: { color: line } },
  }
}

/** Categorical series colours (fixed order, never cycled per chart). */
export const SERIES = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#6250d6']
