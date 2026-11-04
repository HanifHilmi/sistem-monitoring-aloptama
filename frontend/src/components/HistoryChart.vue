<script setup lang="ts">
import type { EChartsCoreOption } from 'echarts/core'
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '@/api/client'
import type { HistoryResponse } from '@/api/types'
import { useLoader } from '@/composables/useLoader'
import type { Locale } from '@/i18n'
import { formatPct } from '@/utils/format'
import { baseChartOptions, token } from '@/utils/theme'
import type { Period } from '@/utils/time'
import EChart from './EChart.vue'

const props = defineProps<{ systemCode: string; period: Period }>()
const { t, locale } = useI18n()
const lc = computed(() => locale.value as Locale)
const BUCKETS = ['day', 'week', 'month', 'quarter', 'year'] as const
const bucket = ref<(typeof BUCKETS)[number]>('day')

const loader = useLoader<HistoryResponse>(() =>
  api.history(
    props.systemCode,
    props.period.from,
    new Date(Math.min(props.period.to.getTime(), Date.now() + 60_000)),
    bucket.value,
  ),
)
watch(
  () => [props.period.from.getTime(), props.period.to.getTime(), bucket.value],
  () => loader.load(),
  { immediate: true },
)

const option = computed<EChartsCoreOption>(() => {
  const rows = loader.data.value?.rows ?? []
  const base = baseChartOptions()
  const pcts = rows.flatMap((r) => [r.sla.pct, r.ola.pct]).filter((v): v is number => v !== null)
  const min = pcts.length ? Math.max(0, Math.floor(Math.min(...pcts) - 1)) : 0
  return {
    grid: { left: 48, right: 12, top: 30, bottom: 30 },
    legend: { top: 0, textStyle: { color: token('muted') } },
    tooltip: {
      ...base.tooltip,
      trigger: 'axis',
      valueFormatter: (v: number | null) => formatPct(v, lc.value),
    },
    xAxis: {
      type: 'category',
      data: rows.map((r) => r.start),
      axisLabel: base.axisLabel,
      axisLine: base.axisLine,
    },
    yAxis: {
      type: 'value',
      min,
      max: 100,
      axisLabel: { ...base.axisLabel, formatter: '{value} %' },
      splitLine: base.splitLine,
    },
    series: [
      {
        name: t('kpi.sla'),
        type: 'bar',
        data: rows.map((r) => r.sla.pct),
        itemStyle: { color: token('series-1') },
      },
      {
        name: t('kpi.ola'),
        type: 'bar',
        data: rows.map((r) => r.ola.pct),
        itemStyle: { color: token('series-2') },
      },
    ],
  }
})
</script>

<template>
  <section class="panel" :aria-label="t('history.title')">
    <div class="mb-2 flex flex-wrap items-center justify-between gap-2">
      <h2 class="label">{{ t('history.title') }}</h2>
      <label class="flex items-center gap-2 text-xs text-muted">
        {{ t('history.bucket') }}
        <select v-model="bucket" class="input">
          <option v-for="b in BUCKETS" :key="b" :value="b">{{ t(`history.${b}`) }}</option>
        </select>
      </label>
    </div>
    <p v-if="loader.error.value" class="text-sm text-warn" role="alert">{{ t('common.error') }}</p>
    <div :class="loader.loading.value ? 'opacity-50' : ''">
      <EChart :option="option" height="240px" :label="t('history.title')" />
    </div>
  </section>
</template>
