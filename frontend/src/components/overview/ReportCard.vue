<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import { ApiProblem, api } from '@/api/client'
import type { SystemSummary } from '@/api/types'
import { useLoader } from '@/composables/useLoader'
import type { Locale } from '@/i18n'
import { useDisplayStore } from '@/stores/display'
import { saveBlob } from '@/utils/download'
import { reportFileName } from '@/utils/exports'
import { pct } from '@/utils/format'
import { lastCompleteMonth } from '@/utils/overview'
import { boardPath } from '@/utils/paths'

// Last month's report (FR-EXP-001), for signed-in users: its SLA and OLA and the two PDFs, one click each.
// The same server route as the Exports page, so the same limit, lock and audit entry apply.
const props = defineProps<{ systems: SystemSummary[] }>()
const { t, te, locale } = useI18n()
const lc = computed(() => locale.value as Locale)
const display = useDisplayStore()

const data = useLoader(async () => {
  const now = new Date()
  const each = await Promise.all(
    props.systems.map(async (s) => {
      const info = await display.system(s.code)
      const month = lastCompleteMonth(info.coverage_start, now)
      if (!month) return null
      const [y, m] = month.split('-').map(Number) as [number, number]
      const k = await api.kpis(s.code, new Date(Date.UTC(y, m - 1, 1)), new Date(Date.UTC(y, m, 1)))
      return { code: s.code, name: s.name[lc.value], month, sla: k.sla.pct, ola: k.ola.pct }
    }),
  )
  return each.filter((e) => e !== null)
})
void data.load()

const monthLabel = (m: string) =>
  new Intl.DateTimeFormat(lc.value === 'id' ? 'id-ID' : 'en-GB', {
    month: 'long',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(new Date(`${m}-01T00:00:00Z`))

const busy = ref<string | null>(null)
const elapsed = ref(0)
const failed = ref<string | null>(null)
async function download(code: string, month: string, lang: 'id' | 'en') {
  busy.value = `${code}:${lang}`
  failed.value = null
  elapsed.value = 0
  const started = Date.now()
  const tick = setInterval(() => (elapsed.value = Math.round((Date.now() - started) / 1000)), 1000)
  try {
    saveBlob(await api.monthlyReport(code, month, lang), reportFileName(code, month, lang))
  } catch (e) {
    const c = e instanceof ApiProblem ? e.code : 'other'
    failed.value = te(`exports.error.${c}`) ? c : 'other'
  } finally {
    clearInterval(tick)
    busy.value = null
  }
}
const LANGS = [
  { lang: 'id', label: 'Bahasa Indonesia' },
  { lang: 'en', label: 'English' },
] as const
</script>

<template>
  <section
    class="flex flex-col gap-2.5 rounded-lg border border-line bg-surface p-4"
    data-testid="card-report"
  >
    <h2 class="flex items-baseline gap-2 text-sm font-semibold">
      {{ t('overview.reportCard.title') }}
      <span class="ml-auto text-[0.6875rem] font-normal text-ink-3">{{ t('overview.signedInOnly') }}</span>
    </h2>
    <p v-if="data.error.value && !data.data.value" class="text-sm text-warn" role="alert">
      {{ t('common.error') }}
      <button type="button" class="icon-btn" @click="data.load()">{{ t('common.retry') }}</button>
    </p>
    <div v-else-if="!data.data.value" class="h-24 animate-pulse rounded bg-sunken" aria-busy="true" />
    <template v-else>
      <p v-if="!data.data.value.length" class="text-[0.8125rem] text-ink-3">
        {{ t('overview.reportCard.none') }}
      </p>
      <div v-for="r in data.data.value" :key="r.code" class="flex flex-col gap-2">
        <p class="text-[0.8125rem] text-ink-2">
          <span v-if="systems.length > 1" class="font-semibold">{{ r.name }} · </span>
          {{ t('overview.reportCard.ready', { month: monthLabel(r.month) }) }}
          <span class="num block"
            >SLA <b class="text-ink">{{ pct(r.sla, lc) }} %</b> · OLA
            <b class="text-ink">{{ pct(r.ola, lc) }} %</b></span
          >
        </p>
        <div class="flex flex-wrap gap-2">
          <button
            v-for="l in LANGS"
            :key="l.lang"
            type="button"
            class="rounded-md border border-line px-2.5 py-1.5 text-[0.8125rem] text-ink-2 hover:bg-sunken hover:text-ink disabled:opacity-60"
            :disabled="!!busy"
            :aria-busy="busy === `${r.code}:${l.lang}`"
            :data-testid="`dash-report-${l.lang}`"
            @click="download(r.code, r.month, l.lang)"
          >
            ⤓
            {{
              busy === `${r.code}:${l.lang}`
                ? t('exports.pdf.preparing', { s: elapsed })
                : t('overview.reportCard.pdf', { lang: l.label })
            }}
          </button>
        </div>
      </div>
      <p v-if="failed" class="text-xs text-warn" role="alert">{{ t(`exports.error.${failed}`) }}</p>
      <RouterLink
        v-if="systems[0]"
        :to="`${boardPath(systems[0].code)}/exports`"
        class="mt-auto text-[0.8125rem] text-accent hover:underline"
        >{{ t('overview.reportCard.open') }} →</RouterLink
      >
    </template>
  </section>
</template>
