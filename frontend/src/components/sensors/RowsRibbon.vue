<script setup lang="ts">
import { computed } from 'vue'
import type { Segment } from '@/api/types'
import type { ChartWindow } from '@/utils/time'

// Rows of time segments over the chart window (present weather, lightning). Darker = heavier or closer.
export interface RibbonRow {
  key: string
  label: string
  color: string
  minutes: string
  segments: Segment[]
}
const props = defineProps<{
  rows: RibbonRow[]
  window: ChartWindow
  describe: (code: string) => string
  label: string
}>()
const from = computed(() => props.window.from.getTime())
const span = computed(() => Math.max(1, props.window.to.getTime() - from.value))
const OPACITY = [0, 0.45, 0.75, 1]
const hhmm = (ms: number) => {
  const d = new Date(ms).toISOString()
  return span.value > 86_400_000 ? `${d.slice(8, 10)}/${d.slice(5, 7)} ${d.slice(11, 16)}` : d.slice(11, 16)
}
const place = (s: Segment) => {
  const a = Math.max(from.value, s[0])
  const b = Math.min(from.value + span.value, s[1])
  return {
    left: `${((a - from.value) / span.value) * 100}%`,
    width: `${Math.max(0.25, ((b - a) / span.value) * 100)}%`,
  }
}
</script>

<template>
  <div class="flex flex-col gap-1.5" role="group" :aria-label="label">
    <div
      v-for="r in rows"
      :key="r.key"
      class="grid grid-cols-[7.5rem_minmax(0,1fr)_4.5rem] items-center gap-2 text-xs"
    >
      <span class="truncate text-ink-2">{{ r.label }}</span>
      <div class="relative h-4 overflow-hidden rounded bg-sunken">
        <span
          v-for="(s, i) in r.segments"
          :key="i"
          class="absolute inset-y-0"
          :style="{ ...place(s), background: r.color, opacity: OPACITY[s[2]] ?? 1 }"
          :title="`${describe(s[3])} · ${hhmm(s[0])}–${hhmm(s[1])} UTC`"
        />
      </div>
      <span class="num text-right text-ink-3">{{ r.minutes }}</span>
    </div>
    <div class="num grid grid-cols-[7.5rem_minmax(0,1fr)_4.5rem] gap-2 text-[0.625rem] text-ink-3">
      <span /><span class="flex justify-between"
        ><span>{{ hhmm(from) }}</span
        ><span>{{ hhmm(from + span) }} UTC</span></span
      ><span />
    </div>
  </div>
</template>
