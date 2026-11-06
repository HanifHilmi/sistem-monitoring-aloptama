<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '@/api/client'
import type {
  Assets,
  ComponentInfo,
  Detection,
  FieldInfo,
  Flag,
  SeriesField,
  SeriesResponse,
} from '@/api/types'
import { useLoader } from '@/composables/useLoader'
import type { Locale } from '@/i18n'
import { useAuthStore } from '@/stores/auth'
import { useDisplayStore } from '@/stores/display'
import { formatDuration, formatRange } from '@/utils/flags'
import { figureLevel, int, LEVEL_TEXT, num, pct } from '@/utils/format'
import type { ChartWindow } from '@/utils/time'
import DetectionList from './detections/DetectionList.vue'
import FieldChart from './FieldChart.vue'
import FlagList from './flags/FlagList.vue'
import CalibrationChip from './records/CalibrationChip.vue'
import GustPanel from './sensors/GustPanel.vue'
import LightningView from './sensors/LightningView.vue'
import SkyChart from './sensors/SkyChart.vue'
import WeatherView from './sensors/WeatherView.vue'
import Sparkline from './Sparkline.vue'
import StatusPill from './StatusPill.vue'
import WindRose from './WindRose.vue'

// One component as a compact table: one row per field (latest, trend, min, max, mean); a row expands to a chart.
const props = defineProps<{
  systemCode: string
  siteSlug: string
  component: ComponentInfo
  fields: Record<string, FieldInfo>
  window: ChartWindow
  status: string
  refreshKey: number
  /** R2.5: the sensor's record and calibration status */
  record?: Assets['components'][number]
}>()
const emit = defineEmits<{
  /** an Admin picked a range to flag on this component */
  flag: [range: { start: string; end: string }]
  editFlag: [id: number]
}>()
const { t, locale } = useI18n()
const lc = computed(() => locale.value as Locale)
const display = useDisplayStore()
const auth = useAuthStore()
const open = ref<string | null>(null)
const details = ref(false)

const loader = useLoader<SeriesResponse>(() =>
  api.series(props.systemCode, props.siteSlug, props.component.type, props.window.from, props.window.to),
)
watch(
  () => [props.window.from.getTime(), props.window.to.getTime()],
  () => loader.load(),
  { immediate: true },
)
watch(
  () => props.refreshKey,
  () => loader.load({ silent: true }),
)

// ---- flags in the window (R2.3) -------------------------------------------------------------------
const flagLoader = useLoader<Flag[]>(() =>
  api.flags(
    props.systemCode,
    props.window.from,
    props.window.to,
    `component:${props.siteSlug}:${props.component.type}`,
  ),
)
watch(
  () => [props.window.from.getTime(), props.window.to.getTime(), props.refreshKey],
  () => flagLoader.load({ silent: true }),
  { immediate: true },
)
const flags = computed(() => flagLoader.data.value ?? [])

// ---- detections in the window (R2.4): confirmed for everyone, suspect and rejected for signed-in users ----
const detLoader = useLoader<Detection[]>(() =>
  api.detections(
    props.systemCode,
    props.window.from,
    props.window.to,
    `component:${props.siteSlug}:${props.component.type}`,
  ),
)
watch(
  () => [props.window.from.getTime(), props.window.to.getTime(), props.refreshKey],
  () => detLoader.load({ silent: true }),
  { immediate: true },
)
const detections = computed(() => detLoader.data.value ?? [])
const fieldDetections = (code: string) => detections.value.filter((d) => d.field === code)
const suspects = computed(() => detections.value.filter((d) => d.status === 'suspect').length)
const confirmed = computed(() => detections.value.filter((d) => d.status === 'confirmed').length)

// ---- sensor details (R2.5): what is on record; serial and part numbers only for signed-in users ----
const detailRows = computed(() => {
  const r = props.record
  if (!r) return []
  const m = r.meta
  const rows: { key: string; value: string }[] = [
    { key: 'sensor_type', value: m.sensor_type ?? '—' },
    { key: 'model', value: [m.manufacturer, m.model].filter(Boolean).join(' ') || '—' },
    { key: 'installed_on', value: m.installed_on ?? '—' },
    { key: 'last_calibration', value: r.calibration.last ?? '—' },
    ...(r.calibration.last
      ? [{ key: 'validated_on', value: r.calibration.validated_on ?? t('calibration.pendingShort') }]
      : []),
    { key: 'next_due', value: r.calibration.next_due ?? '—' },
  ]
  if (m.firmware) rows.push({ key: 'firmware', value: m.firmware })
  if (m.serial_number !== undefined) rows.push({ key: 'serial_number', value: m.serial_number ?? '—' })
  if (m.part_number !== undefined) rows.push({ key: 'part_number', value: m.part_number ?? '—' })
  return rows
})
const selecting = ref(false)
const selection = ref<[number, number] | null>(null)
watch(open, () => {
  selecting.value = false
  selection.value = null
})
const iso = (ms: number) => new Date(ms).toISOString()
const selectionText = computed(() =>
  selection.value
    ? `${formatRange(iso(selection.value[0]), iso(selection.value[1]), lc.value)} UTC · ${formatDuration(
        (selection.value[1] - selection.value[0]) / 60_000,
        t,
      )}`
    : '',
)
/** Charts without drag-select (sky, weather, lightning) start from the whole window; the form adjusts it. */
const draggable = (f: SeriesField) => !f.sky && !f.weather && !f.lightning
function startFlag(f: SeriesField) {
  if (draggable(f)) {
    selecting.value = true
    return
  }
  const end = Math.min(props.window.to.getTime(), Math.floor(Date.now() / 60_000) * 60_000)
  emit('flag', { start: iso(Math.floor(props.window.from.getTime() / 60_000) * 60_000), end: iso(end) })
}
function confirmFlag() {
  if (!selection.value) return
  emit('flag', { start: iso(selection.value[0]), end: iso(selection.value[1]) })
  selecting.value = false
  selection.value = null
}

const DIGITS: Record<string, number> = { '°C': 1, hPa: 1, mm: 1 }
const fmt = (v: number | string | null | undefined, unit: string | null) =>
  typeof v === 'string' ? v : num(v ?? null, lc.value, DIGITS[unit ?? ''] ?? 0, true)
// A unit such as "100 ft" is a multiplier: show it as "×100 ft" so "12 ×100 ft" is not read as "12100 ft".
const unitLabel = (u: string | null) => (u && /^\d/.test(u) ? `×${u}` : (u ?? ''))
// The latest value is older than the end of the window by more than a few minutes: show its time in amber.
const STALE_MS = 5 * 60_000
const stale = (f: SeriesField) => {
  const last = f.stats.last?.time
  const end = Math.min(props.window.to.getTime(), Date.now())
  return !last || end - Date.parse(last) > STALE_MS
}
const name = (code: string) => props.fields[code]?.name[lc.value] ?? code
const hhmm = (iso?: string | null) => (iso ? iso.slice(11, 16) : '')
const textLabel = (v: string | null | undefined) =>
  v === null || v === undefined ? '—' : v === '' ? t('sensor.noEvent') : v
const topState = (f: SeriesField) => f.text?.counts.find((c) => c.value !== '') ?? null
const avail = computed(() => loader.data.value?.availability)
// Gust speed and direction are shown as gust events under the table, not as rows.
const rows = computed(() => (loader.data.value?.fields ?? []).filter((f) => f.chart !== 'gust'))
// Cloud base 0 means no cloud detected.
const noCloud = (f: SeriesField) => f.stats.zero_minutes !== undefined && f.stats.last?.value === 0
</script>

<template>
  <section class="overflow-hidden rounded-lg border border-line bg-surface" :aria-label="component.name[lc]">
    <header class="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line px-3 py-2">
      <h3 class="text-sm font-semibold">{{ component.name[lc] }}</h3>
      <span class="num text-[0.6875rem] text-ink-3">{{ component.type }}</span>
      <StatusPill :status="status" />
      <span
        v-if="flags.length"
        class="inline-flex items-center gap-1 rounded-full border border-flag/50 bg-flag/10 px-2 py-px text-[0.6875rem] text-flag"
        :title="flags.map((f) => t(`flags.reason.${f.reason}`)).join(', ')"
        data-testid="flag-chip"
      >
        <span class="flag-hatch h-2 w-2 rounded-[1px]" aria-hidden="true" />
        {{ t('flags.chip', { n: flags.length }, flags.length) }}
      </span>
      <span
        v-if="suspects"
        class="inline-flex items-center gap-1 rounded-full border border-dashed border-detect px-2 py-px text-[0.6875rem] text-detect"
        data-testid="suspect-chip"
        >{{ t('detections.chipSuspect', { n: suspects }, suspects) }}</span
      >
      <span
        v-if="confirmed"
        class="inline-flex items-center gap-1 rounded-full bg-detect/15 px-2 py-px text-[0.6875rem] text-detect"
        data-testid="detection-chip"
        >{{ t('detections.chipConfirmed', { n: confirmed }, confirmed) }}</span
      >
      <CalibrationChip v-if="record" :calibration="record.calibration" compact />
      <button
        v-if="record"
        type="button"
        class="icon-btn h-6 min-w-6 text-[0.6875rem]"
        :aria-expanded="details"
        :aria-label="t('records.details')"
        :title="t('records.details')"
        @click="details = !details"
      >
        ⓘ
      </button>
      <span
        v-if="avail"
        class="num ml-auto text-xs"
        :class="LEVEL_TEXT[figureLevel(avail, display.thresholds)]"
        :title="
          t('common.validOfExpected', { valid: int(avail.valid, lc), expected: int(avail.expected, lc) })
        "
      >
        {{ pct(avail.pct, lc) }} %
        <span class="text-ink-3">· {{ t('board.missing', { n: int(avail.missing, lc) }) }}</span>
      </span>
    </header>

    <dl
      v-if="details && record"
      class="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-1 border-b border-line bg-sunken/50 px-3 py-2 text-xs sm:grid-cols-[auto_minmax(0,1fr)_auto_minmax(0,1fr)]"
      data-testid="sensor-details"
    >
      <template v-for="row in detailRows" :key="row.key">
        <dt class="text-ink-3">{{ t(`records.meta.${row.key}`) }}</dt>
        <dd class="num min-w-0 truncate">{{ row.value }}</dd>
      </template>
    </dl>
    <p v-if="loader.error.value" class="px-3 py-3 text-sm text-warn" role="alert">
      {{ t('common.error') }}
      <button type="button" class="icon-btn" @click="loader.load()">{{ t('common.retry') }}</button>
    </p>
    <div v-else-if="!loader.data.value" class="h-24 animate-pulse bg-sunken" aria-busy="true" />
    <table v-else class="w-full table-fixed text-xs">
      <colgroup>
        <col class="w-[34%] sm:w-[26%]" />
        <col class="w-[26%] sm:w-[16%]" />
        <col />
        <col class="w-[11%] max-sm:hidden" />
        <col class="w-[11%] max-sm:hidden" />
        <col class="w-[11%] max-sm:hidden" />
        <col class="w-7" />
      </colgroup>
      <thead class="text-[0.625rem] text-ink-3">
        <tr>
          <th class="px-3 py-1 text-left font-normal">{{ t('sensor.field') }}</th>
          <th class="text-right font-normal">{{ t('sensor.latest') }}</th>
          <th class="pl-3 text-left font-normal">{{ t('sensor.trend') }}</th>
          <th class="text-right font-normal max-sm:hidden">{{ t('sensor.min') }}</th>
          <th class="text-right font-normal max-sm:hidden">{{ t('sensor.max') }}</th>
          <th class="text-right font-normal max-sm:hidden">{{ t('sensor.mean') }}</th>
          <th />
        </tr>
      </thead>
      <tbody>
        <template v-for="f in rows" :key="f.code">
          <tr
            class="cursor-pointer border-t border-line hover:bg-sunken"
            :aria-expanded="open === f.code"
            tabindex="0"
            @click="open = open === f.code ? null : f.code"
            @keydown.enter.prevent="open = open === f.code ? null : f.code"
            @keydown.space.prevent="open = open === f.code ? null : f.code"
          >
            <td class="px-3 py-1.5 leading-tight sm:truncate">
              {{ name(f.code) }}
              <span class="num text-[0.625rem] text-ink-3"
                >{{ f.code }}<span v-if="f.mandatory" :title="t('sensor.mandatory')">*</span></span
              >
              <span
                v-if="fieldDetections(f.code).some((d) => d.status !== 'rejected')"
                class="ml-1 inline-block h-2 w-2 rounded-full align-middle"
                :class="
                  fieldDetections(f.code).some((d) => d.status === 'confirmed')
                    ? 'bg-detect'
                    : 'border border-dashed border-detect'
                "
                :title="t('detections.inWindow')"
              />
            </td>
            <td class="num text-right">
              <span v-if="noCloud(f)" class="font-medium">{{ t('sensor.noCloud') }}</span>
              <template v-else-if="f.type === 'numeric'">
                <span class="text-sm font-semibold">{{ fmt(f.stats.last?.value, f.unit) }}</span>
                <span class="text-ink-3"> {{ unitLabel(f.unit) }}</span>
              </template>
              <span v-else class="font-medium">{{
                textLabel(f.stats.last?.value as string | undefined)
              }}</span>
              <span
                class="block text-[0.625rem]"
                :class="stale(f) ? 'font-medium text-warn' : 'text-ink-3'"
                >{{ hhmm(f.stats.last?.time) }}</span
              >
            </td>
            <td class="pl-3 text-ink-3">
              <Sparkline v-if="f.series" :values="f.series.v" :width="120" :height="22" class="text-accent" />
              <span v-else-if="topState(f)" class="block truncate">{{
                t('sensor.mostFrequent', { state: topState(f)!.value, n: int(topState(f)!.minutes, lc) })
              }}</span>
              <span v-else>{{ t('sensor.noEventWindow') }}</span>
            </td>
            <td class="num text-right max-sm:hidden">
              {{ f.type === 'numeric' ? fmt(f.stats.min, f.unit) : '' }}
            </td>
            <td class="num text-right max-sm:hidden">
              {{ f.type === 'numeric' ? fmt(f.stats.max, f.unit) : '' }}
            </td>
            <td class="num text-right max-sm:hidden">
              {{ f.type === 'numeric' ? fmt(f.stats.mean, f.unit) : '' }}
            </td>
            <td class="pr-2 text-right text-ink-3" aria-hidden="true">{{ open === f.code ? '▾' : '▸' }}</td>
          </tr>
          <tr v-if="open === f.code">
            <td colspan="7" class="border-t border-line bg-sunken/50 px-3 py-2">
              <div
                v-if="auth.isAdmin"
                class="mb-1.5 flex min-h-7 flex-wrap items-center justify-end gap-2 text-xs"
                data-testid="flag-toolbar"
              >
                <template v-if="selecting">
                  <span v-if="!selection" class="mr-auto text-ink-2">{{ t('flags.onChart.hint') }}</span>
                  <span v-else class="num mr-auto font-medium text-flag" role="status">{{
                    selectionText
                  }}</span>
                  <button
                    v-if="selection"
                    type="button"
                    class="btn-primary px-2.5 py-1 text-xs"
                    @click="confirmFlag"
                  >
                    {{ t('flags.onChart.continue') }}
                  </button>
                  <button type="button" class="btn px-2.5 py-1 text-xs" @click="selecting = false">
                    {{ t('flags.onChart.cancel') }}
                  </button>
                </template>
                <button v-else type="button" class="btn px-2.5 py-1 text-xs" @click="startFlag(f)">
                  <span class="flag-hatch h-2.5 w-2.5 rounded-[1px] border border-flag" aria-hidden="true" />
                  {{ draggable(f) ? t('flags.onChart.select') : t('flags.onChart.selectWindow') }}
                </button>
              </div>
              <div
                class="grid gap-3"
                :class="
                  loader.data.value.wind && (f.code === 'WS' || f.code === 'WD')
                    ? 'md:grid-cols-[minmax(0,1fr)_16rem]'
                    : ''
                "
              >
                <SkyChart v-if="f.sky" :field="f" :window="window" :flags="flags" />
                <WeatherView v-else-if="f.weather" :field="f" :window="window" :flags="flags" />
                <LightningView v-else-if="f.lightning" :field="f" :window="window" :flags="flags" />
                <FieldChart
                  v-else
                  v-model:selection="selection"
                  :field="f"
                  :name="name(f.code)"
                  :window="window"
                  :flags="flags"
                  :detections="fieldDetections(f.code)"
                  :selecting="selecting"
                />
                <div v-if="loader.data.value.wind && (f.code === 'WS' || f.code === 'WD')">
                  <WindRose :wind="loader.data.value.wind" />
                </div>
              </div>
              <section
                v-if="flags.length"
                class="mt-2 border-t border-line pt-2"
                :aria-label="t('flags.inWindow')"
              >
                <h4 class="eyebrow mb-1.5">{{ t('flags.inWindow') }}</h4>
                <FlagList :flags="flags" :can-edit="auth.isAdmin" @edit="(id) => emit('editFlag', id)" />
              </section>
              <section
                v-if="fieldDetections(f.code).length"
                class="mt-2 border-t border-line pt-2"
                :aria-label="t('detections.inWindow')"
              >
                <h4 class="eyebrow mb-1.5">{{ t('detections.inWindow') }}</h4>
                <DetectionList
                  :detections="fieldDetections(f.code)"
                  :fields="fields"
                  :can-review="auth.isAdmin"
                />
              </section>
            </td>
          </tr>
        </template>
      </tbody>
    </table>
    <GustPanel v-if="loader.data.value?.wind" :wind="loader.data.value.wind" />
  </section>
</template>
