// Fails when the Indonesian and English catalogues do not have exactly the same keys (FR-L10N-001).
import { readFileSync } from 'node:fs'

const load = (l) => JSON.parse(readFileSync(new URL(`../src/i18n/${l}.json`, import.meta.url), 'utf8'))
const keys = (o, p = '') =>
  Object.entries(o).flatMap(([k, v]) => (v && typeof v === 'object' ? keys(v, `${p}${k}.`) : [`${p}${k}`]))

const en = new Set(keys(load('en')))
const id = new Set(keys(load('id')))
const onlyEn = [...en].filter((k) => !id.has(k))
const onlyId = [...id].filter((k) => !en.has(k))
if (onlyEn.length || onlyId.length) {
  console.error('i18n catalogues differ', { missingInId: onlyEn, missingInEn: onlyId })
  process.exit(1)
}
console.log(`i18n ok: ${en.size} keys in both catalogues`)
