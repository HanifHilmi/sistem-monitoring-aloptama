<script setup lang="ts">
import type { EChartsCoreOption } from 'echarts/core'
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { SeriesField } from '@/api/types'
import type { Locale } from '@/i18n'
import { int, num } from '@/utils/format'
import { chartBase, SERIES } from '@/utils/theme'
import type { ChartWindow } from '@/utils/time'
import EChart from './EChart.vue'

// Full view of one field: a line chart for numbers; for text fields a state ribbon over time plus minutes per state.
const props = defineProps<{ field: SeriesField; name: string; window: ChartWindow }>()
const { t, locale } = useI18n()
const lc = computed(() => locale.value as Locale)
const themeTick = ref(0)
const bump = () => themeTick.value++
onMounted(() => window.addEventListener('simola-theme', bump))
onUnmounted(() => window.removeEventListener('simola-theme', bump))

const option = computed<EChartsCoreOption | null>(() => {
  void themeTick.value
  const s = props.field.series
  if (!s) return null
  const base = chartBase()
  // Dots for wind direction (a line would jump between 359° and 0°) and cloud base (0 = no cloud, left out).
  const dots = props.field.chart === 'dots'
  const direction = props.field.unit === '°'
  return {
    ...base,
    grid: { left: 52, right: 12, top: 18, bottom: 24 },
    tooltip: { ...base.tooltip, trigger: 'axis' },
    xAxis: {
      type: 'time',
      min: props.window.from.getTime(),
      max: props.window.to.getTime(),
      axisLabel: base.axisLabel,
      axisLine: base.axisLine,
      splitLine: { show: false },
    },
    yAxis: {
      type: 'value',
      scale: !direction && !dots,
      ...(direction ? { min: 0, max: 360, interval: 90 } : dots ? { min: 0 } : {}),
      name:
        props.field.unit && /^\d/.test(props.field.unit) ? `×${props.field.unit}` : (props.field.unit ?? ''),
      nameTextStyle: { color: base.axisLabel.color, fontSize: 10 },
      axisLabel: direction
        ? {
            ...base.axisLabel,
            formatter: (v: number) => ({ 0: 'N', 90: 'E', 180: 'S', 270: 'W', 360: 'N' })[v] ?? '',
          }
        : base.axisLabel,
      splitLine: base.splitLine,
    },
    series: [
      dots
        ? {
            type: 'scatter',
            name: props.name,
            symbolSize: 3,
            large: s.t.length > 2000,
            itemStyle: { color: SERIES[direction ? 2 : 5], opacity: 0.8 },
            data: s.t.map((x, i) => [x, s.v[i]]),
          }
        : {
            type: 'line',
            name: props.name,
            showSymbol: false,
            connectNulls: false,
            lineStyle: { width: 1.5, color: SERIES[0] },
            itemStyle: { color: SERIES[0] },
            data: s.t.map((x, i) => [x, s.v[i]]),
          },
    ],
  }
})

// ---- text fields ----
const span = computed(() => props.window.to.getTime() - props.window.from.getTime())
const stateColor = (v: string | null, i: number) =>
  v === null ? 'var(--s-bad)' : v === '' ? 'var(--s-line-strong)' : SERIES[i % SERIES.length]
const states = computed(() => {
  const names: (string | null)[] = []
  for (const [, v] of props.field.text?.transitions ?? []) if (!names.includes(v)) names.push(v)
  return names
})
const segments = computed(() => {
  const tr = props.field.text?.transitions ?? []
  const from = props.window.from.getTime()
  const to = props.window.to.getTime()
  return tr.map(([x, v], i) => {
    const start = Math.max(from, x)
    const end = Math.min(to, tr[i + 1]?.[0] ?? to)
    return {
      left: ((start - from) / span.value) * 100,
      width: Math.max(0.15, ((end - start) / span.value) * 100),
      v,
      color: stateColor(v, states.value.indexOf(v)),
    }
  })
})
const noCloudShare = computed(() => {
  const z = props.field.stats.zero_minutes ?? 0
  const n = z + props.field.stats.count
  return num(n ? (z / n) * 100 : 0, lc.value, 0)
})
const label = (v: string | null) => (v === null ? t('sensor.missing') : v === '' ? t('sensor.noEvent') : v)
const hhmm = (ms: number) => new Date(ms).toISOString().slice(11, 16)
</script>

<template>
  <div v-if="option">
    <EChart :option="option" height="210px" :label="name" />
    <p v-if="field.stats.zero_minutes !== undefined" class="num mt-1 text-[0.6875rem] text-ink-3">
      {{ t('sensor.noCloudShare', { p: noCloudShare }) }}
    </p>
  </div>
  <div v-else class="flex flex-col gap-2">
    <div class="relative h-6 overflow-hidden rounded bg-sunken" role="img" :aria-label="name">
      <span
        v-for="(s, i) in segments"
        :key="i"
        class="absolute inset-y-0"
        :style="{ left: `${s.left}%`, width: `${s.width}%`, background: s.color }"
        :title="label(s.v)"
      />
    </div>
    <div class="num flex justify-between text-[0.625rem] text-ink-3">
      <span>{{ hhmm(window.from.getTime()) }}</span
      ><span>{{ hhmm(window.to.getTime()) }} UTC</span>
    </div>
    <ul class="flex flex-wrap gap-x-4 gap-y-1 text-xs">
      <li v-for="c in field.text?.counts ?? []" :key="c.value" class="flex items-center gap-1.5">
        <span
          class="h-2.5 w-2.5 rounded-[2px]"
          :style="{ background: stateColor(c.value, states.indexOf(c.value)) }"
        />
        {{ label(c.value) }} <span class="num text-ink-3">{{ int(c.minutes, lc) }}</span>
      </li>
      <li v-if="field.text?.missing_minutes" class="flex items-center gap-1.5">
        <span class="h-2.5 w-2.5 rounded-[2px] bg-bad" />{{ t('sensor.missing') }}
        <span class="num text-ink-3">{{ int(field.text.missing_minutes, lc) }}</span>
      </li>
    </ul>
  </div>
</template>
