// U9 (PRD §15.7): every text exists in both languages. A key missing in one language, an empty text, a different
// set of placeholders, or an Indonesian text left in English fails here, before a screen shows it.
import { describe, expect, it } from 'vitest'
import en from './en.json'
import id from './id.json'

type Tree = { [k: string]: string | string[] | Tree }

function flat(tree: Tree, prefix = ''): Record<string, string> {
  const out: Record<string, string> = {}
  for (const [k, v] of Object.entries(tree)) {
    const key = prefix ? `${prefix}.${k}` : k
    if (typeof v === 'string') out[key] = v
    else if (Array.isArray(v)) v.forEach((x, i) => (out[`${key}[${i}]`] = x))
    else Object.assign(out, flat(v, key))
  }
  return out
}
const EN = flat(en as Tree)
const ID = flat(id as Tree)
const placeholders = (s: string) => [...new Set(s.match(/\{\w+\}/g) ?? [])].sort()

/**
 * Texts that read the same in both languages: names, units, abbreviations and words Indonesian uses as they are.
 * A new entry here is a decision that the English word is also the Indonesian one.
 */
const SAME_IN_BOTH = new Set([
  'nav.menu',
  'nav.upcoming.awsDigi',
  'nav.upcoming.awsArg',
  'kpi.sla',
  'kpi.ola',
  'day.code.v',
  'live.components',
  'problems.severity.minor',
  'problems.severity.info',
  'status.valid',
  'sensor.speed.calm',
  'sensor.speed.light',
  'sensor.speed.moderate',
  'sensor.speed.strong',
  'sensor.speed.gale',
  'sensor.field',
  'sensor.min',
  'health.database',
  'overview.normal',
  'overview.reportCard.pdf',
  'sky.ofTime',
  'role.admin',
  'admin.title',
  'users.status',
  'users.email',
  'audit.field',
  'audit.entity.alarm',
  'audit.fieldName.email',
  'audit.fieldName.filter',
  'audit.fieldName.status',
  'audit.fieldName.model',
  'jobs.statusLabel',
  'jobs.log',
  'rules.form.min',
  'review.statusLabel',
  'calibration.status.ok',
  'calibration.status.label',
  'records.meta.model',
  'records.sn',
  'records.place.elevationShort',
  'alarms.type.error',
  'alarms.filter.sensor',
  'alarms.col.alarm',
  'reports.type.metar',
  'reports.type.metreport',
  'reports.type.taf',
  'reports.runway',
  'definitions.kpi.ola.name',
  'definitions.mandatory.sensor',
  'exports.col.missing_min',
  // Names and aviation terms the Indonesian screens keep in English (Product Owner, 2026-11-13). Sensor, parameter,
  // site and system names come from the registry, where they also read the same in both languages.
  'nav.upcoming.cat1',
  'sensor.windRose',
  'sky.obscured',
  'sky.obscuredShare',
  'wx.title',
  'wx.light',
  'wx.heavy',
  'wx.tpl',
  'wx.nearby',
  'wx.with',
  'wx.and',
  'ltg.title',
])

/** METAR weather words and cloud amounts: kept in English as a group, like the codes they decode. */
const AVIATION_TERMS = /^(wx\.d\.|wx\.p\.|wx\.row\.(?!other$)|sky\.cover\.)/
const keptInEnglish = (k: string) => SAME_IN_BOTH.has(k) || AVIATION_TERMS.test(k)

describe('texts in both languages (U9)', () => {
  it('has the same keys in English and Indonesian', () => {
    expect(Object.keys(ID).filter((k) => !(k in EN))).toEqual([])
    expect(Object.keys(EN).filter((k) => !(k in ID))).toEqual([])
  })

  it('has no empty text', () => {
    expect(Object.entries({ ...EN, ...ID }).filter(([, v]) => !v.trim())).toEqual([])
  })

  it('uses the same placeholders in both languages', () => {
    const differ = Object.keys(EN).filter(
      (k) => JSON.stringify(placeholders(EN[k]!)) !== JSON.stringify(placeholders(ID[k] ?? '')),
    )
    expect(differ).toEqual([])
  })

  it('has no Indonesian text left in English, except the listed ones', () => {
    const same = Object.keys(EN).filter((k) => EN[k] === ID[k])
    expect(same.filter((k) => !keptInEnglish(k))).toEqual([])
    // and the list holds no key that has since been translated
    expect([...SAME_IN_BOTH].filter((k) => EN[k] !== ID[k])).toEqual([])
    expect(Object.keys(EN).filter((k) => AVIATION_TERMS.test(k) && EN[k] !== ID[k])).toEqual([])
  })
})
