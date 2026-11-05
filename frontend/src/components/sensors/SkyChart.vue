<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { CloudBand, Cover, SeriesField } from '@/api/types'
import type { Locale } from '@/i18n'
import { int, num } from '@/utils/format'
import { formatUtc, type ChartWindow } from '@/utils/time'

// Sky condition: each cloud layer drawn at its height over time, darker = more of the sky covered.
// Low, middle and high bands each get a third of the height (most clouds here are low, so a plain
// height scale would squash them), then the share of time per band and the lowest ceiling.
const props = defineProps<{ field: SeriesField; window: ChartWindow }>()
const { t, locale } = useI18n()
const lc = computed(() => locale.value as Locale)
const sky = computed(() => props.field.sky!)

// Narrower drawing on phones so labels stay readable.
const narrow = ref(false)
let mq: MediaQueryList | null = null
const onMq = () => (narrow.value = !!mq?.matches)
onMounted(() => {
  mq = window.matchMedia('(max-width: 640px)')
  onMq()
  mq.addEventListener('change', onMq)
})
onUnmounted(() => mq?.removeEventListener('change', onMq))

const W = computed(() => (narrow.value ? 600 : 1000))
const H = 250
const X0 = computed(() => (narrow.value ? 78 : 70))
const X1 = computed(() => W.value - 6)
const Y0 = 6
const Y1 = 222
const COVERS: Cover[] = ['FEW', 'SCT', 'BKN', 'OVC']
const BANDS: CloudBand[] = ['low', 'middle', 'high']
const OPACITY: Record<Cover, number> = { FEW: 0.28, SCT: 0.52, BKN: 0.78, OVC: 1 }

const from = computed(() => props.window.from.getTime())
const span = computed(() => Math.max(1, props.window.to.getTime() - from.value))
const top = computed(() => {
  let m = 25_000
  for (const b of sky.value.timeline) for (const l of b.layers) m = Math.max(m, l[1] + 2_000)
  return Math.min(45_000, Math.ceil(m / 5_000) * 5_000)
})
const bands = computed(() => {
  const { low_top_ft: lo, middle_top_ft: mid } = sky.value.bands
  return [
    { key: 'low' as const, a: 0, b: lo },
    { key: 'middle' as const, a: lo, b: mid },
    { key: 'high' as const, a: mid, b: top.value },
  ]
})
const third = (Y1 - Y0) / 3
/** Height in feet -> y, each band filling a third of the chart. */
const y = (ft: number) => {
  const i = bands.value.findIndex((b) => ft < b.b)
  const b = bands.value[i < 0 ? 2 : i]!
  const f = Math.min(1, Math.max(0, (ft - b.a) / (b.b - b.a)))
  return Y1 - (Math.max(0, i < 0 ? 2 : i) + f) * third
}
const x = (ms: number) => X0.value + ((ms - from.value) / span.value) * (X1.value - X0.value)
const bw = computed(() =>
  Math.max(1.5, ((sky.value.bucket_minutes * 60_000) / span.value) * (X1.value - X0.value)),
)
const ft = (v: number) => num(v, lc.value, 0)
const columnText = (b: (typeof sky.value.timeline)[number]) =>
  b.clear
    ? t('sky.clear')
    : b.obscured
      ? `${t('sky.obscured')}${b.vv !== null ? ` · VV ${ft(b.vv)} ft` : ''}`
      : b.layers.map(([c, h, k]) => `${c} ${ft(h)} ft${k ? ` ${k}` : ''}`).join(' · ')
const hhmm = (ms: number) => {
  const d = new Date(ms).toISOString()
  return span.value > 86_400_000 ? `${d.slice(8, 10)}/${d.slice(5, 7)} ${d.slice(11, 16)}` : d.slice(11, 16)
}
const share = (n: number) => (sky.value.reported_minutes ? (n / sky.value.reported_minutes) * 100 : 0)
const bandTotal = (b: CloudBand) => COVERS.reduce((n, c) => n + sky.value.band_minutes[b][c], 0)
const pct0 = (n: number) => num(share(n), lc.value, share(n) < 10 && share(n) > 0 ? 1 : 0)
</script>

<template>
  <div class="flex flex-col gap-2">
    <ul class="flex flex-wrap gap-x-4 gap-y-1 text-[0.6875rem] text-ink-2">
      <li v-for="c in COVERS" :key="c" class="flex items-center gap-1.5">
        <span class="h-2.5 w-2.5 rounded-[2px] bg-accent" :style="{ opacity: OPACITY[c] }" />{{
          t(`sky.cover.${c}`)
        }}
      </li>
      <li class="flex items-center gap-1.5">
        <span class="h-2.5 w-2.5 rounded-[2px]" style="background: #8a94a6" />{{ t('sky.obscured') }}
      </li>
    </ul>

    <svg :viewBox="`0 0 ${W} ${H}`" class="h-auto w-full" role="img" :aria-label="t('sky.chartLabel')">
      <g v-for="(b, i) in bands" :key="b.key">
        <rect
          :x="X0"
          :y="y(b.b) + (i === 2 ? 0 : 0.5)"
          :width="X1 - X0"
          :height="third"
          :fill="i % 2 ? 'var(--s-sunken)' : 'transparent'"
        />
        <text :x="X0 - 8" :y="y(b.a) - third / 2 + 5" text-anchor="end" class="fill-ink-2 text-[13px]">
          {{ t(`sky.band.${b.key}`) }}
        </text>
        <text v-if="i > 0" :x="X0 - 8" :y="y(b.a) + 4" text-anchor="end" class="num fill-ink-3 text-[10px]">
          {{ ft(b.a) }}
        </text>
      </g>
      <text :x="X0 - 8" :y="Y0 + 10" text-anchor="end" class="num fill-ink-3 text-[10px]">
        {{ ft(top) }} ft
      </text>
      <g v-for="b in sky.timeline" :key="b.t">
        <title>{{ hhmm(b.t) }} UTC · {{ columnText(b) }}</title>
        <rect
          v-if="b.obscured"
          :x="x(b.t)"
          :y="y(b.vv ?? 500)"
          :width="bw - 0.5"
          :height="Y1 - y(b.vv ?? 500)"
          fill="#8a94a6"
          opacity="0.75"
        />
        <rect
          v-for="(l, i) in b.layers"
          :key="i"
          :x="x(b.t)"
          :y="y(l[1]) - 5"
          :width="bw - 0.5"
          height="10"
          rx="1.5"
          fill="var(--s-accent)"
          :opacity="OPACITY[l[0]]"
          :stroke="l[2] ? 'var(--s-bad)' : 'none'"
        />
        <rect :x="x(b.t)" :y="Y0" :width="bw" :height="Y1 - Y0" fill="transparent" />
      </g>
      <line :x1="X0" :x2="X1" :y1="Y1" :y2="Y1" stroke="var(--s-line-strong)" />
      <text :x="X0" :y="Y1 + 18" class="num fill-ink-3 text-[11px]">{{ hhmm(from) }}</text>
      <text :x="X1" :y="Y1 + 18" text-anchor="end" class="num fill-ink-3 text-[11px]">
        {{ hhmm(from + span) }} UTC
      </text>
    </svg>

    <div class="flex flex-col gap-1 text-xs">
      <p class="text-[0.6875rem] text-ink-3">{{ t('sky.shareTitle') }}</p>
      <div
        v-for="b in BANDS"
        :key="b"
        class="grid grid-cols-[5.5rem_minmax(0,1fr)_3.5rem] items-center gap-2"
      >
        <span class="text-ink-2">{{ t(`sky.band.${b}`) }}</span>
        <span class="flex h-2.5 overflow-hidden rounded-sm bg-sunken">
          <span
            v-for="c in COVERS"
            :key="c"
            class="h-full bg-accent"
            :style="{ width: `${share(sky.band_minutes[b][c])}%`, opacity: OPACITY[c] }"
            :title="`${t(`sky.cover.${c}`)} · ${pct0(sky.band_minutes[b][c])} %`"
          />
        </span>
        <span class="num whitespace-nowrap text-right text-ink-3">{{
          t('sky.ofTime', { p: pct0(bandTotal(b)) })
        }}</span>
      </div>
      <p class="num mt-1 text-ink-2">
        {{ t('sky.clearShare', { p: pct0(sky.clear_minutes) }) }} ·
        {{ t('sky.obscuredShare', { p: pct0(sky.obscured_minutes) }) }}
        <template v-if="sky.lowest_ceiling">
          ·
          {{
            t('sky.ceiling', {
              cover: sky.lowest_ceiling.cover,
              h: ft(sky.lowest_ceiling.height_ft),
              time: formatUtc(sky.lowest_ceiling.time),
            })
          }}
        </template>
      </p>
      <p class="text-[0.6875rem] text-ink-3">
        {{ t('sky.bandsNote', { lo: ft(sky.bands.low_top_ft), mid: ft(sky.bands.middle_top_ft) }) }} ·
        {{ t('sky.minutes', { n: int(sky.reported_minutes, lc) }) }}
      </p>
    </div>
  </div>
</template>
