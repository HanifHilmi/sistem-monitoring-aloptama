<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import { api } from '@/api/client'
import type { KpiResponse, StatusResponse, SystemInfo } from '@/api/types'
import PeriodPicker from '@/components/PeriodPicker.vue'
import SensorCard from '@/components/SensorCard.vue'
import StatusChip from '@/components/StatusChip.vue'
import WindowPicker from '@/components/WindowPicker.vue'
import { useLoader } from '@/composables/useLoader'
import { usePolling } from '@/composables/usePolling'
import { usePeriodQuery, useWindowQuery } from '@/composables/useUrlState'
import type { Locale } from '@/i18n'
import { useDisplayStore } from '@/stores/display'
import { useProblemsStore } from '@/stores/problems'
import { formatInt, formatPct, LEVEL_TEXT, levelFor } from '@/utils/format'
import { encodePeriod, formatUtc, isOpen, windowFromPreset } from '@/utils/time'

const props = defineProps<{ code: string; slug: string }>()
const { t, locale } = useI18n()
const lc = computed(() => locale.value as Locale)
const display = useDisplayStore()
const problems = useProblemsStore()
const period = usePeriodQuery()
const chartWindow = useWindowQuery()

const info = ref<SystemInfo | null>(null)
onMounted(async () => {
  problems.systemCode = props.code
  info.value = await display.system(props.code)
})
const site = computed(() => info.value?.sites.find((s) => s.slug === props.slug) ?? null)

const kpis = useLoader<KpiResponse>(() => api.kpis(props.code, period.value.from, period.value.to))
const status = useLoader<StatusResponse>(() => api.status(props.code))
watch(
  () => encodePeriod(period.value),
  () => kpis.load(),
  { immediate: true },
)

// Rolling chart windows move forward with time; refresh charts every 60 s (FR-DSH-011).
const refreshKey = ref(0)
usePolling(() => {
  void status.load({ silent: status.data.value !== null })
}, 30_000)
usePolling(() => {
  if (chartWindow.value.preset !== 'custom') {
    chartWindow.value = windowFromPreset(chartWindow.value.preset)
  }
  refreshKey.value++
  if (isOpen(period.value) && kpis.data.value) void kpis.load({ silent: true })
}, 60_000)

const siteKpi = computed(() => kpis.data.value?.sites.find((s) => s.slug === props.slug) ?? null)
const siteLive = computed(() => status.data.value?.sites.find((s) => s.slug === props.slug) ?? null)
const componentStatus = (type: string) => siteLive.value?.components.find((c) => c.type === type)?.status
</script>

<template>
  <div class="space-y-5">
    <nav class="text-sm text-muted">
      <RouterLink :to="`/systems/${code}`" class="hover:underline">‹ {{ info?.name[lc] ?? code }}</RouterLink>
    </nav>
    <p v-if="info && !site" class="text-bad" role="alert">{{ t('site.notFound') }}</p>

    <template v-if="site">
      <header class="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 class="text-xl font-semibold">{{ site.name[lc] }}</h1>
          <p class="text-xs text-muted">
            {{ t('common.lastData') }}: {{ formatUtc(siteLive?.last_data_minute) }}
            <template v-if="siteLive">
              ·
              {{
                t('site.componentsValid', { n: siteLive.components_online, total: siteLive.components_total })
              }}
            </template>
          </p>
        </div>
        <PeriodPicker v-model="period" />
      </header>

      <section class="panel" :aria-label="t('site.components')">
        <div class="mb-3 flex flex-wrap items-baseline justify-between gap-2">
          <h2 class="label">{{ t('site.components') }}</h2>
          <span
            class="text-2xl font-bold tabular-nums"
            :class="LEVEL_TEXT[levelFor(siteKpi?.availability.pct, display.thresholds)]"
          >
            {{ formatPct(siteKpi?.availability.pct, lc) }}
          </span>
        </div>
        <ul class="divide-y divide-border" :class="kpis.loading.value ? 'opacity-60' : ''">
          <li
            v-for="c in site.components"
            :key="c.type"
            class="flex flex-wrap items-center justify-between gap-2 py-2"
          >
            <div class="flex items-center gap-2">
              <StatusChip
                :status="componentStatus(c.type) ?? 'unknown'"
                :label="t(`status.${componentStatus(c.type) ?? 'unknown'}`)"
                compact
              />
              <span class="text-sm">{{ c.is_dcp ? t('site.dcp') : c.name[lc] }}</span>
            </div>
            <div class="flex items-baseline gap-3 text-sm tabular-nums">
              <span class="text-xs text-muted">
                {{
                  t('common.missingMinutes', {
                    n: formatInt(
                      siteKpi?.components.find((x) => x.type === c.type)?.availability.missing,
                      lc,
                    ),
                  })
                }}
              </span>
              <span
                class="w-20 text-right font-semibold"
                :class="
                  LEVEL_TEXT[
                    levelFor(
                      siteKpi?.components.find((x) => x.type === c.type)?.availability.pct,
                      display.thresholds,
                    )
                  ]
                "
              >
                {{ formatPct(siteKpi?.components.find((x) => x.type === c.type)?.availability.pct, lc) }}
              </span>
            </div>
          </li>
        </ul>
      </section>

      <section :aria-label="t('site.sensors')">
        <div class="mb-2 flex flex-wrap items-center justify-between gap-2">
          <h2 class="label">{{ t('site.sensors') }}</h2>
          <WindowPicker v-model="chartWindow" />
        </div>
        <div class="grid gap-3 lg:grid-cols-2">
          <SensorCard
            v-for="c in site.components.filter((x) => !x.is_dcp)"
            :key="c.type"
            :system-code="code"
            :site-slug="slug"
            :component="c"
            :fields="info!.fields"
            :window="chartWindow"
            :status="componentStatus(c.type)"
            :refresh-key="refreshKey"
          />
        </div>
      </section>
    </template>
  </div>
</template>
