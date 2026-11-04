<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { KpiResponse, StatusResponse } from '@/api/types'
import type { Locale } from '@/i18n'
import { useDisplayStore } from '@/stores/display'
import { formatInt, formatPct, LEVEL_TEXT, levelFor } from '@/utils/format'
import { formatUtc } from '@/utils/time'
import StatusChip from './StatusChip.vue'

const props = defineProps<{ kpis: KpiResponse | null; status: StatusResponse | null }>()
const { t, locale } = useI18n()
const display = useDisplayStore()
const lc = computed(() => locale.value as Locale)

const rows = computed(() =>
  (props.status?.cdps ?? props.kpis?.cdps ?? []).map((c) => ({
    code: c.code,
    live: props.status?.cdps.find((s) => s.code === c.code) ?? null,
    period: props.kpis?.cdps.find((k) => k.code === c.code) ?? null,
  })),
)
</script>

<template>
  <section :aria-label="t('cdp.title')">
    <h2 class="label mb-2">{{ t('cdp.title') }}</h2>
    <div class="grid gap-3 sm:grid-cols-2">
      <article v-for="r in rows" :key="r.code" class="panel">
        <header class="mb-2 flex flex-wrap items-center justify-between gap-2">
          <h3 class="font-mono text-base font-semibold">{{ r.code }}</h3>
          <div class="flex flex-wrap gap-1">
            <StatusChip v-if="r.live" :status="r.live.data_flow" :label="t(`cdp.flow.${r.live.data_flow}`)" />
            <StatusChip
              v-if="r.live"
              :status="r.live.reachability"
              :label="t(`cdp.reach.${r.live.reachability}`)"
            />
          </div>
        </header>
        <dl class="grid grid-cols-3 gap-2 text-xs">
          <div>
            <dt class="text-muted" :title="t('kpi.uptimeHint')">{{ t('kpi.uptime') }}</dt>
            <dd
              class="text-base font-semibold tabular-nums"
              :class="LEVEL_TEXT[levelFor(r.period?.uptime.pct, display.thresholds)]"
              :title="
                r.period
                  ? t('common.validOfExpected', {
                      valid: formatInt(r.period.uptime.valid, lc),
                      expected: formatInt(r.period.uptime.expected, lc),
                    })
                  : undefined
              "
            >
              {{ formatPct(r.period?.uptime.pct, lc) }}
            </dd>
          </div>
          <div>
            <dt class="text-muted" :title="t('kpi.reachabilityHint')">{{ t('kpi.reachability') }}</dt>
            <dd class="text-base font-semibold text-text tabular-nums">
              {{
                r.period?.reachability.pct === null || r.period?.reachability.pct === undefined
                  ? t('common.notMeasured')
                  : formatPct(r.period.reachability.pct, lc)
              }}
            </dd>
            <dd v-if="r.period?.reachability.probe_coverage_pct != null" class="text-muted">
              {{ t('kpi.probeCoverage', { pct: formatPct(r.period.reachability.probe_coverage_pct, lc) }) }}
            </dd>
            <dd v-if="r.period?.reachability.legacy_minutes" class="text-muted">{{ t('common.legacy') }}</dd>
          </div>
          <div>
            <dt class="text-muted">{{ t('common.lastData') }}</dt>
            <dd class="font-medium">{{ formatUtc(r.live?.last_data_minute) }}</dd>
          </div>
        </dl>
      </article>
    </div>
  </section>
</template>
