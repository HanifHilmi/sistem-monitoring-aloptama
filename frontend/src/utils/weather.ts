import type { Composer } from 'vue-i18n'

type T = Composer['t']

const TOKEN = /^([+-]?)(VC)?((?:MI|BC|PR|DR|BL|SH|TS|FZ)*)((?:[A-Z]{2})*)$/
const DESCRIPTORS = ['MI', 'BC', 'PR', 'DR', 'BL', 'SH', 'TS', 'FZ']

/** A METAR present-weather code in plain words: "-TSRA" -> "light thunderstorm with rain", "BR" -> "mist". */
export function describeWeather(code: string, t: T, te: (key: string) => boolean): string {
  if (!code.trim()) return t('wx.none')
  return code
    .trim()
    .split(/\s+/)
    .map((tok) => describeToken(tok, t, te))
    .join(', ')
}

function describeToken(tok: string, t: T, te: (key: string) => boolean): string {
  const m = TOKEN.exec(tok)
  if (!m) return tok
  const [, sign, vc, desc = '', phen = ''] = m
  const word = (kind: 'd' | 'p', c: string) => (te(`wx.${kind}.${c}`) ? t(`wx.${kind}.${c}`) : c)
  const descs: string[] = []
  for (let i = 0; i < desc.length; i += 2)
    if (DESCRIPTORS.includes(desc.slice(i, i + 2))) descs.push(word('d', desc.slice(i, i + 2)))
  const phens: string[] = []
  for (let i = 0; i < phen.length; i += 2) phens.push(word('p', phen.slice(i, i + 2)))
  let what = [...descs, phens.join(t('wx.and'))]
    .filter(Boolean)
    .join(descs.length && phens.length ? t('wx.with') : '')
  if (sign) what = t('wx.tpl', { what, intensity: t(sign === '-' ? 'wx.light' : 'wx.heavy') })
  return vc ? t('wx.nearby', { what }) : what
}

const POINTS = [
  'N',
  'NNE',
  'NE',
  'ENE',
  'E',
  'ESE',
  'SE',
  'SSE',
  'S',
  'SSW',
  'SW',
  'WSW',
  'W',
  'WNW',
  'NW',
  'NNW',
]
/** 240 -> "WSW" */
export const compassPoint = (deg: number) => POINTS[Math.round((((deg % 360) + 360) % 360) / 22.5) % 16]!

/** 192 -> "3 h 12 min" (in the current language). */
export function duration(minutes: number, t: T): string {
  const h = Math.floor(minutes / 60)
  const m = Math.round(minutes % 60)
  if (!h) return t('common.durM', { m })
  return m ? t('common.durHM', { h, m }) : t('common.durH', { h })
}
