<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { MatrixResponse, MatrixRow, SystemInfo } from '@/api/types'
import type { Locale } from '@/i18n'
import { useDisplayStore } from '@/stores/display'
import { figureLevel, int, LEVEL_BG, LEVEL_ON, LEVEL_TEXT, matrixLost, pct } from '@/utils/format'
import { isoWeek } from '@/utils/time'

const props = defineProps<{
  matrix: MatrixResponse
  info: SystemInfo
  selected?: { row: string; col: number } | null
}>()
const emit = defineEmits<{ cell: [MatrixRow, number]; row: [MatrixRow] }>()
const { t, locale } = useI18n()
const lc = computed(() => locale.value as Locale)
const display = useDisplayStore()

interface Group {
  key: string
  label: string
  rows: MatrixRow[]
}

const groups = computed<Group[]>(() => {
  const rows = props.matrix.rows
  const byKey = new Map(rows.map((r) => [r.key, r]))
  const system: MatrixRow[] = ['sla', 'ola'].map((k) => byKey.get(k)).filter((r): r is MatrixRow => !!r)
  system.push(...rows.filter((r) => r.kind === 'cdp'))
  const out: Group[] = [{ key: 'system', label: t('board.system'), rows: system }]
  for (const site of props.info.sites) {
    out.push({
      key: site.slug,
      label: site.name[lc.value],
      rows: rows.filter(
        (r) => r.key === `site:${site.slug}` || (r.kind === 'component' && r.site === site.slug),
      ),
    })
  }
  return out
})

const cols = computed(() => props.matrix.buckets.length)
// Week and month cells are wide enough to carry their figure, which colour alone cannot show near 100 %.
const withValues = computed(() => props.matrix.bucket !== 'day')

function colLabel(i: number): string {
  const b = props.matrix.buckets[i]
  if (!b) return ''
  const d = new Date(`${b.start}T00:00:00Z`)
  if (props.matrix.bucket === 'day') return String(d.getUTCDate())
  if (props.matrix.bucket === 'week') return `W${isoWeek(d)}`
  return new Intl.DateTimeFormat(lc.value === 'id' ? 'id-ID' : 'en-GB', {
    month: 'short',
    timeZone: 'UTC',
  }).format(d)
}

function colTitle(i: number): string {
  const b = props.matrix.buckets[i]
  if (!b) return ''
  const fmt = new Intl.DateTimeFormat(lc.value === 'id' ? 'id-ID' : 'en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  })
  const start = new Date(`${b.start}T00:00:00Z`)
  if (props.matrix.bucket === 'day') return fmt.format(start)
  const end = new Date(new Date(`${b.end}T00:00:00Z`).getTime() - 86_400_000)
  return `${fmt.format(start)} – ${fmt.format(end)}`
}

function milestone(i: number): boolean {
  if (props.matrix.bucket !== 'day') return true
  return i === 0 || (i + 1) % 5 === 0
}

function rowLabel(r: MatrixRow): string {
  if (r.kind === 'sla') return t('kpi.sla')
  if (r.kind === 'ola') return t('kpi.ola')
  if (r.kind === 'cdp') return r.cdp ?? ''
  if (r.kind === 'site') return t('board.siteTotal')
  return r.type ?? ''
}

function rowTitle(r: MatrixRow): string {
  if (r.kind === 'component') {
    const site = props.info.sites.find((s) => s.slug === r.site)
    const comp = site?.components.find((c) => c.type === r.type)
    return comp ? `${site?.name[lc.value]} · ${comp.name[lc.value]}` : rowLabel(r)
  }
  if (r.kind === 'sla') return t('kpi.slaHint')
  if (r.kind === 'ola') return t('kpi.olaHint')
  if (r.kind === 'cdp') return t('kpi.uptimeHint')
  return rowLabel(r)
}

// A cell that lost any minute is never 'full', even when it rounds to 100.00.
const lv = (r: MatrixRow, i: number) =>
  figureLevel(r.cells[i], display.thresholds, matrixLost(props.matrix.rows, r, i))
const totalLv = (r: MatrixRow) =>
  figureLevel(r.total, display.thresholds, matrixLost(props.matrix.rows, r, 'total'))

// ---- tooltip ---------------------------------------------------------------------------------
const wrap = ref<HTMLElement | null>(null)
const tip = ref<{ x: number; y: number; title: string; lines: string[] } | null>(null)

function showTip(e: Event, r: MatrixRow, i: number) {
  const el = e.currentTarget as HTMLElement
  const box = wrap.value?.getBoundingClientRect()
  const rect = el.getBoundingClientRect()
  if (!box) return
  const c = r.cells[i]
  const lines: string[] = []
  if (!c || c.pct === null || c.expected === 0) lines.push(t('board.noCoverage'))
  else {
    lines.push(`${pct(c.pct, lc.value)} %`)
    if (c.expected !== undefined) {
      lines.push(
        t('common.validOfExpected', { valid: int(c.valid, lc.value), expected: int(c.expected, lc.value) }),
      )
      if (c.missing) lines.push(t('board.missing', { n: int(c.missing, lc.value) }))
    }
  }
  tip.value = {
    x: Math.min(rect.left - box.left + rect.width / 2, box.width - 110),
    y: rect.top - box.top,
    title: `${rowTitle(r)} · ${colTitle(i)}`,
    lines,
  }
}
</script>

<template>
  <div ref="wrap" class="relative overflow-x-auto" @mouseleave="tip = null">
    <div
      class="matrix-grid grid items-center gap-x-px gap-y-px"
      :style="{ '--n': cols }"
      role="grid"
      :aria-rowcount="matrix.rows.length + 1"
      :aria-colcount="cols + 3"
      :aria-label="t('board.matrix')"
    >
      <!-- header -->
      <div role="row" class="contents">
        <div role="columnheader" class="sticky left-0 z-[1] bg-surface pb-1 text-[0.625rem] text-ink-3">
          {{ t(`board.bucket.${matrix.bucket}`) }}
        </div>
        <div
          v-for="i in cols"
          :key="i"
          role="columnheader"
          class="num pb-1 text-center text-[0.625rem] text-ink-3"
          :class="milestone(i - 1) ? '' : 'max-md:invisible'"
          :title="colTitle(i - 1)"
        >
          {{ colLabel(i - 1) }}
        </div>
        <div role="columnheader" class="pb-1 pl-2 text-right text-[0.625rem] text-ink-3">%</div>
        <div role="columnheader" class="pb-1 pl-2 text-right text-[0.625rem] text-ink-3 max-sm:hidden">
          {{ t('board.minLost') }}
        </div>
      </div>

      <template v-for="g in groups" :key="g.key">
        <div class="col-span-full mt-2.5 mb-0.5 flex items-center gap-2 first:mt-0" role="row">
          <span class="eyebrow sticky left-0 bg-surface pr-1" role="rowheader">{{ g.label }}</span>
          <span class="h-px flex-1 bg-line" aria-hidden="true" />
        </div>
        <div v-for="r in g.rows" :key="r.key" role="row" class="group contents">
          <button
            type="button"
            role="rowheader"
            class="sticky left-0 z-[1] truncate bg-surface pr-2 text-left text-xs hover:text-accent"
            :class="
              r.kind === 'site' || r.kind === 'sla' || r.kind === 'ola'
                ? 'font-semibold'
                : r.kind === 'component'
                  ? 'pl-2 text-ink-2'
                  : ''
            "
            :title="rowTitle(r)"
            @click="emit('row', r)"
          >
            {{ rowLabel(r) }}
          </button>
          <button
            v-for="(c, i) in r.cells"
            :key="i"
            type="button"
            role="gridcell"
            class="flex h-4 w-full items-center justify-center rounded-[2px] transition-transform hover:z-10"
            :class="[
              LEVEL_BG[lv(r, i)],
              withValues ? 'hover:ring-2 hover:ring-ink-2' : 'hover:scale-125',
              selected && selected.row === r.key && selected.col === i
                ? 'ring-2 ring-accent ring-offset-1 ring-offset-bg'
                : '',
            ]"
            :aria-label="`${rowTitle(r)} · ${colTitle(i)} · ${c.pct === null ? t('board.noCoverage') : pct(c.pct, lc) + ' %'}`"
            @mouseenter="showTip($event, r, i)"
            @focus="showTip($event, r, i)"
            @blur="tip = null"
            @click="emit('cell', r, i)"
          >
            <span
              v-if="withValues && lv(r, i) !== 'none'"
              class="num text-[0.625rem] leading-none max-md:hidden"
              :class="LEVEL_ON[lv(r, i)]"
              aria-hidden="true"
              >{{ pct(c.pct, lc) }}</span
            >
          </button>
          <span
            class="num pl-2 text-right text-xs"
            :class="[LEVEL_TEXT[totalLv(r)], r.kind === 'site' || r.kind === 'sla' ? 'font-semibold' : '']"
          >
            {{ pct(r.total.pct, lc) }}
          </span>
          <span class="num pl-2 text-right text-xs text-ink-3 max-sm:hidden">
            {{ r.total.missing === undefined ? '' : r.total.missing === 0 ? '·' : int(r.total.missing, lc) }}
          </span>
        </div>
      </template>
    </div>

    <div
      v-if="tip"
      class="pointer-events-none absolute z-20 w-56 -translate-x-1/2 -translate-y-full rounded-md border border-line-strong bg-surface px-2.5 py-1.5 text-xs shadow-lg"
      :style="{ left: `${tip.x}px`, top: `${tip.y - 6}px` }"
      role="tooltip"
    >
      <p class="font-medium">{{ tip.title }}</p>
      <p v-for="(l, i) in tip.lines" :key="i" class="num text-ink-2">{{ l }}</p>
    </div>
  </div>
</template>

<style scoped>
/* Cells share the free width. On phones the whole period still fits (no sideways scroll), the
   minutes-lost column is dropped, and tapping a row label opens a tap-friendly list of its cells. */
.matrix-grid {
  grid-template-columns: minmax(3.6rem, 5rem) repeat(var(--n), minmax(0, 1fr)) minmax(2.9rem, auto);
}
@media (width >= 40rem) {
  .matrix-grid {
    grid-template-columns:
      minmax(4.25rem, 8.5rem) repeat(var(--n), minmax(0.85rem, 1fr)) minmax(3.6rem, auto)
      minmax(3.4rem, auto);
  }
}
</style>
