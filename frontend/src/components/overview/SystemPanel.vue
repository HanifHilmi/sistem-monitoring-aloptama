<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import { api } from '@/api/client'
import type { ComponentStatus, Problem, StatusResponse, SystemInfo, SystemSummary } from '@/api/types'
import { useLoader } from '@/composables/useLoader'
import { usePolling } from '@/composables/usePolling'
import type { Locale } from '@/i18n'
import { useDisplayStore } from '@/stores/display'
import { useLiveStore } from '@/stores/live'
import { since } from '@/utils/alarms'
import { figureLevel, int, LEVEL_TEXT, lostMinutes, matrixLost, pct } from '@/utils/format'
import { monthProgress } from '@/utils/overview'
import { boardPath, sitePath } from '@/utils/paths'
import { problemMessage, SEVERITY_TONE } from '@/utils/problems'
import { formatUtc, periodContaining } from '@/utils/time'
import MonthStrip from './MonthStrip.vue'

// One system on the dashboard (FR-DSH-001): right now (data flow, last data, today, the latest METAR), the month so
// far (SLA, OLA, day by day) and every site's components. A second system gets a second panel, nothing else.
const props = defineProps<{ summary: SystemSummary; now: Date }>()
const { t, locale } = useI18n()
const lc = computed(() => locale.value as Locale)
const display = useDisplayStore()
const live = useLiveStore()
const code = computed(() => props.summary.code)

const info = shallowRef<SystemInfo | null>(null)
watch(code, async (c) => (info.value = await display.system(c).catch(() => null)), { immediate: true })

// The top bar already keeps its system's status and problems fresh; any other system is read here.
const isLive = computed(() => live.systemCode === code.value)
const own = useLoader(() => Promise.all([api.status(code.value), api.problems(code.value)]))
const status = computed<StatusResponse | null>(() =>
  isLive.value ? live.status : (own.data.value?.[0] ?? null),
)
const problems = computed<Problem[]>(() =>
  isLive.value ? live.problems : (own.data.value?.[1].problems ?? []),
)
const reports = useLoader(() => api.latestReports(code.value))
const month = useLoader(async () => {
  const p = periodContaining('month', new Date())
  const [matrix, sla] = await Promise.all([
    api.matrix(code.value, p.from, p.to, 'day'),
    api.outages(code.value, p.from, p.to, 'sla', 1),
  ])
  return { matrix, slaOutages: sla.intervals_total }
})
usePolling(() => {
  if (!isLive.value) void own.load({ silent: true })
  void reports.load({ silent: true })
}, 60_000)
usePolling(() => month.load({ silent: !!month.data.value }), 300_000)

const worst = computed(() => problems.value[0]?.severity ?? null)
const strip = computed(() =>
  worst.value === 'critical' || worst.value === 'major'
    ? 'bg-bad/6'
    : worst.value === 'minor'
      ? 'bg-warn/8'
      : 'bg-sunken/60',
)
const pill = computed(() =>
  !problems.value.length
    ? 'bg-ok/12 text-ok'
    : worst.value === 'critical' || worst.value === 'major'
      ? 'bg-bad/12 text-bad'
      : worst.value === 'minor'
        ? 'bg-warn/15 text-warn'
        : 'bg-sunken text-ink-2',
)

const ago = (iso: string) => t('reports.ago', { age: since(iso, props.now.getTime(), t) })
const STALE_MS = 5 * 60_000
const lastData = computed(() => status.value?.last_data_minute ?? props.summary.last_data_minute)
const stale = computed(() => !lastData.value || props.now.getTime() - Date.parse(lastData.value) > STALE_MS)
const metar = computed(() => reports.data.value?.metar[0] ?? null)

const monthName = computed(() =>
  new Intl.DateTimeFormat(lc.value === 'id' ? 'id-ID' : 'en-GB', { month: 'long', timeZone: 'UTC' }).format(
    props.now,
  ),
)
const progress = computed(() => monthProgress(props.now))
const slaLevel = computed(() => figureLevel(props.summary.sla_month, display.thresholds))
const olaLevel = computed(() => {
  const m = month.data.value?.matrix
  const row = m?.rows.find((r) => r.kind === 'ola')
  return m && row
    ? figureLevel(row.total, display.thresholds, matrixLost(m.rows, row, 'total'))
    : figureLevel(props.summary.ola_month, display.thresholds)
})

const sites = computed(() =>
  (info.value?.sites ?? []).map((s) => {
    const st = status.value?.sites.find((x) => x.slug === s.slug)
    const row = month.data.value?.matrix.rows.find((r) => r.kind === 'site' && r.site === s.slug)
    return {
      slug: s.slug,
      name: s.name[lc.value],
      online: st?.components_online ?? null,
      total: st?.components_total ?? s.components.length,
      components: st?.components ?? [],
      month: row?.total.pct ?? null,
    }
  }),
)
const valid = computed(() => sites.value.reduce((n, s) => n + (s.online ?? 0), 0))
const total = computed(() => sites.value.reduce((n, s) => n + s.total, 0))

// UX-002: colour and a sign, never colour alone.
const CHIP: Record<ComponentStatus, { tone: string; sign: string }> = {
  valid: { tone: 'bg-sunken text-ink-2', sign: '' },
  field_missing: { tone: 'bg-warn/20 text-ink font-medium', sign: '!' },
  stale: { tone: 'bg-warn/20 text-ink font-medium', sign: '!' },
  no_data: { tone: 'bg-bad/15 text-bad font-medium', sign: '×' },
  not_in_service: { tone: 'bg-sunken text-ink-3', sign: '–' },
  unknown: { tone: 'bg-sunken text-ink-3', sign: '?' },
}
const FLOW_DOT = { producing: 'bg-ok', not_producing: 'bg-bad', unknown: 'bg-ink-3' } as const
</script>

<template>
  <section
    class="overflow-hidden rounded-lg border border-line bg-surface"
    :aria-labelledby="`sys-${summary.code}`"
    data-testid="system-panel"
  >
    <header class="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-line px-4 py-3">
      <h2 :id="`sys-${summary.code}`" class="text-base font-semibold">
        <RouterLink :to="boardPath(summary.code)" class="hover:text-accent">{{
          summary.name[lc]
        }}</RouterLink>
      </h2>
      <span v-if="info" class="text-xs text-ink-3"
        >{{ t('overview.cdps', { n: info.cdps.length }, info.cdps.length) }} ·
        {{ t('overview.sites', { n: info.sites.length }, info.sites.length) }}</span
      >
      <span class="rounded-full px-2.5 py-0.5 text-xs font-medium" :class="pill" data-testid="system-state">{{
        problems.length
          ? t('overview.problems', { n: problems.length }, problems.length)
          : `✓ ${t('overview.normal')}`
      }}</span>
      <RouterLink
        :to="boardPath(summary.code)"
        class="ml-auto rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90"
        >{{ t('overview.open') }} →</RouterLink
      >
    </header>

    <ul
      v-if="problems.length"
      class="border-b border-line px-4 py-2"
      :class="strip"
      data-testid="system-problems"
    >
      <li
        v-for="(p, i) in problems"
        :key="i"
        class="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 py-1 text-sm"
      >
        <span
          class="rounded px-1.5 py-0.5 text-[0.625rem] font-semibold uppercase"
          :class="SEVERITY_TONE[p.severity]"
          >{{ t(`problems.severity.${p.severity}`) }}</span
        >
        <RouterLink :to="p.link" class="hover:text-accent">{{ problemMessage(p, t) }}</RouterLink>
        <span v-if="p.params.since" class="num text-[0.6875rem] text-ink-3">{{
          t('problems.since', { time: formatUtc(String(p.params.since)) })
        }}</span>
      </li>
    </ul>

    <div class="grid lg:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)_minmax(0,1.5fr)]">
      <!-- right now -->
      <div class="flex min-w-0 flex-col gap-2.5 px-4 py-3.5" data-testid="system-now">
        <h3 class="flex items-baseline gap-2 text-xs font-semibold text-ink-2">
          {{ t('overview.now') }}
          <span v-if="status" class="num font-normal text-ink-3">{{
            t('common.asOf', { time: formatUtc(status.generated_at) })
          }}</span>
        </h3>
        <div v-if="status" class="flex flex-wrap gap-1.5">
          <span
            v-for="c in status.cdps"
            :key="c.code"
            class="inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-[0.8125rem]"
            :class="c.data_flow === 'not_producing' ? 'border-bad/50 font-medium text-bad' : 'border-line'"
          >
            <i class="h-2 w-2 rounded-full" :class="FLOW_DOT[c.data_flow]" aria-hidden="true" />
            {{ c.code }} · {{ t(`cdp.flow.${c.data_flow}`) }}
          </span>
        </div>
        <div v-else class="h-7 animate-pulse rounded bg-sunken" aria-busy="true" />
        <p class="flex flex-wrap items-baseline gap-x-2 text-sm">
          <span class="text-xs text-ink-3">{{ t('overview.lastData') }}</span>
          <span class="num" :class="stale ? 'font-medium text-warn' : ''">{{ formatUtc(lastData) }}</span>
          <span v-if="lastData" class="num text-xs" :class="stale ? 'text-warn' : 'text-ink-3'">{{
            ago(lastData)
          }}</span>
        </p>
        <p class="flex flex-wrap items-baseline gap-x-2 text-sm">
          <span class="text-xs text-ink-3">{{ t('overview.slaToday') }}</span>
          <span
            class="num font-semibold"
            :class="LEVEL_TEXT[figureLevel(summary.sla_today, display.thresholds)]"
            >{{ pct(summary.sla_today.pct, lc) }} %</span
          >
          <span class="num text-xs text-ink-3">{{
            t('common.validOfExpected', {
              valid: int(summary.sla_today.valid, lc),
              expected: int(summary.sla_today.expected, lc),
            })
          }}</span>
        </p>
        <div v-if="metar" class="flex flex-col gap-1" data-testid="latest-metar">
          <p class="flex flex-wrap items-baseline gap-x-2">
            <RouterLink
              :to="`${boardPath(summary.code)}/reports`"
              class="text-xs text-ink-3 hover:text-accent"
              >{{ t('overview.latestMetar') }}</RouterLink
            >
            <span class="num text-xs text-ink-3"
              >{{ formatUtc(metar.logged_at) }} · {{ ago(metar.logged_at) }}</span
            >
          </p>
          <p class="num rounded-md bg-sunken px-2.5 py-1.5 text-xs break-words text-ink-2">
            {{ metar.text }}
          </p>
        </div>
      </div>

      <!-- the month so far -->
      <div
        class="flex min-w-0 flex-col gap-3 border-t border-line px-4 py-3.5 lg:border-t-0 lg:border-l"
        data-testid="system-month"
      >
        <h3 class="flex items-baseline gap-2 text-xs font-semibold text-ink-2">
          {{ t('overview.monthSoFar', { month: monthName }) }}
          <span class="num font-normal text-ink-3">{{ t('overview.dayOf', progress) }}</span>
        </h3>
        <dl class="grid grid-cols-2 gap-3">
          <div>
            <dt class="text-xs text-ink-3">{{ t('overview.slaMonth') }}</dt>
            <dd class="num text-2xl font-semibold" :class="LEVEL_TEXT[slaLevel]">
              {{ pct(summary.sla_month.pct, lc) }}<span class="text-sm font-normal text-ink-3"> %</span>
            </dd>
            <dd class="num text-[0.6875rem] text-ink-3">
              {{
                t('overview.lost', {
                  lost: int(lostMinutes(summary.sla_month), lc),
                  expected: int(summary.sla_month.expected, lc),
                })
              }}<template v-if="month.data.value">
                ·
                {{
                  t('overview.outages', { n: month.data.value.slaOutages }, month.data.value.slaOutages)
                }}</template
              >
            </dd>
          </div>
          <div>
            <dt class="text-xs text-ink-3">{{ t('overview.olaMonth') }}</dt>
            <dd class="num text-2xl font-semibold" :class="LEVEL_TEXT[olaLevel]">
              {{ pct(summary.ola_month.pct, lc) }}<span class="text-sm font-normal text-ink-3"> %</span>
            </dd>
            <dd class="text-[0.6875rem] text-ink-3">{{ t('kpi.olaHint') }}</dd>
          </div>
        </dl>
        <MonthStrip
          v-if="month.data.value"
          :code="summary.code"
          :matrix="month.data.value.matrix"
          :now="now"
        />
        <p v-else-if="month.error.value" class="text-xs text-warn" role="alert">
          {{ t('common.error') }}
          <button type="button" class="icon-btn" @click="month.load()">{{ t('common.retry') }}</button>
        </p>
        <div v-else class="h-12 animate-pulse rounded bg-sunken" aria-busy="true" />
      </div>

      <!-- every site's components -->
      <div
        class="flex min-w-0 flex-col gap-2.5 border-t border-line px-4 py-3.5 lg:border-t-0 lg:border-l"
        data-testid="system-sites"
      >
        <h3 class="flex items-baseline gap-2 text-xs font-semibold text-ink-2">
          {{ t('overview.sitesTitle') }}
          <span v-if="status" class="num font-normal text-ink-3">{{
            t('site.componentsValid', { n: valid, total })
          }}</span>
        </h3>
        <div
          class="grid gap-2.5 sm:[grid-template-columns:repeat(var(--n),minmax(0,1fr))]"
          :style="{ '--n': Math.min(Math.max(sites.length, 1), 3) }"
        >
          <RouterLink
            v-for="s in sites"
            :key="s.slug"
            :to="sitePath(summary.code, s.slug)"
            class="flex min-w-0 flex-col gap-1.5 rounded-md border px-2.5 py-2 hover:bg-sunken/60"
            :class="s.online !== null && s.online < s.total ? 'border-warn/70' : 'border-line'"
            data-testid="site-card"
          >
            <span class="flex items-baseline gap-2 text-sm font-semibold">
              {{ s.name }}
              <span v-if="s.online !== null" class="num ml-auto text-[0.6875rem] font-normal text-ink-3"
                >{{ s.online }}/{{ s.total }}</span
              >
            </span>
            <span class="flex flex-wrap gap-1">
              <span
                v-for="c in s.components"
                :key="c.type"
                class="inline-flex items-center gap-1 rounded px-1.5 py-px text-[0.6875rem]"
                :class="CHIP[c.status].tone"
                :title="t(`status.${c.status}`)"
              >
                <i v-if="c.status === 'valid'" class="h-1.5 w-1.5 rounded-full bg-ok" aria-hidden="true" />
                <template v-else>{{ CHIP[c.status].sign }}</template>
                {{ c.type }}<template v-if="c.status !== 'valid'"> · {{ t(`status.${c.status}`) }}</template>
              </span>
            </span>
            <span v-if="s.month !== null" class="num text-[0.6875rem] text-ink-3">{{
              t('overview.siteMonth', { pct: pct(s.month, lc) })
            }}</span>
          </RouterLink>
        </div>
      </div>
    </div>
  </section>
</template>
