<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Flag, LightningRow, SeriesField } from '@/api/types'
import type { Locale } from '@/i18n'
import { int } from '@/utils/format'
import { formatUtc, type ChartWindow } from '@/utils/time'
import { duration } from '@/utils/weather'
import RowsRibbon from './RowsRibbon.vue'

// Lightning: how close the storm was over time, and where distant lightning was seen.
const props = defineProps<{ field: SeriesField; window: ChartWindow; flags?: Flag[] }>()
const { t, locale } = useI18n()
const lc = computed(() => locale.value as Locale)
const L = computed(() => props.field.lightning)
const COLOR: Record<LightningRow, string> = {
  airport: 'var(--s-bad)',
  vicinity: 'var(--s-warn)',
  distant: '#8a94a6',
}
const rows = computed(() =>
  (L.value?.rows ?? []).map((r) => ({
    key: r.key,
    label: t(`ltg.row.${r.key}`),
    color: COLOR[r.key],
    minutes: r.minutes ? duration(r.minutes, t) : '—',
    segments: r.segments,
  })),
)
const describe = (text: string) => text
const DIRS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
const maxDir = computed(() => Math.max(1, ...DIRS.map((d) => L.value?.directions[d] ?? 0)))
const spoke = (i: number) => {
  const a = ((i * 45 - 90) * Math.PI) / 180
  const len = 8 + (46 * (L.value?.directions[DIRS[i]!] ?? 0)) / maxDir.value
  return {
    x2: 70 + Math.cos(a) * len,
    y2: 70 + Math.sin(a) * len,
    lx: 70 + Math.cos(a) * 62,
    ly: 70 + Math.sin(a) * 62,
  }
}
</script>

<template>
  <div v-if="L" class="flex flex-col gap-3">
    <p class="text-xs text-ink-2">
      <template v-if="L.episodes">
        {{ t('ltg.episodes', { n: int(L.episodes, lc) }) }} ·
        {{ t('ltg.span', { first: formatUtc(L.first), last: formatUtc(L.last) }) }}
      </template>
      <template v-else>{{ t('ltg.none') }}</template>
    </p>
    <div class="grid gap-3 md:grid-cols-[minmax(0,1fr)_10.5rem] md:items-center">
      <RowsRibbon :rows="rows" :window="window" :describe="describe" :label="t('ltg.title')" :flags="flags" />
      <figure class="mx-auto text-center">
        <svg viewBox="0 0 160 160" class="h-40 w-40" role="img" :aria-label="t('ltg.directions')">
          <circle cx="80" cy="80" r="52" fill="none" stroke="var(--s-line-strong)" />
          <line
            v-for="(d, i) in DIRS"
            :key="d"
            x1="80"
            y1="80"
            :x2="spoke(i).x2"
            :y2="spoke(i).y2"
            stroke="var(--s-warn)"
            stroke-width="5"
            stroke-linecap="round"
          >
            <title>{{ d }} · {{ duration(L.directions[d] ?? 0, t) }}</title>
          </line>
          <text
            v-for="(d, i) in DIRS"
            :key="`l${d}`"
            :x="spoke(i).lx"
            :y="spoke(i).ly + 3"
            text-anchor="middle"
            class="fill-ink-3 text-[10px]"
          >
            {{ d }}
          </text>
        </svg>
        <figcaption class="text-[0.6875rem] text-ink-3">
          {{ t('ltg.allAround', { d: duration(L.directions.ALQDS ?? 0, t) }) }}
        </figcaption>
      </figure>
    </div>
  </div>
</template>
