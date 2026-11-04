<script setup lang="ts">
import type { EChartsCoreOption } from 'echarts/core'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '@/api/client'
import type { CalendarResponse } from '@/api/types'
import { useLoader } from '@/composables/useLoader'
import type { Locale } from '@/i18n'
import { useDisplayStore } from '@/stores/display'
import { formatInt, formatPct } from '@/utils/format'
import { baseChartOptions, token } from '@/utils/theme'
import EChart from './EChart.vue'

const props = defineProps<{ systemCode: string; cdps: string[] }>()
const emit = defineEmits<{ day: [string] }>()
const { t, locale } = useI18n()
const display = useDisplayStore()
const lc = computed(() => locale.value as Locale)

// ECharts only ships EN/ZH calendar labels; Indonesian names are supplied here (Sunday first).
const ID_DAYS = ['Min', 'Sen', 'Sel', 'Rab', 'Kam', 'Jum', 'Sab']
const ID_MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des']

const now = new Date()
const year = ref(now.getUTCFullYear())
const month = ref(now.getUTCMonth())
const metric = ref('sla')
const narrow = ref(false)
const years = computed(() => Array.from({ length: now.getUTCFullYear() - 2024 }, (_, i) => 2025 + i))

const loader = useLoader<CalendarResponse>(() => api.calendar(props.systemCode, year.value, metric.value))
watch([year, metric], () => loader.load())

let mq: MediaQueryList | null = null
const onMq = () => (narrow.value = !!mq?.matches)
onMounted(() => {
  mq = window.matchMedia('(max-width: 639px)')
  onMq()
  mq.addEventListener('change', onMq)
  void loader.load()
})
onUnmounted(() => mq?.removeEventListener('change', onMq))

const range = computed(() =>
  narrow.value ? `${year.value}-${String(month.value + 1).padStart(2, '0')}` : String(year.value),
)

const option = computed<EChartsCoreOption>(() => {
  const days = loader.data.value?.days ?? []
  const base = baseChartOptions()
  const { good, warning } = display.thresholds
  return {
    tooltip: {
      ...base.tooltip,
      formatter: (p: { value: [string, number | null, number, number] }) => {
        const [day, pct, valid, expected] = p.value
        if (pct === null) return `${day}<br/>${t('calendar.noCoverage')}`
        const minutes =
          expected !== undefined && valid !== undefined && expected > 0
            ? `<br/>${t('common.validOfExpected', { valid: formatInt(valid, lc.value), expected: formatInt(expected, lc.value) })}`
            : ''
        return `${day}<br/><b>${formatPct(pct, lc.value)}</b>${minutes}`
      },
    },
    visualMap: {
      type: 'piecewise',
      orient: 'horizontal',
      left: 'center',
      bottom: 0,
      textStyle: { color: token('muted') },
      pieces: [
        { gte: good, label: `≥ ${good} %`, color: token('good') },
        { gte: warning, lt: good, label: `${warning}–${good} %`, color: token('warn') },
        { lt: warning, label: `< ${warning} %`, color: token('bad') },
      ],
      dimension: 1,
    },
    calendar: {
      range: range.value,
      top: 30,
      left: 40,
      right: 10,
      bottom: 50,
      cellSize: narrow.value ? ['auto', 28] : ['auto', 14],
      splitLine: { lineStyle: { color: token('border') } },
      itemStyle: { color: token('panel-2'), borderColor: token('bg'), borderWidth: 2 },
      dayLabel: { color: token('muted'), firstDay: 1, nameMap: lc.value === 'id' ? ID_DAYS : 'EN' },
      monthLabel: { color: token('muted'), nameMap: lc.value === 'id' ? ID_MONTHS : 'EN' },
      yearLabel: { show: false },
    },
    series: [
      {
        type: 'heatmap',
        coordinateSystem: 'calendar',
        data: days.filter((d) => d.pct !== null).map((d) => [d.day, d.pct, d.valid, d.expected]),
      },
    ],
  }
})

function onClick(p: unknown) {
  const v = (p as { value?: [string] }).value
  if (v?.[0]) emit('day', v[0])
}
</script>

<template>
  <section class="panel" :aria-label="t('calendar.title')">
    <div class="mb-2 flex flex-wrap items-center justify-between gap-2">
      <h2 class="label">{{ t('calendar.title') }}</h2>
      <div class="flex flex-wrap items-center gap-2">
        <select v-model="metric" class="input" :aria-label="t('calendar.metric')">
          <option value="sla">{{ t('calendar.sla') }}</option>
          <option value="ola">{{ t('calendar.ola') }}</option>
          <option v-for="c in cdps" :key="c" :value="`cdp:${c}`">{{ t('calendar.cdp', { cdp: c }) }}</option>
        </select>
        <select v-if="narrow" v-model.number="month" class="input" :aria-label="t('calendar.month')">
          <option v-for="m in 12" :key="m" :value="m - 1">
            {{
              new Intl.DateTimeFormat(lc === 'id' ? 'id-ID' : 'en-GB', {
                month: 'short',
                timeZone: 'UTC',
              }).format(new Date(Date.UTC(2026, m - 1, 1)))
            }}
          </option>
        </select>
        <select v-model.number="year" class="input" :aria-label="t('calendar.year')">
          <option v-for="y in years" :key="y" :value="y">{{ y }}</option>
        </select>
      </div>
    </div>
    <p v-if="loader.error.value" class="text-sm text-warn" role="alert">
      {{ t('common.error') }}
      <button type="button" class="btn-ghost" @click="loader.load()">{{ t('common.retry') }}</button>
    </p>
    <div :class="loader.loading.value ? 'opacity-50' : ''">
      <EChart
        :option="option"
        :height="narrow ? '290px' : '210px'"
        :label="t('calendar.title')"
        @click="onClick"
      />
    </div>
  </section>
</template>
