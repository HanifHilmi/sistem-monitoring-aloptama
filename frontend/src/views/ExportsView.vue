<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { ApiProblem, api } from '@/api/client'
import { ALARM_TYPES, type AlarmType, type SystemInfo } from '@/api/types'
import PeriodBar from '@/components/PeriodBar.vue'
import { usePeriodQuery } from '@/composables/useUrlState'
import type { Locale } from '@/i18n'
import { useDisplayStore } from '@/stores/display'
import { DEFAULT_SYSTEM } from '@/stores/live'
import {
  ALARM_COLUMNS,
  DAILY_COLUMNS,
  EXPORT_KINDS,
  MAX_DAYS,
  MINUTE_STATUSES,
  QUALITY_COLUMNS,
  defaultReportMonth,
  estimateBytes,
  estimateRows,
  exportFileName,
  exportUrl,
  minuteHeader,
  minuteLayout,
  reportFileName,
  reportMonths,
  type Column,
  type ExportKind,
} from '@/utils/exports'
import { int, num } from '@/utils/format'
import { saveBlob } from '@/utils/download'
import { formatUtc, isOpen } from '@/utils/time'

// Exports (FR-EXP-001…003, Viewers and Admins): the monthly PDF and four CSV files. The server writes the files,
// checks the role and the limits, and records every download in the audit log.
const props = withDefaults(defineProps<{ code?: string }>(), { code: DEFAULT_SYSTEM })
const { t, te, locale } = useI18n()
const lc = computed(() => locale.value as Locale)
const route = useRoute()
const router = useRouter()
const display = useDisplayStore()
const info = ref<SystemInfo | null>(null)
const definitions = ref<string | null>(null)
onMounted(async () => {
  info.value = await display.system(props.code)
  site.value ||= info.value.sites[0]?.slug ?? ''
  try {
    definitions.value = (await api.definitions()).version
  } catch {
    /* the note just leaves the version out */
  }
})

const kind = computed<ExportKind>({
  get: () => {
    const k = route.query.kind
    return typeof k === 'string' && (EXPORT_KINDS as readonly string[]).includes(k)
      ? (k as ExportKind)
      : 'daily'
  },
  set: (k) => void router.replace({ query: { ...route.query, kind: k === 'daily' ? undefined : k } }),
})
const period = usePeriodQuery()
const DAY = 86_400_000
const days = computed(() => (period.value.to.getTime() - period.value.from.getTime()) / DAY)
const tooLong = computed(() => days.value > MAX_DAYS[kind.value])
const open = computed(() => isOpen(period.value))
const beforeCoverage = computed(
  () => !!info.value && period.value.from.getTime() < Date.parse(info.value.coverage_start),
)

// ---- options per file ---------------------------------------------------------------------------
const site = ref(typeof route.query.site === 'string' ? route.query.site : '')
const alarmType = ref<AlarmType | ''>('')
const alarmPlace = ref('')
const alarmSensor = ref('')
watch(alarmPlace, () => (alarmSensor.value = ''))
const alarmScope = computed(() =>
  alarmPlace.value.startsWith('site:') && alarmSensor.value
    ? `component:${alarmPlace.value.slice(5)}:${alarmSensor.value}`
    : alarmPlace.value,
)
const places = computed(() => [
  ...(info.value?.sites ?? []).map((s) => ({ value: `site:${s.slug}`, label: s.name[lc.value] })),
  { value: 'station', label: t('alarms.place.station') },
  { value: 'unmapped', label: t('alarms.place.unmapped') },
])
const placeSensors = computed(() =>
  alarmPlace.value.startsWith('site:')
    ? (info.value?.sites.find((s) => s.slug === alarmPlace.value.slice(5))?.components ?? []).map((c) => ({
        value: c.type,
        label: c.name[lc.value],
      }))
    : [],
)
const withFlags = ref(true)
const withDetections = ref(true)
const allDetections = ref(false)

// ---- the file -----------------------------------------------------------------------------------
const siteInfo = computed(() => info.value?.sites.find((s) => s.slug === site.value) ?? null)
const layout = computed(() => (info.value && site.value ? minuteLayout(info.value, site.value) : null))
const columns = computed<Column[]>(() =>
  kind.value === 'daily' ? DAILY_COLUMNS : kind.value === 'alarms' ? ALARM_COLUMNS : QUALITY_COLUMNS,
)
const columnCount = computed(() =>
  kind.value === 'minutes' ? (layout.value ? minuteHeader(layout.value).length : 0) : columns.value.length,
)
const options = computed(() => ({
  site: site.value,
  type: alarmType.value || undefined,
  scope: alarmScope.value || undefined,
  flags: withFlags.value,
  detections: withDetections.value,
  all: allDetections.value,
}))
const nothingPicked = computed(() => kind.value === 'quality' && !withFlags.value && !withDetections.value)
const fileName = computed(() =>
  exportFileName(
    props.code,
    kind.value,
    period.value.from,
    period.value.to,
    kind.value === 'minutes' ? siteInfo.value?.code : undefined,
  ),
)
const href = computed(() =>
  exportUrl(props.code, kind.value, period.value.from, period.value.to, options.value),
)
const ready = computed(() => !!info.value && !tooLong.value && !nothingPicked.value)

// The file is fetched by the page and then handed to the browser, so a refusal (too many files a minute, a
// session that ended) is said on the page instead of being saved as the file. Files are at most a few MB.
const busy = ref(false)
const failed = ref<string | null>(null)
async function download() {
  busy.value = true
  failed.value = null
  try {
    const res = await fetch(href.value, { credentials: 'same-origin' })
    if (!res.ok) {
      failed.value = (await problemCode(res)) ?? 'http_error'
      return
    }
    saveBlob(await res.blob(), fileName.value)
  } catch {
    failed.value = 'network_error'
  } finally {
    busy.value = false
  }
}
async function problemCode(res: Response): Promise<string | null> {
  try {
    return ((await res.json()) as { code?: string }).code ?? null
  } catch {
    return null
  }
}
watch([kind, href], () => (failed.value = null))

// Alarm changes and data-quality records in the period, for the row estimate.
const count = ref<number | null>(null)
let seq = 0
watch(
  () => [kind.value, period.value.from.getTime(), period.value.to.getTime(), JSON.stringify(options.value)],
  async () => {
    const mine = ++seq
    count.value = null
    if (tooLong.value || (kind.value !== 'alarms' && kind.value !== 'quality')) return
    const { from, to } = period.value
    try {
      let n = 0
      if (kind.value === 'alarms') {
        const page = await api.alarms(props.code, {
          from: from.toISOString(),
          to: to.toISOString(),
          type: options.value.type,
          scope: options.value.scope,
        })
        n = page.total
      } else {
        const [flags, detections] = await Promise.all([
          withFlags.value ? api.flags(props.code, from, to) : Promise.resolve([]),
          withDetections.value ? api.detections(props.code, from, to) : Promise.resolve([]),
        ])
        n =
          flags.reduce((s, f) => s + f.components.length, 0) +
          detections.filter((d) => allDetections.value || d.status === 'confirmed').length
      }
      if (mine === seq) count.value = n
    } catch {
      /* the estimate is only a hint */
    }
  },
  { immediate: true },
)
const rows = computed(() =>
  info.value
    ? estimateRows(kind.value, info.value, period.value.from, period.value.to, Date.now(), count.value)
    : null,
)
function size(bytes: number): string {
  if (bytes < 1024) return `${int(bytes, lc.value)} B`
  if (bytes < 1024 * 1024) return `${num(bytes / 1024, lc.value, 0)} kB`
  return `${num(bytes / 1024 / 1024, lc.value, 1)} MB`
}
const about = computed(() => {
  if (rows.value === null) return t('exports.counting')
  const parts = [
    t('exports.rows', { n: int(rows.value, lc.value) }, rows.value),
    t('exports.columns', { n: columnCount.value }, columnCount.value),
  ]
  if (rows.value) parts.push(`≈ ${size(estimateBytes(kind.value, rows.value, columnCount.value))}`)
  return parts.join(' · ')
})

// ---- monthly PDF (R3.5) ---------------------------------------------------------------------------
// One UTC month, drawn on the server from the dashboard's figures (FR-EXP-001). Last month by default.
const reportList = computed(() => (info.value ? reportMonths(info.value.coverage_start, new Date()) : []))
const reportMonth = ref('')
watch(
  reportList,
  (list) => {
    if (!list.includes(reportMonth.value)) reportMonth.value = defaultReportMonth(list)
  },
  { immediate: true },
)
const reportLang = ref<'id' | 'en'>(lc.value === 'en' ? 'en' : 'id')
function monthLabel(m: string): string {
  return new Intl.DateTimeFormat(lc.value === 'id' ? 'id-ID' : 'en-GB', {
    month: 'long',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(new Date(`${m}-01T00:00:00Z`))
}
const reportName = computed(() => reportFileName(props.code, reportMonth.value, reportLang.value))
const reportOpen = computed(() => !!reportMonth.value && reportMonth.value === reportList.value[0])
const reportPartial = computed(
  () => !!info.value && reportMonth.value === info.value.coverage_start.slice(0, 7),
)
const reportBusy = ref(false)
const reportFailed = ref<string | null>(null)
const elapsed = ref(0)
async function downloadReport() {
  reportBusy.value = true
  reportFailed.value = null
  elapsed.value = 0
  const started = Date.now()
  const tick = setInterval(() => (elapsed.value = Math.round((Date.now() - started) / 1000)), 1000)
  try {
    saveBlob(await api.monthlyReport(props.code, reportMonth.value, reportLang.value), reportName.value)
  } catch (e) {
    reportFailed.value = e instanceof ApiProblem ? e.code : 'network_error'
  } finally {
    clearInterval(tick)
    reportBusy.value = false
  }
}
watch([reportMonth, reportLang], () => (reportFailed.value = null))
</script>

<template>
  <div class="mx-auto flex w-full max-w-6xl flex-col gap-5 px-3 py-5 sm:px-5">
    <header class="max-w-3xl">
      <h1 class="text-lg font-semibold">{{ t('exports.title') }}</h1>
      <p class="text-sm text-ink-2">{{ t('exports.subtitle') }}</p>
    </header>

    <!-- Monthly report (PDF, R3.5) -->
    <section
      class="rounded-lg border border-line bg-surface px-4 py-3.5"
      data-testid="export-pdf"
      aria-labelledby="pdf-title"
    >
      <div class="flex flex-wrap items-end gap-x-5 gap-y-3">
        <div class="min-w-0 flex-1 basis-72 self-start">
          <h2 id="pdf-title" class="text-sm font-semibold">{{ t('exports.pdf.title') }}</h2>
          <p class="mt-0.5 text-xs text-ink-2">{{ t('exports.pdf.what') }}</p>
        </div>
        <label class="flex flex-col gap-1">
          <span class="label">{{ t('exports.pdf.month') }}</span>
          <select
            v-model="reportMonth"
            class="input py-1 text-xs"
            data-testid="report-month"
            :disabled="reportBusy"
          >
            <option v-for="m in reportList" :key="m" :value="m">{{ monthLabel(m) }}</option>
          </select>
        </label>
        <div class="flex flex-col gap-1">
          <span id="report-lang" class="label">{{ t('exports.pdf.language') }}</span>
          <div class="seg" role="group" aria-labelledby="report-lang">
            <button
              type="button"
              :aria-pressed="reportLang === 'id'"
              :disabled="reportBusy"
              data-testid="report-lang-id"
              @click="reportLang = 'id'"
            >
              Bahasa Indonesia
            </button>
            <button
              type="button"
              :aria-pressed="reportLang === 'en'"
              :disabled="reportBusy"
              data-testid="report-lang-en"
              @click="reportLang = 'en'"
            >
              English
            </button>
          </div>
        </div>
        <button
          type="button"
          class="btn-primary"
          :disabled="!reportMonth || reportBusy"
          :aria-busy="reportBusy"
          data-testid="report-download"
          @click="downloadReport"
        >
          ⤓ {{ reportBusy ? t('exports.pdf.preparing', { s: elapsed }) : t('exports.pdf.download') }}
        </button>
      </div>
      <div
        class="mt-3 flex flex-wrap items-baseline gap-x-4 gap-y-1 border-t border-line pt-2.5 text-xs text-ink-2"
      >
        <span class="num font-medium break-all text-ink" data-testid="report-filename">{{ reportName }}</span>
        <span>{{ t('exports.pdf.how') }}</span>
      </div>
      <p v-if="reportOpen" class="mt-1.5 text-xs text-ink-2" data-testid="report-open">
        {{ t('exports.pdf.open') }}
      </p>
      <p v-if="reportPartial && info" class="mt-1.5 text-xs text-ink-2" data-testid="report-partial">
        {{ t('exports.pdf.partial', { date: formatUtc(info.coverage_start) }) }}
      </p>
      <p v-if="reportFailed" class="mt-2 text-sm text-warn" role="alert" data-testid="report-failed">
        {{
          te(`exports.error.${reportFailed}`) ? t(`exports.error.${reportFailed}`) : t('exports.error.other')
        }}
      </p>
    </section>

    <!-- CSV files -->
    <section aria-labelledby="csv-title" class="flex flex-col gap-3">
      <h2 id="csv-title" class="text-base font-semibold">{{ t('exports.csv.title') }}</h2>
      <div class="grid gap-4 lg:grid-cols-[18rem_minmax(0,1fr)] lg:items-start">
        <div
          role="radiogroup"
          :aria-label="t('exports.csv.kind')"
          class="grid gap-2 sm:grid-cols-2 lg:grid-cols-1"
        >
          <button
            v-for="k in EXPORT_KINDS"
            :key="k"
            type="button"
            role="radio"
            :aria-checked="kind === k"
            class="flex flex-col gap-0.5 rounded-lg border px-3.5 py-2.5 text-left"
            :class="
              kind === k
                ? 'border-accent bg-accent/5 ring-1 ring-accent'
                : 'border-line bg-surface hover:border-line-strong'
            "
            :data-testid="`export-kind-${k}`"
            @click="kind = k"
          >
            <span class="text-sm font-medium">{{ t(`exports.kind.${k}.name`) }}</span>
            <span class="text-xs text-ink-2">{{ t(`exports.kind.${k}.what`) }}</span>
          </button>
        </div>

        <div class="flex min-w-0 flex-col gap-4 rounded-lg border border-line bg-surface px-4 py-4">
          <!-- options -->
          <div class="flex flex-wrap items-end gap-x-4 gap-y-3">
            <div class="flex flex-col gap-1">
              <span class="label">{{ t('exports.period') }}</span>
              <PeriodBar v-model="period" />
            </div>
            <label v-if="kind === 'minutes'" class="flex flex-col gap-1">
              <span class="label">{{ t('exports.site') }}</span>
              <select v-model="site" class="input py-1 text-xs" data-testid="export-site">
                <option v-for="s in info?.sites ?? []" :key="s.slug" :value="s.slug">{{ s.name[lc] }}</option>
              </select>
            </label>
            <template v-if="kind === 'alarms'">
              <label class="flex flex-col gap-1">
                <span class="label">{{ t('alarms.filter.type') }}</span>
                <select v-model="alarmType" class="input py-1 text-xs">
                  <option value="">{{ t('alarms.filter.all') }}</option>
                  <option v-for="x in ALARM_TYPES" :key="x" :value="x">{{ t(`alarms.type.${x}`) }}</option>
                </select>
              </label>
              <label class="flex flex-col gap-1">
                <span class="label">{{ t('alarms.filter.place') }}</span>
                <select v-model="alarmPlace" class="input max-w-48 py-1 text-xs" data-testid="export-place">
                  <option value="">{{ t('alarms.filter.all') }}</option>
                  <option v-for="s in places" :key="s.value" :value="s.value">{{ s.label }}</option>
                </select>
              </label>
              <label v-if="placeSensors.length" class="flex flex-col gap-1">
                <span class="label">{{ t('alarms.filter.sensor') }}</span>
                <select v-model="alarmSensor" class="input max-w-60 py-1 text-xs">
                  <option value="">{{ t('alarms.filter.allSensors') }}</option>
                  <option v-for="c in placeSensors" :key="c.value" :value="c.value">{{ c.label }}</option>
                </select>
              </label>
            </template>
            <fieldset v-if="kind === 'quality'" class="flex flex-col gap-1">
              <legend class="label mb-1">{{ t('exports.records') }}</legend>
              <div class="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-sm">
                <label class="flex items-center gap-1.5"
                  ><input v-model="withFlags" type="checkbox" /> {{ t('exports.quality.flags') }}</label
                >
                <label class="flex items-center gap-1.5"
                  ><input v-model="withDetections" type="checkbox" />
                  {{ t('exports.quality.detections') }}</label
                >
                <label
                  class="flex items-center gap-1.5 text-ink-2"
                  :class="withDetections ? '' : 'opacity-50'"
                  ><input v-model="allDetections" type="checkbox" :disabled="!withDetections" />
                  {{ t('exports.quality.all') }}</label
                >
              </div>
            </fieldset>
          </div>

          <p v-if="tooLong" class="text-sm text-warn" role="alert" data-testid="export-too-long">
            {{ t(`exports.tooLong.${kind === 'minutes' ? 'minutes' : 'other'}`, { n: MAX_DAYS[kind] }) }}
          </p>
          <p v-else-if="nothingPicked" class="text-sm text-warn" role="alert">
            {{ t('exports.quality.none') }}
          </p>
          <p v-if="open && !tooLong" class="text-xs text-ink-3">
            {{ t(kind === 'daily' || kind === 'minutes' ? 'exports.open.figures' : 'exports.open.records') }}
          </p>
          <p v-if="beforeCoverage && info && !tooLong" class="text-xs text-ink-3">
            {{ t('exports.coverage', { time: formatUtc(info.coverage_start) }) }}
          </p>

          <!-- the file and its download -->
          <div class="flex flex-wrap items-center gap-3 rounded-md bg-sunken/70 px-3 py-2.5">
            <span aria-hidden="true" class="text-lg text-ink-3">▤</span>
            <div class="min-w-0 flex-1">
              <p class="num text-sm font-medium" data-testid="export-filename">
                <!-- long names wrap after an underscore -->
                <template v-for="(part, i) in fileName.split('_')" :key="i"
                  >{{ i ? '_' : '' }}<wbr v-if="i" />{{ part }}</template
                >
              </p>
              <p class="num text-xs text-ink-2" data-testid="export-size">{{ ready ? about : '—' }}</p>
            </div>
            <button
              type="button"
              class="btn-primary"
              :disabled="!ready || busy"
              :aria-busy="busy"
              data-testid="export-download"
              @click="download"
            >
              ⤓ {{ busy ? t('exports.preparing') : t('exports.download') }}
            </button>
          </div>
          <p v-if="failed" class="text-sm text-warn" role="alert" data-testid="export-failed">
            {{ te(`exports.error.${failed}`) ? t(`exports.error.${failed}`) : t('exports.error.other') }}
          </p>

          <!-- what is in it -->
          <section :aria-label="t('exports.inFile')">
            <h3 class="mb-1.5 text-sm font-semibold">{{ t('exports.inFile') }}</h3>
            <p class="mb-2 text-xs text-ink-2">{{ t(`exports.kind.${kind}.rows`) }}</p>
            <div class="overflow-x-auto rounded-md border border-line">
              <table class="w-full text-xs sm:min-w-[560px]" data-testid="export-columns">
                <thead
                  class="hidden border-b border-line bg-sunken/60 text-left text-ink-3 sm:table-header-group"
                >
                  <tr>
                    <th class="px-3 py-0.5 sm:py-1.5 font-normal">{{ t('exports.col.header') }}</th>
                    <th class="px-3 py-0.5 sm:py-1.5 font-normal">{{ t('exports.col.meaning') }}</th>
                    <th class="px-3 py-0.5 sm:py-1.5 font-normal">{{ t('exports.col.example') }}</th>
                  </tr>
                </thead>
                <tbody v-if="kind !== 'minutes'">
                  <tr
                    v-for="c in columns"
                    :key="c.name"
                    class="block border-b border-line py-1 align-top sm:table-row sm:py-0 last:border-0"
                  >
                    <td class="block sm:table-cell num whitespace-nowrap px-3 py-0.5 sm:py-1.5 font-medium">
                      {{ c.name }}
                    </td>
                    <td class="block sm:table-cell px-3 py-0.5 sm:py-1.5 text-ink-2">
                      {{ t(`exports.col.${c.key}`) }}
                    </td>
                    <td class="block sm:table-cell num whitespace-nowrap px-3 py-0.5 sm:py-1.5 text-ink-3">
                      {{ c.example || '—' }}
                    </td>
                  </tr>
                </tbody>
                <tbody v-else-if="layout">
                  <tr
                    v-for="c in layout.lead"
                    :key="c.name"
                    class="block border-b border-line py-1 align-top sm:table-row sm:py-0"
                  >
                    <td class="block sm:table-cell num whitespace-nowrap px-3 py-0.5 sm:py-1.5 font-medium">
                      {{ c.name }}
                    </td>
                    <td class="block sm:table-cell px-3 py-0.5 sm:py-1.5 text-ink-2">
                      {{ t(`exports.col.${c.key}`) }}
                    </td>
                    <td class="block sm:table-cell num whitespace-nowrap px-3 py-0.5 sm:py-1.5 text-ink-3">
                      {{ c.example }}
                    </td>
                  </tr>
                  <tr
                    v-for="s in layout.sensors"
                    :key="s.type"
                    class="block border-b border-line py-1 align-top sm:table-row sm:py-0"
                    data-testid="export-sensor"
                  >
                    <td class="block sm:table-cell px-3 py-0.5 sm:py-1.5">
                      <span class="num block font-medium">{{ s.status }}</span>
                      <span
                        v-for="f in s.fields"
                        :key="f"
                        class="num mr-1 mt-1 inline-block rounded bg-sunken px-1.5 py-px"
                        >{{ f }}</span
                      >
                    </td>
                    <td class="block sm:table-cell px-3 py-0.5 sm:py-1.5 text-ink-2">
                      {{ siteInfo?.components.find((c) => c.type === s.type)?.name[lc] ?? s.type }}:
                      {{ t(s.fields.length ? 'exports.col.sensor' : 'exports.col.dcp') }}
                    </td>
                    <td class="block sm:table-cell num whitespace-nowrap px-3 py-0.5 sm:py-1.5 text-ink-3">
                      valid
                    </td>
                  </tr>
                  <tr
                    v-for="c in layout.trailer"
                    :key="c.name"
                    class="block border-b border-line py-1 align-top sm:table-row sm:py-0 last:border-0"
                  >
                    <td class="block sm:table-cell num whitespace-nowrap px-3 py-0.5 sm:py-1.5 font-medium">
                      {{ c.name }}
                    </td>
                    <td class="block sm:table-cell px-3 py-0.5 sm:py-1.5 text-ink-2">
                      {{ t(`exports.col.${c.key}`) }}
                    </td>
                    <td class="block sm:table-cell num whitespace-nowrap px-3 py-0.5 sm:py-1.5 text-ink-3">
                      {{ c.example }}
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p v-if="kind === 'minutes'" class="mt-2 text-xs text-ink-3">
              {{ t('exports.statuses', { list: MINUTE_STATUSES.join(', ') }) }}
            </p>
          </section>

          <!-- how to get the month's figures back from the daily file (U7) -->
          <section
            v-if="kind === 'daily'"
            class="rounded-md border border-line px-3 py-2.5"
            data-testid="export-recompute"
            :aria-label="t('exports.recompute.title')"
          >
            <h3 class="mb-1 text-sm font-semibold">{{ t('exports.recompute.title') }}</h3>
            <ul class="flex list-disc flex-col gap-1 pl-5 text-xs text-ink-2">
              <li v-for="k in ['sla', 'uptime', 'reach', 'site', 'ola', 'pooled']" :key="k">
                {{ t(`exports.recompute.${k}`) }}
              </li>
            </ul>
          </section>
        </div>
      </div>
    </section>

    <!-- format -->
    <section class="max-w-3xl" :aria-label="t('exports.format.title')">
      <h2 class="mb-1.5 text-sm font-semibold">{{ t('exports.format.title') }}</h2>
      <ul class="flex list-disc flex-col gap-1 pl-5 text-xs text-ink-2">
        <li>{{ t('exports.format.encoding') }}</li>
        <li>{{ t('exports.format.times') }}</li>
        <li>{{ t('exports.format.safe') }}</li>
        <li>
          {{ t('exports.format.version', { v: definitions ?? '…' }) }}
          <RouterLink :to="`/systems/${code}/definitions`" class="text-accent hover:underline"
            >{{ t('nav.definitions') }} →</RouterLink
          >
        </li>
        <li>{{ t('exports.format.audit') }}</li>
      </ul>
    </section>
  </div>
</template>
