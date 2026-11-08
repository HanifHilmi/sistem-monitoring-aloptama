// Fails when the Indonesian and English catalogues do not have exactly the same keys (FR-L10N-001), or when a
// message does not compile (an unescaped @ or | breaks a page only when the message is shown).
import { readFileSync } from 'node:fs'
// installed with vue-i18n; the same parser the app uses
import { createParser } from '@intlify/message-compiler'

const load = (l) => JSON.parse(readFileSync(new URL(`../src/i18n/${l}.json`, import.meta.url), 'utf8'))
const keys = (o, p = '') =>
  Object.entries(o).flatMap(([k, v]) => (v && typeof v === 'object' ? keys(v, `${p}${k}.`) : [`${p}${k}`]))

const broken = []
for (const l of ['en', 'id']) {
  const cat = load(l)
  for (const k of keys(cat)) {
    const msg = k.split('.').reduce((o, x) => o[x], cat)
    if (typeof msg !== 'string') continue
    createParser({ onError: (e) => broken.push(`${l} ${k}: ${e.message}`) }).parse(msg)
  }
}
if (broken.length) {
  console.error('i18n messages that do not compile:\n' + broken.join('\n'))
  process.exit(1)
}

const en = new Set(keys(load('en')))
const id = new Set(keys(load('id')))
const onlyEn = [...en].filter((k) => !id.has(k))
const onlyId = [...id].filter((k) => !en.has(k))
if (onlyEn.length || onlyId.length) {
  console.error('i18n catalogues differ', { missingInId: onlyEn, missingInEn: onlyId })
  process.exit(1)
}
console.log(`i18n ok: ${en.size} keys in both catalogues`)
