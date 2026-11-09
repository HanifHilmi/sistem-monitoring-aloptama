<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import type { MatrixResponse } from '@/api/types'
import type { Locale } from '@/i18n'
import { useDisplayStore } from '@/stores/display'
import { int, LEVEL_BG, pct } from '@/utils/format'
import { dayCells, type DayCell } from '@/utils/overview'
import { boardPath } from '@/utils/paths'

// This month day by day for SLA and OLA (the board's matrix rows, by day). A day opens the board on that day;
// the days still to come are outlined, so the strip also shows how far the month has run.
const props = defineProps<{ code: string; matrix: MatrixResponse; now: Date }>()
const { t, locale } = useI18n()
const lc = computed(() => locale.value as Locale)
const display = useDisplayStore()

const rows = computed(() =>
  (['sla', 'ola'] as const).map((kind) => ({
    kind,
    name: t(`kpi.${kind}`),
    cells: dayCells(
      props.matrix,
      props.matrix.rows.find((r) => r.kind === kind),
      display.thresholds,
      props.now,
    ),
  })),
)
const dayFmt = computed(
  () =>
    new Intl.DateTimeFormat(lc.value === 'id' ? 'id-ID' : 'en-GB', {
      day: 'numeric',
      month: 'short',
      timeZone: 'UTC',
    }),
)
const dayName = (c: DayCell) => dayFmt.value.format(new Date(`${c.day}T00:00:00Z`))
function label(name: string, c: DayCell): string {
  if (c.state === 'future') return t('overview.day.future', { day: dayName(c) })
  if (c.pct === null) return t('overview.day.none', { day: dayName(c), name })
  return t(c.state === 'today' ? 'overview.day.today' : 'overview.day.done', {
    day: dayName(c),
    name,
    pct: pct(c.pct, lc.value),
    lost: int(c.lost, lc.value),
  })
}
const to = (c: DayCell) => ({ path: boardPath(props.code), query: { p: `day:${c.day}` } })
const ticks = computed(() =>
  props.matrix.buckets.map((b, i) => {
    const d = Number(b.start.slice(8, 10))
    return d === 1 || d % 5 === 0 || i === props.matrix.buckets.length - 1 ? String(d) : ''
  }),
)
const cols = computed(() => `2.25rem repeat(${props.matrix.buckets.length}, minmax(0, 1fr))`)
</script>

<template>
  <div class="flex flex-col gap-2">
    <div class="grid items-center gap-[2px]" :style="{ gridTemplateColumns: cols }">
      <template v-for="r in rows" :key="r.kind">
        <span class="text-[0.6875rem] text-ink-3" aria-hidden="true">{{ r.name }}</span>
        <template v-for="c in r.cells" :key="c.day">
          <span
            v-if="c.state === 'future'"
            class="h-3.5 rounded-[2px] border border-dashed border-line-strong"
            :title="label(r.name, c)"
            :aria-label="label(r.name, c)"
            role="img"
          />
          <RouterLink
            v-else
            :to="to(c)"
            class="h-3.5 rounded-[2px] hover:opacity-80 focus-visible:outline-2 focus-visible:outline-accent"
            :class="[
              LEVEL_BG[c.level],
              c.state === 'today' ? 'ring-2 ring-ink ring-offset-1 ring-offset-surface' : '',
            ]"
            :title="label(r.name, c)"
            :aria-label="label(r.name, c)"
            :data-testid="`strip-${r.kind}`"
          />
        </template>
      </template>
      <span aria-hidden="true" />
      <span
        v-for="(d, i) in ticks"
        :key="i"
        class="num text-center text-[0.625rem] leading-none text-ink-3"
        aria-hidden="true"
        >{{ d }}</span
      >
    </div>
    <p class="flex flex-wrap items-center gap-x-3 gap-y-1 text-[0.6875rem] text-ink-3">
      <span class="inline-flex items-center gap-1"><i class="h-2.5 w-2.5 rounded-[2px] bg-full" />100 %</span>
      <span class="inline-flex items-center gap-1"
        ><i class="h-2.5 w-2.5 rounded-[2px] bg-good" />≥ {{ display.thresholds.good }} %</span
      >
      <span class="inline-flex items-center gap-1"
        ><i class="h-2.5 w-2.5 rounded-[2px] bg-warn" />≥ {{ display.thresholds.warning }} %</span
      >
      <span class="inline-flex items-center gap-1"
        ><i class="h-2.5 w-2.5 rounded-[2px] bg-bad" />&lt; {{ display.thresholds.warning }} %</span
      >
      <span class="inline-flex items-center gap-1"
        ><i class="h-2.5 w-2.5 rounded-[2px] border border-dashed border-line-strong" />{{
          t('overview.day.notYet')
        }}</span
      >
      <span>· {{ t('overview.day.hint') }}</span>
    </p>
  </div>
</template>
