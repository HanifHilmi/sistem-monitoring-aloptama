<script setup lang="ts">
import type { EChartsCoreOption } from 'echarts/core'
import { computed, onMounted, reactive, ref, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api/client'
import {
  ALARM_TYPES,
  type ActiveAlarms as ActiveAlarmList,
  type AlarmEvent,
  type AlarmFilter,
  type AlarmPage,
  type AlarmType,
  type SystemInfo,
} from '@/api/types'
import ActiveAlarms from '@/components/alarms/ActiveAlarms.vue'
import AlarmTypeBadge from '@/components/alarms/AlarmTypeBadge.vue'
import EChart from '@/components/EChart.vue'
import { usePolling } from '@/composables/usePolling'
import type { Locale } from '@/i18n'
import { useDisplayStore } from '@/stores/display'
import { DEFAULT_SYSTEM } from '@/stores/live'
import { changeLabel, placeLabel, stateLabel } from '@/utils/alarms'
import { chartBase, token } from '@/utils/theme'
import { formatUtc } from '@/utils/time'

// AWOS alarms (FR-ALM-001…004, signed-in users): what the AWOS reported itself, from both CDPs' alarm files.
// Shown as reported; SIMOLA never acknowledges or annotates an alarm.
const props = withDefaults(defineProps<{ code?: string }>(), { code: DEFAULT_SYSTEM })
const { t, te, locale } = useI18n()
const lc = computed(() => locale.value as Locale)
const route = useRoute()
const router = useRouter()
const display = useDisplayStore()
const info = ref<SystemInfo | null>(null)
onMounted(async () => (info.value = await display.system(props.code)))

const tab = computed<'active' | 'history'>({
  get: () => (route.query.tab === 'history' ? 'history' : 'active'),
  set: (v) => void router.replace({ query: { ...route.query, tab: v === 'active' ? undefined : v } }),
})

// ---- active ---------------------------------------------------------------------------------------
const current = shallowRef<ActiveAlarmList | null>(null)
const active = computed(() => current.value?.active ?? null)
const notCleared = computed(() => current.value?.not_cleared ?? [])
const showNotCleared = ref(false)
const activeError = ref(false)
const now = ref(Date.now())
async function loadActive() {
  try {
    current.value = await api.activeAlarms(props.code)
    activeError.value = false
    now.value = Date.now()
  } catch {
    activeError.value = true
  }
}
usePolling(loadActive, 60_000)
const errors = computed(() => active.value?.filter((a) => a.type === 'error').length ?? 0)

// ---- history --------------------------------------------------------------------------------------
const DAY = 86_400_000
const today = new Date().toISOString().slice(0, 10)
const dayBefore = (n: number) =>
  new Date(Date.parse(`${today}T00:00:00Z`) - n * DAY).toISOString().slice(0, 10)
/** "component:04:RVR" → site:04 + RVR; "site:04", "station", "unmapped" as they are. */
function placeFromScope(v: string): { place: string; sensor: string } {
  const [kind, site, component] = v.split(':')
  if (kind === 'component' && site && component) return { place: `site:${site}`, sensor: component }
  return { place: v, sensor: '' }
}
const f = reactive({
  from: dayBefore(29),
  to: today,
  type: '' as AlarmType | '',
  // Where: a site (then optionally one of its sensors), the station, or not assigned
  ...placeFromScope(typeof route.query.scope === 'string' ? route.query.scope : ''),
  name: '',
  change: '' as '' | 'raised' | 'cleared',
  order: 'desc' as 'asc' | 'desc',
})
const scope = computed(() =>
  f.place.startsWith('site:') && f.sensor ? `component:${f.place.slice(5)}:${f.sensor}` : f.place,
)
watch(
  () => f.place,
  () => (f.sensor = ''),
)
const preset = (days: number) => Object.assign(f, { from: dayBefore(days - 1), to: today })
const filter = computed<AlarmFilter>(() => ({
  from: `${f.from}T00:00:00Z`,
  to: new Date(Date.parse(`${f.to}T00:00:00Z`) + DAY).toISOString(),
  type: f.type || undefined,
  scope: scope.value || undefined,
  name: f.name.trim() || undefined,
  active: f.change === '' ? undefined : f.change === 'raised',
  order: f.order,
}))
const page = shallowRef<AlarmPage | null>(null)
const rows = shallowRef<AlarmEvent[]>([])
const loading = ref(false)
const historyError = ref(false)
async function loadHistory(more = false) {
  if (f.from > f.to) return
  loading.value = true
  historyError.value = false
  try {
    const p = await api.alarms(props.code, filter.value, more ? rows.value.length : 0)
    rows.value = more ? [...rows.value, ...p.events] : p.events
    page.value = p
  } catch {
    historyError.value = true
  } finally {
    loading.value = false
  }
}
let timer: ReturnType<typeof setTimeout> | undefined
watch(
  [filter, tab],
  () => {
    if (tab.value !== 'history') return
    clearTimeout(timer)
    timer = setTimeout(() => void loadHistory(), 250) // typing in the search waits for a pause
  },
  { immediate: true },
)

const places = computed(() => [
  ...(info.value?.sites ?? []).map((s) => ({ value: `site:${s.slug}`, label: s.name[lc.value] })),
  { value: 'station', label: t('alarms.place.station') },
  { value: 'unmapped', label: t('alarms.place.unmapped') },
])
const sensors = computed(() =>
  f.place.startsWith('site:')
    ? (info.value?.sites.find((s) => s.slug === f.place.slice(5))?.components ?? []).map((c) => ({
        value: c.type,
        label: c.name[lc.value],
      }))
    : [],
)

const chart = computed<EChartsCoreOption | null>(() => {
  const days = page.value?.per_day
  if (!days?.length) return null
  const base = chartBase()
  return {
    ...base,
    grid: { left: 28, right: 8, top: 10, bottom: 22 },
    tooltip: { ...base.tooltip, trigger: 'axis' },
    xAxis: {
      type: 'category',
      data: days.map((d) => d.day.slice(5)),
      axisLabel: base.axisLabel,
      axisLine: base.axisLine,
      axisTick: { show: false },
    },
    yAxis: { type: 'value', minInterval: 1, axisLabel: base.axisLabel, splitLine: base.splitLine },
    series: ALARM_TYPES.map((type) => ({
      type: 'bar',
      stack: 'n',
      name: t(`alarms.type.${type}`),
      itemStyle: { color: type === 'error' ? token('bad') : token('warn') },
      data: days.map((d) => d[type]),
      barMaxWidth: 14,
    })),
  }
})
const raisedTotal = computed(() => page.value?.per_day.reduce((n, d) => n + d.error + d.warning, 0) ?? 0)
</script>

<template>
  <div class="mx-auto flex w-full max-w-6xl flex-col gap-4 px-3 py-5 sm:px-5">
    <header class="max-w-3xl">
      <h1 class="text-lg font-semibold">{{ t('alarms.title') }}</h1>
      <p class="text-sm text-ink-2">{{ t('alarms.subtitle') }}</p>
    </header>

    <div class="seg self-start" role="tablist" :aria-label="t('alarms.title')">
      <button
        type="button"
        role="tab"
        :aria-selected="tab === 'active'"
        :aria-pressed="tab === 'active'"
        @click="tab = 'active'"
      >
        {{ t('alarms.tab.active') }}
        <span v-if="active" class="num text-ink-3">{{ active.length }}</span>
      </button>
      <button
        type="button"
        role="tab"
        :aria-selected="tab === 'history'"
        :aria-pressed="tab === 'history'"
        @click="tab = 'history'"
      >
        {{ t('alarms.tab.history') }}
      </button>
    </div>

    <!-- active -->
    <section v-if="tab === 'active'" :aria-label="t('alarms.tab.active')" class="flex flex-col gap-2">
      <p v-if="activeError" class="text-sm text-warn" role="alert">{{ t('common.error') }}</p>
      <div v-else-if="!active" class="h-40 animate-pulse rounded-lg bg-sunken" aria-busy="true" />
      <p
        v-else-if="!active.length"
        class="rounded-lg border border-dashed border-line px-4 py-8 text-center text-sm text-ink-3"
      >
        ✓ {{ t('alarms.noneActive') }}
      </p>
      <template v-else>
        <p class="text-sm text-ink-2">
          {{ t('alarms.activeSummary', { n: active.length }, active.length) }}
          <template v-if="errors">({{ t('alarms.errorCount', { n: errors }, errors) }})</template>
        </p>
        <div class="rounded-lg border border-line bg-surface px-4">
          <ActiveAlarms :alarms="active" :info="info" :now="now" />
        </div>
      </template>
      <p v-if="current" class="text-xs text-ink-3">
        {{ t('alarms.activeRule', { h: current.window_hours }) }} {{ t('alarms.asReported') }}
      </p>
      <section v-if="notCleared.length" class="mt-2 flex flex-col gap-2" data-testid="alarms-not-cleared">
        <button
          type="button"
          class="flex items-center gap-2 self-start text-sm font-medium"
          :aria-expanded="showNotCleared"
          @click="showNotCleared = !showNotCleared"
        >
          <span aria-hidden="true">{{ showNotCleared ? '▾' : '▸' }}</span>
          {{ t('alarms.notCleared.title', { n: notCleared.length }, notCleared.length) }}
        </button>
        <p class="max-w-3xl text-xs text-ink-3">
          {{ t('alarms.notCleared.note', { h: current?.window_hours ?? 24 }) }}
        </p>
        <div v-if="showNotCleared" class="rounded-lg border border-line bg-surface px-4 opacity-80">
          <ActiveAlarms :alarms="notCleared" :info="info" :now="now" last-change />
        </div>
      </section>
    </section>

    <!-- history -->
    <section v-else :aria-label="t('alarms.tab.history')" class="flex flex-col gap-3">
      <div
        class="flex flex-wrap items-end gap-x-4 gap-y-2 rounded-lg border border-line bg-surface px-4 py-3"
      >
        <div class="flex flex-col gap-1">
          <span class="label">{{ t('alarms.filter.period') }}</span>
          <div class="flex flex-wrap items-center gap-1.5">
            <button
              v-for="n in [1, 7, 30]"
              :key="n"
              type="button"
              class="btn py-1 text-xs"
              @click="preset(n)"
            >
              {{ t('alarms.filter.lastDays', { n }, n) }}
            </button>
            <input
              v-model="f.from"
              type="date"
              :max="f.to"
              class="input num w-36 py-1 text-xs"
              :aria-label="t('jobs.from')"
            />
            <span class="text-ink-3">–</span>
            <input
              v-model="f.to"
              type="date"
              :min="f.from"
              :max="today"
              class="input num w-36 py-1 text-xs"
              :aria-label="t('jobs.to')"
            />
          </div>
        </div>
        <label class="flex flex-col gap-1">
          <span class="label">{{ t('alarms.filter.type') }}</span>
          <select v-model="f.type" class="input py-1 text-xs">
            <option value="">{{ t('alarms.filter.all') }}</option>
            <option v-for="x in ALARM_TYPES" :key="x" :value="x">{{ t(`alarms.type.${x}`) }}</option>
          </select>
        </label>
        <label class="flex flex-col gap-1">
          <span class="label">{{ t('alarms.filter.place') }}</span>
          <select v-model="f.place" class="input max-w-48 py-1 text-xs" data-testid="alarm-place">
            <option value="">{{ t('alarms.filter.all') }}</option>
            <option v-for="s in places" :key="s.value" :value="s.value">{{ s.label }}</option>
          </select>
        </label>
        <label v-if="sensors.length" class="flex flex-col gap-1">
          <span class="label">{{ t('alarms.filter.sensor') }}</span>
          <select v-model="f.sensor" class="input max-w-60 py-1 text-xs" data-testid="alarm-sensor">
            <option value="">{{ t('alarms.filter.allSensors') }}</option>
            <option v-for="c in sensors" :key="c.value" :value="c.value">{{ c.label }}</option>
          </select>
        </label>
        <label class="flex flex-col gap-1">
          <span class="label">{{ t('alarms.filter.change') }}</span>
          <select v-model="f.change" class="input py-1 text-xs">
            <option value="">{{ t('alarms.filter.all') }}</option>
            <option value="raised">{{ t('alarms.change.raised') }}</option>
            <option value="cleared">{{ t('alarms.change.cleared') }}</option>
          </select>
        </label>
        <label class="flex min-w-40 flex-1 flex-col gap-1">
          <span class="label">{{ t('alarms.filter.search') }}</span>
          <input
            v-model="f.name"
            type="search"
            class="input py-1 text-xs"
            :placeholder="t('alarms.filter.searchHint')"
          />
        </label>
      </div>

      <p v-if="historyError" class="text-sm text-warn" role="alert">{{ t('common.error') }}</p>
      <template v-else-if="page">
        <figure class="rounded-lg border border-line bg-surface px-3 pt-2 pb-1">
          <figcaption class="flex flex-wrap items-center gap-x-3 text-xs text-ink-2">
            <span class="font-medium text-ink">{{ t('alarms.perDay') }}</span>
            <span class="num">{{ t('alarms.raisedInPeriod', { n: raisedTotal }, raisedTotal) }}</span>
            <span class="ml-auto flex gap-3">
              <span class="flex items-center gap-1"
                ><span class="h-2 w-2 rounded-sm bg-bad" />{{ t('alarms.type.error') }}</span
              >
              <span class="flex items-center gap-1"
                ><span class="h-2 w-2 rounded-sm bg-warn" />{{ t('alarms.type.warning') }}</span
              >
            </span>
          </figcaption>
          <EChart v-if="chart" :option="chart" height="120px" :label="t('alarms.perDay')" />
        </figure>

        <div class="flex items-center gap-2 text-xs text-ink-2">
          <span class="num">{{ t('alarms.changes', { n: page.total }, page.total) }}</span>
          <button
            type="button"
            class="ml-auto text-accent hover:underline"
            @click="f.order = f.order === 'desc' ? 'asc' : 'desc'"
          >
            {{ f.order === 'desc' ? t('alarms.newestFirst') : t('alarms.oldestFirst') }} ⇅
          </button>
        </div>
        <p
          v-if="!rows.length"
          class="rounded-lg border border-dashed border-line px-4 py-8 text-center text-sm text-ink-3"
        >
          {{ t('alarms.noneInPeriod') }}
        </p>
        <!-- phones: one alarm change per row; wider screens: the table -->
        <ul
          v-if="rows.length"
          class="rounded-lg border border-line bg-surface px-3 md:hidden"
          data-testid="alarm-history-list"
        >
          <li
            v-for="e in rows"
            :key="e.id"
            class="flex flex-col gap-0.5 border-b border-line py-2.5 last:border-0"
          >
            <p class="num flex flex-wrap items-center gap-x-2 text-xs text-ink-2">
              <span>{{ formatUtc(e.time, { seconds: true }) }}</span>
              <span :class="e.raised ? 'font-medium text-ink' : 'text-ink-3'">{{ changeLabel(e, t) }}</span>
            </p>
            <p class="flex items-start gap-2 text-sm">
              <AlarmTypeBadge :type="e.type" class="mt-0.5" />
              <span class="min-w-0">{{ e.message }}</span>
            </p>
            <p class="text-xs text-ink-3">
              <span class="num">{{ e.name }}</span> ·
              <span :class="e.place.kind === 'unmapped' ? 'text-warn' : ''">{{
                placeLabel(e.place, info, lc, t)
              }}</span>
              · {{ stateLabel(e.state, t, te) }} · <span class="num">{{ e.cdps.join(' + ') }}</span>
            </p>
          </li>
        </ul>
        <div
          v-if="rows.length"
          class="overflow-x-auto rounded-lg border border-line bg-surface max-md:hidden"
        >
          <table class="w-full min-w-[720px] text-sm" data-testid="alarm-history">
            <thead class="border-b border-line bg-sunken/60 text-left text-xs text-ink-3">
              <tr>
                <th class="px-3 py-2 font-normal">{{ t('alarms.col.time') }}</th>
                <th class="px-2 py-2 font-normal">{{ t('alarms.col.change') }}</th>
                <th class="px-2 py-2 font-normal">{{ t('alarms.col.alarm') }}</th>
                <th class="px-2 py-2 font-normal">{{ t('alarms.col.place') }}</th>
                <th class="px-2 py-2 font-normal">{{ t('alarms.col.state') }}</th>
                <th class="px-3 py-2 font-normal">{{ t('alarms.col.cdps') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="e in rows" :key="e.id" class="border-b border-line align-top last:border-0">
                <td class="num px-3 py-2 text-xs whitespace-nowrap">
                  {{ formatUtc(e.time, { seconds: true }) }}
                </td>
                <td
                  class="px-2 py-2 text-xs whitespace-nowrap"
                  :class="e.raised ? 'font-medium' : 'text-ink-3'"
                >
                  {{ changeLabel(e, t) }}
                </td>
                <td class="px-2 py-2">
                  <span class="flex items-start gap-2">
                    <AlarmTypeBadge :type="e.type" class="mt-0.5" />
                    <span class="min-w-0">
                      <span class="block">{{ e.message }}</span>
                      <span class="num block text-xs text-ink-3">{{ e.name }}</span>
                    </span>
                  </span>
                </td>
                <td
                  class="px-2 py-2 text-xs"
                  :class="e.place.kind === 'unmapped' ? 'text-warn' : 'text-ink-2'"
                >
                  {{ placeLabel(e.place, info, lc, t) }}
                </td>
                <td class="px-2 py-2 text-xs text-ink-2">{{ stateLabel(e.state, t, te) }}</td>
                <td class="num px-3 py-2 text-xs whitespace-nowrap text-ink-3">{{ e.cdps.join(' + ') }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <button
          v-if="rows.length < page.total"
          type="button"
          class="btn self-center py-1 text-xs"
          :disabled="loading"
          @click="loadHistory(true)"
        >
          {{ t('alarms.more', { n: page.total - rows.length }) }}
        </button>
      </template>
      <div v-else class="h-60 animate-pulse rounded-lg bg-sunken" aria-busy="true" />
    </section>
  </div>
</template>
