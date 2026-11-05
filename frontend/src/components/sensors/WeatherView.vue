<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { SeriesField, WeatherRow } from '@/api/types'
import type { ChartWindow } from '@/utils/time'
import { describeWeather, duration } from '@/utils/weather'
import RowsRibbon from './RowsRibbon.vue'

// Present weather: one row per kind of weather (darker = heavier), then the codes seen, in plain words.
const props = defineProps<{ field: SeriesField; window: ChartWindow }>()
const { t, te } = useI18n()
const COLOR: Record<WeatherRow, string> = {
  thunderstorm: '#7c6cf0',
  rain: 'var(--s-accent)',
  drizzle: '#5aa9e6',
  mist_fog: '#8a94a6',
  haze: 'var(--s-warn)',
  other: '#9aa3b2',
}
const describe = (code: string) => (code ? `${code} · ${describeWeather(code, t, te)}` : t('wx.none'))
const rows = computed(() =>
  (props.field.weather?.rows ?? [])
    .filter((r) => r.minutes > 0 || r.key !== 'other')
    .map((r) => ({
      key: r.key,
      label: t(`wx.row.${r.key}`),
      color: COLOR[r.key],
      minutes: r.minutes ? duration(r.minutes, t) : '—',
      segments: r.segments,
    })),
)
const codes = computed(() => (props.field.text?.counts ?? []).filter((c) => c.value !== '').slice(0, 8))
</script>

<template>
  <div class="flex flex-col gap-3">
    <p v-if="!field.weather?.weather_minutes" class="text-xs text-ink-3">{{ t('wx.noneInWindow') }}</p>
    <RowsRibbon :rows="rows" :window="window" :describe="describe" :label="t('wx.title')" />
    <ul v-if="codes.length" class="flex flex-wrap gap-x-4 gap-y-1 text-xs">
      <li v-for="c in codes" :key="c.value">
        <span class="num font-medium">{{ c.value }}</span>
        <span class="ml-1 text-ink-2">{{ describeWeather(c.value, t, te) }}</span>
        <span class="num ml-1 text-ink-3">· {{ duration(c.minutes, t) }}</span>
      </li>
    </ul>
  </div>
</template>
