<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '@/api/client'
import type { ComponentInfo, FieldInfo, SeriesField, SeriesResponse } from '@/api/types'
import { useLoader } from '@/composables/useLoader'
import type { Locale } from '@/i18n'
import { useDisplayStore } from '@/stores/display'
import { figureLevel, int, LEVEL_TEXT, num, pct } from '@/utils/format'
import type { ChartWindow } from '@/utils/time'
import FieldChart from './FieldChart.vue'
import GustPanel from './sensors/GustPanel.vue'
import LightningView from './sensors/LightningView.vue'
import SkyChart from './sensors/SkyChart.vue'
import WeatherView from './sensors/WeatherView.vue'
import Sparkline from './Sparkline.vue'
import StatusPill from './StatusPill.vue'
import WindRose from './WindRose.vue'

// One component as a compact table: one row per field (latest, trend, min, max, mean); a row expands to a chart.
const props = defineProps<{
  systemCode: string
  siteSlug: string
  component: ComponentInfo
  fields: Record<string, FieldInfo>
  window: ChartWindow
  status: string
  refreshKey: number
}>()
const { t, locale } = useI18n()
const lc = computed(() => locale.value as Locale)
const display = useDisplayStore()
const open = ref<string | null>(null)

const loader = useLoader<SeriesResponse>(() =>
  api.series(props.systemCode, props.siteSlug, props.component.type, props.window.from, props.window.to),
)
watch(
  () => [props.window.from.getTime(), props.window.to.getTime()],
  () => loader.load(),
  { immediate: true },
)
watch(
  () => props.refreshKey,
  () => loader.load({ silent: true }),
)

const DIGITS: Record<string, number> = { '°C': 1, hPa: 1, mm: 1 }
const fmt = (v: number | string | null | undefined, unit: string | null) =>
  typeof v === 'string' ? v : num(v ?? null, lc.value, DIGITS[unit ?? ''] ?? 0, true)
// A unit such as "100 ft" is a multiplier: show it as "×100 ft" so "12 ×100 ft" is not read as "12100 ft".
const unitLabel = (u: string | null) => (u && /^\d/.test(u) ? `×${u}` : (u ?? ''))
// The latest value is older than the end of the window by more than a few minutes: show its time in amber.
const STALE_MS = 5 * 60_000
const stale = (f: SeriesField) => {
  const last = f.stats.last?.time
  const end = Math.min(props.window.to.getTime(), Date.now())
  return !last || end - Date.parse(last) > STALE_MS
}
const name = (code: string) => props.fields[code]?.name[lc.value] ?? code
const hhmm = (iso?: string | null) => (iso ? iso.slice(11, 16) : '')
const textLabel = (v: string | null | undefined) =>
  v === null || v === undefined ? '—' : v === '' ? t('sensor.noEvent') : v
const topState = (f: SeriesField) => f.text?.counts.find((c) => c.value !== '') ?? null
const avail = computed(() => loader.data.value?.availability)
// Gust speed and direction are shown as gust events under the table, not as rows.
const rows = computed(() => (loader.data.value?.fields ?? []).filter((f) => f.chart !== 'gust'))
// Cloud base 0 means no cloud detected.
const noCloud = (f: SeriesField) => f.stats.zero_minutes !== undefined && f.stats.last?.value === 0
</script>

<template>
  <section class="overflow-hidden rounded-lg border border-line bg-surface" :aria-label="component.name[lc]">
    <header class="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line px-3 py-2">
      <h3 class="text-sm font-semibold">{{ component.name[lc] }}</h3>
      <span class="num text-[0.6875rem] text-ink-3">{{ component.type }}</span>
      <StatusPill :status="status" />
      <span
        v-if="avail"
        class="num ml-auto text-xs"
        :class="LEVEL_TEXT[figureLevel(avail, display.thresholds)]"
        :title="
          t('common.validOfExpected', { valid: int(avail.valid, lc), expected: int(avail.expected, lc) })
        "
      >
        {{ pct(avail.pct, lc) }} %
        <span class="text-ink-3">· {{ t('board.missing', { n: int(avail.missing, lc) }) }}</span>
      </span>
    </header>

    <p v-if="loader.error.value" class="px-3 py-3 text-sm text-warn" role="alert">
      {{ t('common.error') }}
      <button type="button" class="icon-btn" @click="loader.load()">{{ t('common.retry') }}</button>
    </p>
    <div v-else-if="!loader.data.value" class="h-24 animate-pulse bg-sunken" aria-busy="true" />
    <table v-else class="w-full table-fixed text-xs">
      <colgroup>
        <col class="w-[34%] sm:w-[26%]" />
        <col class="w-[26%] sm:w-[16%]" />
        <col />
        <col class="w-[11%] max-sm:hidden" />
        <col class="w-[11%] max-sm:hidden" />
        <col class="w-[11%] max-sm:hidden" />
        <col class="w-7" />
      </colgroup>
      <thead class="text-[0.625rem] text-ink-3">
        <tr>
          <th class="px-3 py-1 text-left font-normal">{{ t('sensor.field') }}</th>
          <th class="text-right font-normal">{{ t('sensor.latest') }}</th>
          <th class="pl-3 text-left font-normal">{{ t('sensor.trend') }}</th>
          <th class="text-right font-normal max-sm:hidden">{{ t('sensor.min') }}</th>
          <th class="text-right font-normal max-sm:hidden">{{ t('sensor.max') }}</th>
          <th class="text-right font-normal max-sm:hidden">{{ t('sensor.mean') }}</th>
          <th />
        </tr>
      </thead>
      <tbody>
        <template v-for="f in rows" :key="f.code">
          <tr
            class="cursor-pointer border-t border-line hover:bg-sunken"
            :aria-expanded="open === f.code"
            tabindex="0"
            @click="open = open === f.code ? null : f.code"
            @keydown.enter.prevent="open = open === f.code ? null : f.code"
            @keydown.space.prevent="open = open === f.code ? null : f.code"
          >
            <td class="px-3 py-1.5 leading-tight sm:truncate">
              {{ name(f.code) }}
              <span class="num text-[0.625rem] text-ink-3"
                >{{ f.code }}<span v-if="f.mandatory" :title="t('sensor.mandatory')">*</span></span
              >
            </td>
            <td class="num text-right">
              <span v-if="noCloud(f)" class="font-medium">{{ t('sensor.noCloud') }}</span>
              <template v-else-if="f.type === 'numeric'">
                <span class="text-sm font-semibold">{{ fmt(f.stats.last?.value, f.unit) }}</span>
                <span class="text-ink-3"> {{ unitLabel(f.unit) }}</span>
              </template>
              <span v-else class="font-medium">{{
                textLabel(f.stats.last?.value as string | undefined)
              }}</span>
              <span
                class="block text-[0.625rem]"
                :class="stale(f) ? 'font-medium text-warn' : 'text-ink-3'"
                >{{ hhmm(f.stats.last?.time) }}</span
              >
            </td>
            <td class="pl-3 text-ink-3">
              <Sparkline v-if="f.series" :values="f.series.v" :width="120" :height="22" class="text-accent" />
              <span v-else-if="topState(f)" class="block truncate">{{
                t('sensor.mostFrequent', { state: topState(f)!.value, n: int(topState(f)!.minutes, lc) })
              }}</span>
              <span v-else>{{ t('sensor.noEventWindow') }}</span>
            </td>
            <td class="num text-right max-sm:hidden">
              {{ f.type === 'numeric' ? fmt(f.stats.min, f.unit) : '' }}
            </td>
            <td class="num text-right max-sm:hidden">
              {{ f.type === 'numeric' ? fmt(f.stats.max, f.unit) : '' }}
            </td>
            <td class="num text-right max-sm:hidden">
              {{ f.type === 'numeric' ? fmt(f.stats.mean, f.unit) : '' }}
            </td>
            <td class="pr-2 text-right text-ink-3" aria-hidden="true">{{ open === f.code ? '▾' : '▸' }}</td>
          </tr>
          <tr v-if="open === f.code">
            <td colspan="7" class="border-t border-line bg-sunken/50 px-3 py-2">
              <div
                class="grid gap-3"
                :class="
                  loader.data.value.wind && (f.code === 'WS' || f.code === 'WD')
                    ? 'md:grid-cols-[minmax(0,1fr)_16rem]'
                    : ''
                "
              >
                <SkyChart v-if="f.sky" :field="f" :window="window" />
                <WeatherView v-else-if="f.weather" :field="f" :window="window" />
                <LightningView v-else-if="f.lightning" :field="f" :window="window" />
                <FieldChart v-else :field="f" :name="name(f.code)" :window="window" />
                <div v-if="loader.data.value.wind && (f.code === 'WS' || f.code === 'WD')">
                  <WindRose :wind="loader.data.value.wind" />
                </div>
              </div>
            </td>
          </tr>
        </template>
      </tbody>
    </table>
    <GustPanel v-if="loader.data.value?.wind" :wind="loader.data.value.wind" />
  </section>
</template>
