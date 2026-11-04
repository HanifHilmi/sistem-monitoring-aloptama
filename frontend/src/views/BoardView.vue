<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '@/api/client'
import type { KpiResponse, MatrixResponse, MatrixRow, SystemInfo } from '@/api/types'
import AvailabilityMatrix from '@/components/AvailabilityMatrix.vue'
import DayDetail from '@/components/DayDetail.vue'
import KpiStrip, { type KpiItem } from '@/components/KpiStrip.vue'
import LossesList from '@/components/LossesList.vue'
import PeriodBar from '@/components/PeriodBar.vue'
import RowBreakdown from '@/components/RowBreakdown.vue'
import SidePanel from '@/components/SidePanel.vue'
import { useLoader } from '@/composables/useLoader'
import { usePolling } from '@/composables/usePolling'
import { usePeriodQuery } from '@/composables/useUrlState'
import type { Locale } from '@/i18n'
import { useDisplayStore } from '@/stores/display'
import { useLiveStore } from '@/stores/live'
import {
  bucketFor,
  encodePeriod,
  formatUtc,
  isOpen,
  periodContaining,
  shiftPeriod,
  type Period,
} from '@/utils/time'

const props = defineProps<{ wall?: boolean }>()
const { t, locale } = useI18n()
const lc = computed(() => locale.value as Locale)
const display = useDisplayStore()
const live = useLiveStore()
const urlPeriod = usePeriodQuery()
const period = computed<Period>({
  get: () => (props.wall ? periodContaining('month', new Date()) : urlPeriod.value),
  set: (p) => (urlPeriod.value = p),
})
const code = computed(() => live.systemCode)
const info = ref<SystemInfo | null>(null)
onMounted(async () => (info.value = await display.system(code.value)))

const bucket = computed(() => bucketFor(period.value))
const previous = computed(() => shiftPeriod(period.value, -1))
const matrix = useLoader<MatrixResponse>(() =>
  api.matrix(code.value, period.value.from, period.value.to, bucket.value),
)
const kpis = useLoader<KpiResponse>(() => api.kpis(code.value, period.value.from, period.value.to))
const prevKpis = useLoader<KpiResponse>(() => api.kpis(code.value, previous.value.from, previous.value.to))

function loadAll(silent = false) {
  void matrix.load({ silent })
  void kpis.load({ silent })
  if (!silent) void prevKpis.load()
}
watch(
  () => encodePeriod(period.value),
  () => loadAll(),
  { immediate: true },
)
usePolling(() => {
  if (isOpen(period.value) && matrix.data.value) loadAll(true)
}, 60_000)

// ---- headline figures ----------------------------------------------------------------------------
const rowByKey = computed(() => new Map((matrix.data.value?.rows ?? []).map((r) => [r.key, r])))
// Trends cover the evaluated part of the period only (an open month does not end in empty days).
function trimEnd(v: (number | null)[]): (number | null)[] {
  let n = v.length
  while (n > 0 && v[n - 1] === null) n--
  return v.slice(0, n)
}
const sparkOf = (key: string) =>
  trimEnd((rowByKey.value.get(key)?.cells ?? []).map((c) => (c.expected === 0 ? null : c.pct)))
const pooledSpark = computed(() => {
  const comps = (matrix.data.value?.rows ?? []).filter((r) => r.kind === 'component')
  const n = matrix.data.value?.buckets.length ?? 0
  return trimEnd(
    Array.from({ length: n }, (_, i) => {
      let v = 0
      let e = 0
      for (const r of comps) {
        v += r.cells[i]?.valid ?? 0
        e += r.cells[i]?.expected ?? 0
      }
      return e ? (v / e) * 100 : null
    }),
  )
})
const periodName = (p: Period) => {
  const f = (o: Intl.DateTimeFormatOptions) =>
    new Intl.DateTimeFormat(lc.value === 'id' ? 'id-ID' : 'en-GB', { timeZone: 'UTC', ...o }).format(p.from)
  if (p.kind === 'month') return f({ month: 'long', year: 'numeric' })
  if (p.kind === 'year') return String(p.from.getUTCFullYear())
  if (p.kind === 'quarter') return `Q${Math.floor(p.from.getUTCMonth() / 3) + 1} ${p.from.getUTCFullYear()}`
  return `${formatUtc(p.from).slice(0, 10)} – ${formatUtc(new Date(p.to.getTime() - 1)).slice(0, 10)}`
}
const items = computed<KpiItem[]>(() => {
  const k = kpis.data.value
  const pk = prevKpis.data.value
  const cdpItems = (k?.cdps ?? []).map((c) => ({
    key: `cdp:${c.code}`,
    label: t('kpi.uptimeOf', { cdp: c.code }),
    hint: t('kpi.uptimeHint'),
    value: c.uptime.pct,
    previous: pk?.cdps.find((x) => x.code === c.code)?.uptime.pct ?? null,
    spark: sparkOf(`cdp:${c.code}`),
    valid: c.uptime.valid,
    expected: c.uptime.expected,
  }))
  return [
    {
      key: 'sla',
      label: t('kpi.sla'),
      hint: t('kpi.slaHint'),
      value: k?.sla.pct ?? null,
      previous: pk?.sla.pct ?? null,
      spark: sparkOf('sla'),
      valid: k?.sla.valid,
      expected: k?.sla.expected,
    },
    {
      key: 'ola',
      label: t('kpi.ola'),
      hint: t('kpi.olaHint'),
      value: k?.ola.pct ?? null,
      previous: pk?.ola.pct ?? null,
      spark: sparkOf('ola'),
    },
    ...cdpItems,
    {
      key: 'pooled',
      label: t('kpi.pooled'),
      hint: t('kpi.pooledHint'),
      value: k?.pooled.pct ?? null,
      previous: pk?.pooled.pct ?? null,
      spark: pooledSpark.value,
      valid: k?.pooled.valid,
      expected: k?.pooled.expected,
    },
  ]
})

// ---- drill-down panel ----------------------------------------------------------------------------
type Panel =
  | { kind: 'day'; row: MatrixRow; day: string }
  | { kind: 'group'; row: MatrixRow; col: number }
  | { kind: 'row'; row: MatrixRow }
  | { kind: 'sub'; row: MatrixRow; col: number }
const panel = ref<Panel | null>(null)
const subMatrix = useLoader<MatrixResponse>(async () => {
  const p = panel.value
  const b = p && p.kind === 'sub' ? matrix.data.value?.buckets[p.col] : undefined
  if (!b) throw new Error('no bucket')
  return api.matrix(code.value, new Date(`${b.start}T00:00:00Z`), new Date(`${b.end}T00:00:00Z`), 'day')
})

function siteName(slug?: string) {
  return info.value?.sites.find((s) => s.slug === slug)?.name[lc.value] ?? slug ?? ''
}
function rowName(r: MatrixRow): string {
  if (r.kind === 'sla') return t('kpi.sla')
  if (r.kind === 'ola') return t('kpi.ola')
  if (r.kind === 'cdp') return r.cdp ?? ''
  if (r.kind === 'site') return siteName(r.site)
  const comp = info.value?.sites.find((s) => s.slug === r.site)?.components.find((c) => c.type === r.type)
  return `${siteName(r.site)} · ${comp?.name[lc.value] ?? r.type}`
}
function compName(r: MatrixRow): string {
  const comp = info.value?.sites.find((s) => s.slug === r.site)?.components.find((c) => c.type === r.type)
  return comp?.name[lc.value] ?? r.type ?? ''
}
function colName(m: MatrixResponse | null | undefined, i: number): string {
  const b = m?.buckets[i]
  if (!b) return ''
  const fmt = new Intl.DateTimeFormat(lc.value === 'id' ? 'id-ID' : 'en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  })
  const start = fmt.format(new Date(`${b.start}T00:00:00Z`))
  if (m?.bucket === 'day') return start
  return `${start} – ${fmt.format(new Date(new Date(`${b.end}T00:00:00Z`).getTime() - 86_400_000))}`
}
const scopeOf = (r: MatrixRow) =>
  r.kind === 'component' ? `component:${r.site}:${r.type}` : r.kind === 'cdp' ? `cdp:${r.cdp}` : 'sla'

function openCell(r: MatrixRow, col: number, source: MatrixResponse | null = matrix.data.value) {
  if (!source) return
  if (r.kind === 'site' || r.kind === 'ola') {
    panel.value = { kind: 'group', row: r, col }
    return
  }
  if (source.bucket === 'day') {
    const day = source.buckets[col]?.start
    if (day) panel.value = { kind: 'day', row: r, day }
    return
  }
  panel.value = { kind: 'sub', row: r, col }
  void subMatrix.load()
}

const groupRows = computed(() => {
  const p = panel.value
  const rows = matrix.data.value?.rows ?? []
  if (!p || p.kind !== 'group') return []
  const members =
    p.row.kind === 'ola'
      ? rows.filter((r) => r.kind === 'site')
      : rows.filter((r) => r.kind === 'component' && r.site === p.row.site)
  // Inside one site the site name is already in the panel title: list components by name only.
  return members.map((row) => ({
    row,
    label: p.row.kind === 'site' ? compName(row) : rowName(row),
  }))
})

const panelTitle = computed(() => {
  const p = panel.value
  if (!p) return ''
  if (p.kind === 'day')
    return `${rowName(p.row)} · ${colName({ bucket: 'day', buckets: [{ start: p.day, end: p.day }] } as MatrixResponse, 0)}`
  if (p.kind === 'row') return `${rowName(p.row)} · ${periodName(period.value)}`
  return `${rowName(p.row)} · ${colName(matrix.data.value, p.col)}`
})
const siteLink = computed(() => {
  const p = panel.value
  if (!p || p.kind !== 'day' || p.row.kind !== 'component') return null
  const from = new Date(`${p.day}T00:00:00Z`)
  const to = new Date(from.getTime() + 86_400_000)
  return `/sites/${p.row.site}?w=custom:${from.toISOString()}~${to.toISOString()}`
})
const levelsLegend = computed(() => {
  const { good, warning } = display.thresholds
  return [
    { cls: 'bg-full', label: '100 %' },
    { cls: 'bg-good', label: `≥ ${good} %` },
    { cls: 'bg-warn', label: `${warning}–${good} %` },
    { cls: 'bg-bad', label: `< ${warning} %` },
    { cls: 'bg-empty border border-line', label: t('board.noCoverage') },
  ]
})
</script>

<template>
  <div class="flex flex-col gap-4">
    <header class="flex flex-wrap items-end justify-between gap-3">
      <div class="min-w-0">
        <p v-if="!wall" class="eyebrow">{{ info?.name[lc] ?? '' }}</p>
        <h1 class="text-lg font-semibold">
          {{ t('board.title') }}
          <span class="font-normal text-ink-2">· {{ periodName(period) }}</span>
        </h1>
        <p class="num text-[0.6875rem] text-ink-3">
          <template v-if="kpis.data.value?.period.open">{{
            t('board.soFar', { time: formatUtc(kpis.data.value.period.as_of) })
          }}</template>
          <template v-else-if="kpis.data.value">{{ t('board.closed') }}</template>
        </p>
      </div>
      <PeriodBar v-if="!wall" v-model="period" />
    </header>

    <p
      v-if="matrix.error.value || kpis.error.value"
      class="rounded-md border border-warn/40 bg-warn/10 px-3 py-2 text-sm text-warn"
      role="alert"
    >
      {{ t('common.error') }}
      <button type="button" class="icon-btn ml-2" @click="loadAll()">{{ t('common.retry') }}</button>
    </p>

    <KpiStrip :items="items" :previous-label="periodName(previous)" :loading="kpis.loading.value" />

    <div class="grid gap-4 lg:grid-cols-[minmax(0,1fr)_16rem]">
      <section
        class="min-w-0 rounded-lg border border-line bg-surface p-3 sm:p-4"
        :class="matrix.loading.value ? 'opacity-60' : ''"
      >
        <div
          v-if="!matrix.data.value || !info"
          class="h-96 animate-pulse rounded-md bg-sunken"
          aria-busy="true"
        />
        <AvailabilityMatrix
          v-else
          :matrix="matrix.data.value"
          :info="info"
          :selected="panel && 'col' in panel ? { row: panel.row.key, col: panel.col } : null"
          @cell="(r, i) => openCell(r, i)"
          @row="(r) => (panel = { kind: 'row', row: r })"
        />
        <div
          class="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-line pt-2 text-[0.6875rem] text-ink-2"
        >
          <span v-for="l in levelsLegend" :key="l.label" class="flex items-center gap-1.5">
            <span class="h-2.5 w-2.5 rounded-[2px]" :class="l.cls" />{{ l.label }}
          </span>
          <span class="ml-auto text-ink-3">{{ t('board.legendNote') }}</span>
        </div>
      </section>

      <aside class="flex flex-col gap-4">
        <div class="rounded-lg border border-line bg-surface p-3">
          <LossesList
            v-if="matrix.data.value && info"
            :rows="matrix.data.value.rows"
            :info="info"
            :limit="wall ? 6 : 8"
            @pick="(r) => (panel = { kind: 'row', row: r })"
          />
        </div>
        <div v-if="!wall" class="flex flex-col gap-2 px-1 text-[0.6875rem] text-ink-3">
          <dl class="contents">
            <div>
              <dt class="inline font-medium text-ink-2">{{ t('kpi.sla') }}:</dt>
              <dd class="ml-1 inline">{{ t('kpi.slaHint') }}</dd>
            </div>
            <div>
              <dt class="inline font-medium text-ink-2">{{ t('kpi.ola') }}:</dt>
              <dd class="ml-1 inline">{{ t('kpi.olaHint') }}</dd>
            </div>
          </dl>
          <p>{{ t('board.thresholdNote') }}</p>
        </div>
      </aside>
    </div>

    <SidePanel
      :open="!!panel"
      :title="panelTitle"
      :subtitle="panel?.kind === 'day' ? t('day.subtitle') : undefined"
      @close="panel = null"
    >
      <template v-if="panel">
        <DayDetail
          v-if="panel.kind === 'day'"
          :system-code="code"
          :scope="scopeOf(panel.row)"
          :day="panel.day"
          :site-link="siteLink"
        />
        <RowBreakdown
          v-else-if="panel.kind === 'group' && matrix.data.value"
          :matrix="matrix.data.value"
          :rows="groupRows"
          :col="panel.col"
          :col-label="(i) => colName(matrix.data.value, i)"
          @pick="(r, i) => openCell(r, i)"
        />
        <RowBreakdown
          v-else-if="panel.kind === 'row' && matrix.data.value"
          :matrix="matrix.data.value"
          :rows="[{ row: panel.row, label: rowName(panel.row) }]"
          :col-label="(i) => colName(matrix.data.value, i)"
          @pick="(r, i) => openCell(r, i)"
        />
        <template v-else-if="panel.kind === 'sub'">
          <div
            v-if="!subMatrix.data.value"
            class="h-40 animate-pulse rounded-md bg-sunken"
            aria-busy="true"
          />
          <RowBreakdown
            v-else
            :matrix="subMatrix.data.value"
            :rows="
              subMatrix.data.value.rows
                .filter((r) => r.key === panel?.row.key)
                .map((row) => ({ row, label: rowName(row) }))
            "
            :col-label="(i) => colName(subMatrix.data.value, i)"
            @pick="(r, i) => openCell(r, i, subMatrix.data.value)"
          />
        </template>
      </template>
    </SidePanel>
  </div>
</template>
