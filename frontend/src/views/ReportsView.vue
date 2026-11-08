<script setup lang="ts">
import { computed, reactive, ref, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api/client'
import {
  REPORT_TYPES,
  type LatestReports,
  type ReportDay,
  type ReportSearch,
  type ReportType,
} from '@/api/types'
import LatestReport from '@/components/reports/LatestReport.vue'
import ReportRow from '@/components/reports/ReportRow.vue'
import { usePolling } from '@/composables/usePolling'
import { DEFAULT_SYSTEM } from '@/stores/live'

// METAR/SPECI, MET REPORT/SPECIAL and TAF as the AWOS issued them (FR-RPT-001…003), for everyone: the latest of each,
// a UTC day's archive, and a text search. Shown as sent, never decoded (FR-RPT-004).
const props = withDefaults(defineProps<{ code?: string }>(), { code: DEFAULT_SYSTEM })
const { t } = useI18n()
const route = useRoute()
const router = useRouter()

type Tab = 'latest' | 'archive' | 'search'
const q = (k: string) => (typeof route.query[k] === 'string' ? (route.query[k] as string) : '')
const setQuery = (patch: Record<string, string | undefined>) =>
  void router.replace({ query: { ...route.query, ...patch } })
const tab = computed<Tab>({
  get: () => (['archive', 'search'].includes(q('tab')) ? (q('tab') as Tab) : 'latest'),
  set: (v) => setQuery({ tab: v === 'latest' ? undefined : v }),
})
const asType = (v: string): ReportType =>
  (REPORT_TYPES as readonly string[]).includes(v) ? (v as ReportType) : 'metar'

const DAY = 86_400_000
const today = () => new Date().toISOString().slice(0, 10)
const shift = (d: string, n: number) =>
  new Date(Date.parse(`${d}T00:00:00Z`) + n * DAY).toISOString().slice(0, 10)

// ---- latest -------------------------------------------------------------------------------------
const latest = shallowRef<LatestReports | null>(null)
const latestError = ref(false)
const now = ref(Date.now())
usePolling(async () => {
  if (tab.value !== 'latest') return
  try {
    latest.value = await api.latestReports(props.code)
    latestError.value = false
    now.value = Date.now()
  } catch {
    latestError.value = true
  }
}, 60_000)
watch(tab, async (v) => {
  if (v === 'latest' && !latest.value) latest.value = await api.latestReports(props.code).catch(() => null)
})

// ---- daily archive ------------------------------------------------------------------------------
const day = computed({
  get: () => (/^\d{4}-\d{2}-\d{2}$/.test(q('day')) ? q('day') : today()),
  set: (v: string) => setQuery({ day: v === today() ? undefined : v }),
})
const dayType = computed({
  get: () => asType(q('type')),
  set: (v: ReportType) => setQuery({ type: v === 'metar' ? undefined : v }),
})
const specialsOnly = ref(false)
const dayPage = shallowRef<ReportDay | null>(null)
const dayError = ref(false)
watch(
  [tab, day, dayType],
  async () => {
    if (tab.value !== 'archive') return
    dayError.value = false
    try {
      dayPage.value = await api.reportDay(props.code, day.value, dayType.value)
    } catch {
      dayError.value = true
    }
  },
  { immediate: true },
)
const isSpecial = (kind: string) => /^(SPECI|SPECIAL|TAF (AMD|COR))$/.test(kind)
const dayRows = computed(() =>
  (dayPage.value?.reports ?? []).filter((r) => !specialsOnly.value || isSpecial(r.kind)),
)

// ---- search -------------------------------------------------------------------------------------
const MAX_DAYS = 31
const s = reactive({
  type: asType(q('type')),
  from: shift(today(), -6),
  to: today(),
  text: q('q'),
})
const tooLong = computed(() => (Date.parse(s.to) - Date.parse(s.from)) / DAY + 1 > MAX_DAYS || s.from > s.to)
const found = shallowRef<ReportSearch | null>(null)
const hits = shallowRef<ReportSearch['reports']>([])
const searching = ref(false)
const searchError = ref(false)
async function runSearch(more = false) {
  if (tooLong.value) return
  searching.value = true
  searchError.value = false
  try {
    const page = await api.searchReports(
      props.code,
      { type: s.type, from: s.from, to: s.to, q: s.text.trim() },
      more ? hits.value.length : 0,
    )
    hits.value = more ? [...hits.value, ...page.reports] : page.reports
    found.value = page
  } catch {
    searchError.value = true
  } finally {
    searching.value = false
  }
}
let timer: ReturnType<typeof setTimeout> | undefined
watch(
  [tab, () => ({ ...s })],
  () => {
    if (tab.value !== 'search') return
    setQuery({ q: s.text.trim() || undefined })
    clearTimeout(timer)
    timer = setTimeout(() => void runSearch(), 300) // typing waits for a pause
  },
  { immediate: true, deep: true },
)
</script>

<template>
  <div class="mx-auto flex w-full max-w-6xl flex-col gap-4 px-3 py-5 sm:px-5">
    <header class="max-w-3xl">
      <h1 class="text-lg font-semibold">{{ t('reports.title') }}</h1>
      <p class="text-sm text-ink-2">{{ t('reports.subtitle') }}</p>
    </header>

    <div class="seg self-start" role="tablist" :aria-label="t('reports.title')">
      <button
        v-for="x in ['latest', 'archive', 'search'] as const"
        :key="x"
        type="button"
        role="tab"
        :aria-selected="tab === x"
        :aria-pressed="tab === x"
        @click="tab = x"
      >
        {{ t(`reports.tab.${x}`) }}
      </button>
    </div>

    <!-- latest -->
    <section v-if="tab === 'latest'" :aria-label="t('reports.tab.latest')" class="flex flex-col gap-3">
      <p v-if="latestError" class="text-sm text-warn" role="alert">{{ t('common.error') }}</p>
      <div v-else-if="!latest" class="h-60 animate-pulse rounded-lg bg-sunken" aria-busy="true" />
      <template v-else>
        <LatestReport v-for="x in REPORT_TYPES" :key="x" :type="x" :reports="latest[x]" :now="now" />
      </template>
    </section>

    <!-- daily archive -->
    <section v-else-if="tab === 'archive'" :aria-label="t('reports.tab.archive')" class="flex flex-col gap-3">
      <div
        class="flex flex-wrap items-end gap-x-4 gap-y-2 rounded-lg border border-line bg-surface px-4 py-3"
      >
        <div class="flex flex-col gap-1">
          <span class="label">{{ t('reports.day') }}</span>
          <div class="flex items-center gap-1.5">
            <button
              type="button"
              class="btn px-2 py-1 text-xs"
              :aria-label="t('reports.prev')"
              @click="day = shift(day, -1)"
            >
              ‹
            </button>
            <input
              :value="day"
              type="date"
              :max="today()"
              class="input num w-36 py-1 text-xs"
              :aria-label="t('reports.day')"
              data-testid="report-day"
              @change="day = ($event.target as HTMLInputElement).value || today()"
            />
            <button
              type="button"
              class="btn px-2 py-1 text-xs"
              :aria-label="t('reports.next')"
              :disabled="day >= today()"
              @click="day = shift(day, 1)"
            >
              ›
            </button>
          </div>
        </div>
        <div class="flex flex-col gap-1">
          <span class="label">{{ t('reports.kind') }}</span>
          <div class="seg" role="group" :aria-label="t('reports.kind')">
            <button
              v-for="x in REPORT_TYPES"
              :key="x"
              type="button"
              :aria-pressed="dayType === x"
              @click="dayType = x"
            >
              {{ t(`reports.type.${x}`) }}
              <span v-if="dayPage" class="num text-ink-3">{{ dayPage.counts[x] }}</span>
            </button>
          </div>
        </div>
        <label class="flex items-center gap-2 pb-1 text-xs text-ink-2">
          <input v-model="specialsOnly" type="checkbox" />
          {{ dayType === 'taf' ? t('reports.amendmentsOnly') : t('reports.specialsOnly') }}
        </label>
      </div>
      <p v-if="dayError" class="text-sm text-warn" role="alert">{{ t('common.error') }}</p>
      <div v-else-if="!dayPage" class="h-60 animate-pulse rounded-lg bg-sunken" aria-busy="true" />
      <template v-else>
        <p class="num text-xs text-ink-2">{{ t('reports.count', { n: dayRows.length }, dayRows.length) }}</p>
        <p
          v-if="!dayRows.length"
          class="rounded-lg border border-dashed border-line px-4 py-8 text-center text-sm text-ink-3"
        >
          {{ t('reports.noneDay') }}
        </p>
        <ul v-else class="rounded-lg border border-line bg-surface" data-testid="report-day-list">
          <ReportRow v-for="r in dayRows" :key="r.id" :entry="r" />
        </ul>
      </template>
    </section>

    <!-- search -->
    <section v-else :aria-label="t('reports.tab.search')" class="flex flex-col gap-3">
      <div
        class="flex flex-wrap items-end gap-x-4 gap-y-2 rounded-lg border border-line bg-surface px-4 py-3"
      >
        <label class="flex flex-col gap-1">
          <span class="label">{{ t('reports.kind') }}</span>
          <select v-model="s.type" class="input py-1 text-xs" data-testid="report-search-type">
            <option v-for="x in REPORT_TYPES" :key="x" :value="x">{{ t(`reports.type.${x}`) }}</option>
          </select>
        </label>
        <div class="flex flex-col gap-1">
          <span class="label">{{ t('reports.period') }}</span>
          <div class="flex items-center gap-1.5">
            <input
              v-model="s.from"
              type="date"
              :max="s.to"
              class="input num w-36 py-1 text-xs"
              :aria-label="t('jobs.from')"
            />
            <span class="text-ink-3">–</span>
            <input
              v-model="s.to"
              type="date"
              :min="s.from"
              :max="today()"
              class="input num w-36 py-1 text-xs"
              :aria-label="t('jobs.to')"
            />
          </div>
        </div>
        <label class="flex min-w-48 flex-1 flex-col gap-1">
          <span class="label">{{ t('reports.text') }}</span>
          <input
            v-model="s.text"
            type="search"
            class="input num py-1 text-xs"
            :placeholder="t('reports.textHint')"
            data-testid="report-search-text"
          />
        </label>
      </div>
      <p v-if="tooLong" class="text-sm text-warn" role="alert">{{ t('reports.tooLong', { n: MAX_DAYS }) }}</p>
      <p v-else-if="searchError" class="text-sm text-warn" role="alert">{{ t('common.error') }}</p>
      <template v-else-if="found">
        <p class="num text-xs text-ink-2">{{ t('reports.found', { n: found.total }, found.total) }}</p>
        <p
          v-if="!hits.length"
          class="rounded-lg border border-dashed border-line px-4 py-8 text-center text-sm text-ink-3"
        >
          {{ t('reports.noneFound') }}
        </p>
        <ul v-else class="rounded-lg border border-line bg-surface" data-testid="report-search-list">
          <ReportRow v-for="r in hits" :key="r.id" :entry="r" with-date :highlight="s.text" />
        </ul>
        <button
          v-if="hits.length < found.total"
          type="button"
          class="btn self-center py-1 text-xs"
          :disabled="searching"
          @click="runSearch(true)"
        >
          {{ t('reports.more', { n: found.total - hits.length }) }}
        </button>
      </template>
      <div v-else class="h-40 animate-pulse rounded-lg bg-sunken" aria-busy="true" />
    </section>
  </div>
</template>
