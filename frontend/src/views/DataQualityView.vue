<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import { api, ApiProblem } from '@/api/client'
import type { DataQualitySummary, DqComponent, DqReason, SystemInfo } from '@/api/types'
import PeriodBar from '@/components/PeriodBar.vue'
import { usePeriodQuery } from '@/composables/useUrlState'
import type { Locale } from '@/i18n'
import { useAuthStore } from '@/stores/auth'
import { useDisplayStore } from '@/stores/display'
import { DEFAULT_SYSTEM } from '@/stores/live'
import { int, num } from '@/utils/format'
import { formatUtc } from '@/utils/time'

// FR-DQ-008: what manual flags and confirmed detections cost a period, by sensor and by reason. Public; the number
// of suspects waiting for review only for signed-in users (D7). The minutes are the outage list's, so they are
// already counted in every figure.
const props = withDefaults(defineProps<{ code?: string }>(), { code: DEFAULT_SYSTEM })
const { t, locale } = useI18n()
const lc = computed(() => locale.value as Locale)
const auth = useAuthStore()
const display = useDisplayStore()
const info = ref<SystemInfo | null>(null)
onMounted(async () => (info.value = await display.system(props.code)))

const period = usePeriodQuery()
const summary = ref<DataQualitySummary | null>(null)
const problem = ref<string | null>(null)
const loading = ref(false)
watch(
  () => [period.value.from.getTime(), period.value.to.getTime()],
  async () => {
    loading.value = true
    problem.value = null
    try {
      summary.value = await api.dataQuality(props.code, period.value.from, period.value.to)
    } catch (e) {
      summary.value = null
      problem.value = e instanceof ApiProblem ? e.code : 'network_error'
    } finally {
      loading.value = false
    }
  },
  { immediate: true },
)

const name = (site: string, type: string) => {
  const s = info.value?.sites.find((x) => x.slug === site)
  const c = s?.components.find((x) => x.type === type)
  return { site: s?.name[lc.value] ?? site, component: c?.name[lc.value] ?? type }
}
const reasonLabel = (r: DqReason) =>
  r.kind === 'flag' ? t(`flags.reason.${r.reason}`) : t('quality.rule', { type: t(`rules.type.${r.reason}`) })
/** "0.54 % of its minutes"; a sensor that lost a minute never reads 0.00 %. */
function shareLabel(c: DqComponent): string {
  const lost = c.flagged_minutes + c.detection_minutes
  if (!c.expected) return ''
  const pct = (lost / c.expected) * 100
  return t('quality.share', {
    pct: pct > 0 && pct < 0.01 ? `< ${num(0.01, lc.value, 2, true)}` : num(pct, lc.value, 2, true),
  })
}
const flagReasons = computed(() => summary.value?.reasons.filter((r) => r.kind === 'flag') ?? [])
const detectionReasons = computed(() => summary.value?.reasons.filter((r) => r.kind === 'detection') ?? [])
const widest = computed(() => Math.max(1, ...(summary.value?.reasons.map((r) => r.minutes) ?? [])))
const hours = (m: number) => (m >= 120 ? t('quality.hours', { h: num(m / 60, lc.value) }) : '')
</script>

<template>
  <div class="mx-auto flex w-full max-w-6xl flex-col gap-4 px-3 py-5 sm:px-5">
    <header class="flex flex-wrap items-end justify-between gap-3">
      <div class="max-w-3xl">
        <h1 class="text-lg font-semibold">{{ t('quality.title') }}</h1>
        <p class="text-sm text-ink-2">{{ t('quality.subtitle') }}</p>
      </div>
      <PeriodBar v-model="period" />
    </header>

    <p v-if="problem === 'period_too_long'" class="text-sm text-warn" role="alert">
      {{ t('quality.tooLong') }}
    </p>
    <p v-else-if="problem" class="text-sm text-warn" role="alert">{{ t('common.error') }}</p>
    <div v-else-if="!summary" class="h-60 animate-pulse rounded-lg bg-sunken" aria-busy="true" />
    <template v-else>
      <p v-if="summary.period.open" class="num text-xs text-ink-3">
        {{ t('quality.asOf', { time: formatUtc(summary.period.as_of) }) }}
      </p>

      <!-- totals -->
      <div class="grid gap-3 sm:grid-cols-3" :class="loading ? 'opacity-60' : ''">
        <section class="rounded-lg border border-line bg-surface px-4 py-3" data-testid="quality-flagged">
          <h2 class="text-xs text-ink-2">{{ t('quality.flagged') }}</h2>
          <p class="num mt-1 text-2xl font-semibold">
            {{ int(summary.flagged_minutes, lc) }}<span class="ml-1 text-sm font-normal text-ink-3">min</span>
          </p>
          <p class="text-xs text-ink-3">
            {{ t('quality.flags', { n: summary.flags }, summary.flags) }}
            <template v-if="hours(summary.flagged_minutes)"> · {{ hours(summary.flagged_minutes) }}</template>
          </p>
        </section>
        <section class="rounded-lg border border-line bg-surface px-4 py-3" data-testid="quality-detections">
          <h2 class="text-xs text-ink-2">{{ t('quality.detected') }}</h2>
          <p class="num mt-1 text-2xl font-semibold">
            {{ int(summary.detection_minutes, lc)
            }}<span class="ml-1 text-sm font-normal text-ink-3">min</span>
          </p>
          <p class="text-xs text-ink-3">
            {{ t('quality.detections', { n: summary.detections }, summary.detections) }}
            <template v-if="hours(summary.detection_minutes)">
              · {{ hours(summary.detection_minutes) }}</template
            >
          </p>
        </section>
        <section
          v-if="summary.pending_suspects !== null"
          class="rounded-lg border border-line bg-surface px-4 py-3"
          data-testid="quality-suspects"
        >
          <h2 class="text-xs text-ink-2">{{ t('quality.suspects') }}</h2>
          <p class="num mt-1 text-2xl font-semibold">{{ int(summary.pending_suspects, lc) }}</p>
          <p class="text-xs text-ink-3">
            {{ t('quality.suspectsNote') }}
            <RouterLink v-if="auth.isAdmin" to="/admin/review" class="text-accent hover:underline"
              >{{ t('quality.review') }} →</RouterLink
            >
          </p>
        </section>
      </div>

      <p
        v-if="!summary.components.length"
        class="rounded-lg border border-dashed border-line px-4 py-8 text-center text-sm text-ink-3"
        data-testid="quality-none"
      >
        {{ t('quality.none') }}
      </p>
      <template v-else>
        <!-- by sensor -->
        <section
          class="overflow-hidden rounded-lg border border-line bg-surface"
          :aria-label="t('quality.bySensor')"
        >
          <h2 class="border-b border-line px-4 py-2.5 text-sm font-semibold">{{ t('quality.bySensor') }}</h2>
          <ul data-testid="quality-components">
            <li
              v-for="c in summary.components"
              :key="`${c.site}:${c.component}`"
              class="flex flex-col gap-1.5 border-b border-line px-4 py-2.5 last:border-0 md:grid md:grid-cols-[minmax(0,14rem)_7rem_7rem_minmax(0,1fr)] md:items-start md:gap-x-4"
              data-testid="quality-component"
            >
              <p class="min-w-0 text-sm">
                <span class="block font-medium md:truncate">{{ name(c.site, c.component).component }}</span>
                <span class="block text-xs text-ink-3">{{ name(c.site, c.component).site }}</span>
              </p>
              <div class="grid grid-cols-2 gap-3 md:contents">
                <p class="num text-xs">
                  <span class="block text-ink-3 md:hidden">{{ t('quality.flaggedShort') }}</span>
                  <span :class="c.flagged_minutes ? 'text-ink' : 'text-ink-3'"
                    >{{ int(c.flagged_minutes, lc) }} min</span
                  >
                  <span class="block text-ink-3">{{ t('quality.flags', { n: c.flags }, c.flags) }}</span>
                </p>
                <p class="num text-xs">
                  <span class="block text-ink-3 md:hidden">{{ t('quality.detectedShort') }}</span>
                  <span :class="c.detection_minutes ? 'text-ink' : 'text-ink-3'"
                    >{{ int(c.detection_minutes, lc) }} min</span
                  >
                  <span class="block text-ink-3">{{
                    t('quality.detections', { n: c.detections }, c.detections)
                  }}</span>
                </p>
              </div>
              <div class="flex flex-wrap items-center gap-1.5">
                <span
                  v-for="r in c.reasons"
                  :key="`${r.kind}:${r.reason}`"
                  class="rounded border px-1.5 py-px text-[0.6875rem]"
                  :class="r.kind === 'flag' ? 'border-flag/40 bg-flag/10' : 'border-bad/30 bg-bad/10'"
                  >{{ reasonLabel(r) }} · <span class="num">{{ int(r.minutes, lc) }} min</span></span
                >
                <span class="num ml-auto text-[0.6875rem] text-ink-3">{{ shareLabel(c) }}</span>
              </div>
            </li>
          </ul>
        </section>

        <!-- by reason -->
        <div class="grid gap-3 md:grid-cols-2">
          <section
            v-for="g in [
              { key: 'flags', title: t('quality.byFlagReason'), rows: flagReasons, bar: 'bg-flag' },
              { key: 'detections', title: t('quality.byRule'), rows: detectionReasons, bar: 'bg-bad' },
            ]"
            :key="g.key"
            class="rounded-lg border border-line bg-surface px-4 py-3"
            :data-testid="`quality-${g.key}-reasons`"
          >
            <h2 class="mb-2 text-sm font-semibold">{{ g.title }}</h2>
            <p v-if="!g.rows.length" class="text-xs text-ink-3">{{ t('quality.noneOfKind') }}</p>
            <ul v-else class="flex flex-col gap-2">
              <li v-for="r in g.rows" :key="r.reason" class="text-xs">
                <p class="flex items-baseline justify-between gap-2">
                  <span>{{ reasonLabel(r) }}</span>
                  <span class="num text-ink-2"
                    >{{ int(r.minutes, lc) }} min ·
                    {{
                      t(g.key === 'flags' ? 'quality.flags' : 'quality.detections', { n: r.count }, r.count)
                    }}</span
                  >
                </p>
                <div class="mt-1 h-1.5 rounded-full bg-sunken">
                  <div
                    class="h-1.5 rounded-full"
                    :class="g.bar"
                    :style="{ width: `${(r.minutes / widest) * 100}%` }"
                  />
                </div>
              </li>
            </ul>
          </section>
        </div>
      </template>

      <p class="max-w-3xl text-xs text-ink-3">
        {{ t('quality.note') }}
        <RouterLink :to="`/systems/${code}/definitions`" class="text-accent hover:underline"
          >{{ t('quality.definitionsLink', { v: summary.definitions_version }) }} →</RouterLink
        >
      </p>
    </template>
  </div>
</template>
