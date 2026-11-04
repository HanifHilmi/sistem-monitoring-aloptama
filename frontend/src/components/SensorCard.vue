<script setup lang="ts">
import type { EChartsCoreOption } from 'echarts/core'
import { computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '@/api/client'
import type { ComponentInfo, FieldInfo, SeriesField, SeriesResponse } from '@/api/types'
import { useLoader } from '@/composables/useLoader'
import type { Locale } from '@/i18n'
import { useDisplayStore } from '@/stores/display'
import { formatInt, formatNumber, formatPct, LEVEL_TEXT, levelFor } from '@/utils/format'
import { baseChartOptions, seriesColors, token } from '@/utils/theme'
import { formatUtc, type ChartWindow } from '@/utils/time'
import EChart from './EChart.vue'
import StatusChip from './StatusChip.vue'

const props = defineProps<{
  systemCode: string
  siteSlug: string
  component: ComponentInfo
  fields: Record<string, FieldInfo>
  window: ChartWindow
  status?: string
  refreshKey: number
}>()
const { t, locale } = useI18n()
const display = useDisplayStore()
const lc = computed(() => locale.value as Locale)

const loader = useLoader<SeriesResponse>(() =>
  api.series(props.systemCode, props.siteSlug, props.component.type, props.window.from, props.window.to),
)
watch(
  () => [props.window.from.getTime(), props.window.to.getTime(), props.siteSlug],
  () => loader.load(),
  { immediate: true },
)
watch(
  () => props.refreshKey,
  () => loader.load({ silent: true }),
)

const fieldName = (code: string) => props.fields[code]?.name[lc.value] ?? code
const numeric = computed(() =>
  (loader.data.value?.fields ?? []).filter((f) => f.type === 'numeric' && f.series),
)
const textFields = computed(() =>
  (loader.data.value?.fields ?? []).filter((f) => f.type === 'text' && f.text),
)
const hasValues = computed(() => numeric.value.some((f) => f.series!.v.some((v) => v !== null)))
const downsampled = computed(() => numeric.value.some((f) => f.series!.downsampled))

const lineOption = computed<EChartsCoreOption>(() => {
  const base = baseChartOptions()
  const colors = seriesColors()
  const units = [...new Set(numeric.value.map((f) => f.unit ?? ''))]
  const axisFor = (f: SeriesField) => Math.min(1, units.indexOf(f.unit ?? ''))
  return {
    color: colors,
    grid: { left: 52, right: units.length > 1 ? 52 : 16, top: 34, bottom: 28 },
    legend: { top: 0, textStyle: { color: token('muted') }, type: 'scroll' },
    tooltip: { ...base.tooltip, trigger: 'axis' },
    xAxis: {
      type: 'time',
      min: props.window.from.getTime(),
      max: props.window.to.getTime(),
      axisLabel: base.axisLabel,
      axisLine: base.axisLine,
    },
    yAxis: units.slice(0, 2).map((u, i) => ({
      type: 'value',
      scale: true,
      name: u,
      nameTextStyle: { color: token('muted') },
      axisLabel: base.axisLabel,
      splitLine: i === 0 ? base.splitLine : { show: false },
    })),
    series: numeric.value.map((f) => ({
      name: `${f.code}${f.unit ? ` (${f.unit})` : ''}`,
      type: 'line',
      showSymbol: false,
      connectNulls: false,
      yAxisIndex: axisFor(f),
      data: f.series!.t.map((ts, i) => [ts, f.series!.v[i]]),
    })),
  }
})

function stateOption(f: SeriesField): EChartsCoreOption {
  const base = baseChartOptions()
  const counts = f.text!.counts.slice(0, 8)
  return {
    grid: { left: 110, right: 16, top: 8, bottom: 24 },
    tooltip: { ...base.tooltip, trigger: 'axis' },
    xAxis: { type: 'value', axisLabel: base.axisLabel, splitLine: base.splitLine },
    yAxis: {
      type: 'category',
      inverse: true,
      data: counts.map((c) => c.value || t('sensor.emptyState')),
      axisLabel: { ...base.axisLabel, width: 100, overflow: 'truncate' },
    },
    series: [{ type: 'bar', data: counts.map((c) => c.minutes), itemStyle: { color: token('series-1') } }],
  }
}

const SECTORS = [
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
const SPEEDS = ['calm', 'light', 'moderate', 'strong', 'gale'] as const
const roseOption = computed<EChartsCoreOption>(() => {
  const w = loader.data.value?.wind
  const colors = [token('faint'), token('series-1'), token('series-3'), token('series-4'), token('series-5')]
  return {
    tooltip: { ...baseChartOptions().tooltip },
    polar: { radius: ['8%', '75%'] },
    angleAxis: {
      type: 'category',
      data: SECTORS,
      startAngle: 90 + 11.25,
      axisLabel: { color: token('muted'), fontSize: 10 },
    },
    radiusAxis: { axisLabel: { show: false }, splitLine: { lineStyle: { color: token('border') } } },
    legend: { bottom: 0, textStyle: { color: token('muted'), fontSize: 10 }, itemWidth: 10 },
    series: SPEEDS.map((s, i) => ({
      type: 'bar',
      coordinateSystem: 'polar',
      stack: 'wind',
      name: t(`sensor.speed.${s}`),
      itemStyle: { color: colors[i] },
      data: (w?.rose ?? []).map((r) => r[s] ?? 0),
    })),
  }
})

const kt = (v: number | null | undefined) =>
  v === null || v === undefined ? '—' : `${formatNumber(v, lc.value)} kt`

const availabilityLevel = computed(() => levelFor(loader.data.value?.availability.pct, display.thresholds))
</script>

<template>
  <article class="panel flex flex-col gap-3">
    <header class="flex flex-wrap items-start justify-between gap-2">
      <div>
        <h3 class="font-semibold">{{ component.name[lc] }}</h3>
        <p class="text-xs text-muted">
          <span v-for="(f, i) in component.fields" :key="f">
            {{ i ? ' · ' : '' }}{{ f
            }}<span v-if="component.mandatory.includes(f)" :title="t('sensor.mandatory')" aria-hidden="true"
              >*</span
            >
          </span>
        </p>
      </div>
      <div class="flex flex-col items-end gap-1">
        <StatusChip v-if="status" :status="status" :label="t(`status.${status}`)" />
        <span
          v-if="loader.data.value"
          class="text-xs tabular-nums"
          :class="LEVEL_TEXT[availabilityLevel]"
          :title="
            t('common.validOfExpected', {
              valid: formatInt(loader.data.value.availability.valid, lc),
              expected: formatInt(loader.data.value.availability.expected, lc),
            })
          "
        >
          {{ t('sensor.availability') }}: {{ formatPct(loader.data.value.availability.pct, lc) }}
        </span>
      </div>
    </header>

    <p v-if="loader.error.value" class="text-sm text-warn" role="alert">
      {{ t('common.error') }}
      <button type="button" class="btn-ghost" @click="loader.load()">{{ t('common.retry') }}</button>
    </p>
    <div v-else-if="!loader.data.value" class="h-48 animate-pulse rounded bg-panel-2" aria-busy="true" />
    <template v-else>
      <div v-if="numeric.length">
        <EChart v-if="hasValues" :option="lineOption" height="220px" :label="component.name[lc]" />
        <p v-else class="py-8 text-center text-sm text-muted">{{ t('sensor.noValues') }}</p>
        <p v-if="downsampled" class="text-right text-[11px] text-muted">{{ t('sensor.downsampled') }}</p>
      </div>

      <div v-for="f in textFields" :key="f.code">
        <h4 class="label mb-1">{{ fieldName(f.code) }} · {{ t('sensor.states') }}</h4>
        <EChart
          v-if="f.text!.counts.length"
          :option="stateOption(f)"
          :height="`${Math.max(70, Math.min(8, f.text!.counts.length) * 24 + 30)}px`"
          :label="fieldName(f.code)"
        />
        <p v-else class="text-sm text-muted">{{ t('sensor.noValues') }}</p>
      </div>

      <div v-if="loader.data.value.wind" class="grid gap-3 sm:grid-cols-[1fr_auto]">
        <div>
          <h4 class="label mb-1">{{ t('sensor.windRose') }}</h4>
          <EChart :option="roseOption" height="240px" :label="t('sensor.windRose')" />
        </div>
        <dl class="grid grid-cols-2 gap-2 text-xs sm:grid-cols-1 sm:content-start">
          <div class="rounded bg-panel-2 p-2">
            <dt class="text-muted">{{ t('sensor.maxSpeed') }}</dt>
            <dd class="font-semibold">{{ kt(loader.data.value.wind.max_speed_kt) }}</dd>
          </div>
          <div class="rounded bg-panel-2 p-2">
            <dt class="text-muted">{{ t('sensor.minSpeed') }}</dt>
            <dd class="font-semibold">{{ kt(loader.data.value.wind.min_speed_kt) }}</dd>
          </div>
          <div class="rounded bg-panel-2 p-2">
            <dt class="text-muted">{{ t('sensor.gusts') }}</dt>
            <dd class="font-semibold">{{ formatInt(loader.data.value.wind.gust.count, lc) }}</dd>
          </div>
          <div class="rounded bg-panel-2 p-2">
            <dt class="text-muted">{{ t('sensor.maxGust') }}</dt>
            <dd class="font-semibold">
              {{ kt(loader.data.value.wind.gust.max_speed_kt) }}
              <span v-if="loader.data.value.wind.gust.direction_deg !== null" class="text-muted">
                / {{ formatNumber(loader.data.value.wind.gust.direction_deg, lc, 0) }}°
              </span>
            </dd>
          </div>
        </dl>
      </div>
      <p class="text-[11px] text-muted">
        {{ formatUtc(loader.data.value.from) }} – {{ formatUtc(loader.data.value.to) }}
      </p>
    </template>
  </article>
</template>
