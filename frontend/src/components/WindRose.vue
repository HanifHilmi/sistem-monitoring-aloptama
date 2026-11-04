<script setup lang="ts">
import type { EChartsCoreOption } from 'echarts/core'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { WindSummary } from '@/api/types'
import { chartBase, SERIES, token } from '@/utils/theme'
import EChart from './EChart.vue'

const props = defineProps<{ wind: WindSummary }>()
const { t } = useI18n()
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
const CLASSES = ['calm', 'light', 'moderate', 'strong', 'gale'] as const

const colors = () => [token('line-strong'), SERIES[0], SERIES[2], SERIES[3], SERIES[1]]
// The legend is plain HTML under the chart so it can wrap without covering the compass labels.
const legend = computed(() => CLASSES.map((c, i) => ({ label: t(`sensor.speed.${c}`), color: colors()[i] })))

const option = computed<EChartsCoreOption>(() => {
  const base = chartBase()
  const palette = colors()
  return {
    ...base,
    tooltip: { ...base.tooltip },
    polar: { radius: ['6%', '78%'], center: ['50%', '52%'] },
    angleAxis: {
      type: 'category',
      data: SECTORS,
      startAngle: 90 + 11.25,
      axisLabel: { ...base.axisLabel, fontSize: 9, interval: 1 },
      axisLine: base.axisLine,
    },
    radiusAxis: { axisLabel: { show: false }, splitLine: base.splitLine, axisLine: { show: false } },
    series: CLASSES.map((c, i) => ({
      type: 'bar',
      coordinateSystem: 'polar',
      stack: 'w',
      name: t(`sensor.speed.${c}`),
      itemStyle: { color: palette[i] },
      data: props.wind.rose.map((r) => r[c] ?? 0),
    })),
  }
})
</script>

<template>
  <div>
    <EChart :option="option" height="210px" :label="t('sensor.windRose')" />
    <ul class="mt-1 flex flex-wrap justify-center gap-x-3 gap-y-0.5 text-[0.625rem] text-ink-3">
      <li v-for="l in legend" :key="l.label" class="flex items-center gap-1">
        <span class="h-2 w-2 rounded-[2px]" :style="{ background: l.color }" />{{ l.label }}
      </li>
    </ul>
  </div>
</template>
