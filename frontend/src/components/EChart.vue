<script setup lang="ts">
import { BarChart, HeatmapChart, LineChart, ScatterChart } from 'echarts/charts'
import {
  CalendarComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  PolarComponent,
  TooltipComponent,
  VisualMapComponent,
} from 'echarts/components'
import { init, use, type ECharts, type EChartsCoreOption } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

use([
  LineChart,
  BarChart,
  HeatmapChart,
  ScatterChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  VisualMapComponent,
  CalendarComponent,
  PolarComponent,
  MarkAreaComponent,
  CanvasRenderer,
])

const props = withDefaults(defineProps<{ option: EChartsCoreOption; height?: string; label: string }>(), {
  height: '240px',
})
const emit = defineEmits<{ click: [params: unknown] }>()

const el = ref<HTMLDivElement | null>(null)
let chart: ECharts | null = null
let observer: ResizeObserver | null = null

onMounted(() => {
  if (!el.value) return
  chart = init(el.value, undefined, { renderer: 'canvas' })
  chart.setOption({ useUTC: true, ...props.option }, true)
  chart.on('click', (p) => emit('click', p))
  observer = new ResizeObserver(() => chart?.resize())
  observer.observe(el.value)
})

watch(
  () => props.option,
  (opt) => chart?.setOption({ useUTC: true, ...opt }, true),
)

onBeforeUnmount(() => {
  observer?.disconnect()
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div ref="el" role="img" :aria-label="label" :style="{ height, width: '100%' }" />
</template>
