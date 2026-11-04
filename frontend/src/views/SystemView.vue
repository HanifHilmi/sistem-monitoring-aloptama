<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { api } from '@/api/client'
import type { KpiResponse, StatusResponse, SystemInfo } from '@/api/types'
import AvailabilityCalendar from '@/components/AvailabilityCalendar.vue'
import CdpPanel from '@/components/CdpPanel.vue'
import HistoryChart from '@/components/HistoryChart.vue'
import KpiTile from '@/components/KpiTile.vue'
import PeriodPicker from '@/components/PeriodPicker.vue'
import SiteCard from '@/components/SiteCard.vue'
import { useLoader } from '@/composables/useLoader'
import { usePolling } from '@/composables/usePolling'
import { usePeriodQuery } from '@/composables/useUrlState'
import type { Locale } from '@/i18n'
import { useDisplayStore } from '@/stores/display'
import { useProblemsStore } from '@/stores/problems'
import { encodePeriod, formatUtc, isOpen, periodContaining } from '@/utils/time'

const props = defineProps<{ code: string }>()
const { t, locale } = useI18n()
const lc = computed(() => locale.value as Locale)
const display = useDisplayStore()
const problems = useProblemsStore()
const router = useRouter()
const period = usePeriodQuery()

const info = ref<SystemInfo | null>(null)
const infoError = ref(false)
onMounted(async () => {
  problems.systemCode = props.code
  try {
    info.value = await display.system(props.code)
  } catch {
    infoError.value = true
  }
})

const kpis = useLoader<KpiResponse>(() => api.kpis(props.code, period.value.from, period.value.to))
const status = useLoader<StatusResponse>(() => api.status(props.code))
watch(
  () => encodePeriod(period.value),
  () => kpis.load(),
  { immediate: true },
)
usePolling(() => status.load({ silent: status.data.value !== null }), 30_000)
usePolling(() => {
  if (isOpen(period.value) && kpis.data.value) void kpis.load({ silent: true })
}, 60_000)

const periodNote = computed(() => {
  const k = kpis.data.value
  if (!k) return ''
  return k.period.open ? `${t('common.soFar')}, ${t('common.asOf', { time: formatUtc(k.period.as_of) })}` : ''
})

const stale = computed(() => status.data.value?.ingestion_stale)

function openDay(day: string) {
  void router.push({ query: { p: encodePeriod(periodContaining('day', new Date(`${day}T00:00:00Z`))) } })
}
</script>

<template>
  <div class="space-y-5">
    <header class="flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 class="text-xl font-semibold">{{ info?.name[lc] ?? code }}</h1>
        <p class="text-xs text-muted">
          {{ t('common.lastData') }}: {{ formatUtc(status.data.value?.last_data_minute) }}
          <template v-if="periodNote"> · {{ periodNote }}</template>
        </p>
      </div>
      <PeriodPicker v-model="period" />
    </header>

    <p v-if="infoError" class="text-sm text-bad" role="alert">{{ t('common.error') }}</p>
    <p
      v-if="stale"
      class="rounded border border-warn/40 bg-warn/10 px-3 py-2 text-sm text-warn"
      role="status"
    >
      {{ t('common.stale', { time: formatUtc(status.updatedAt.value) }) }}
    </p>
    <p v-if="kpis.error.value" class="text-sm text-warn" role="alert">
      {{ t('common.error') }}
      <button type="button" class="btn-ghost" @click="kpis.load()">{{ t('common.retry') }}</button>
    </p>
    <p v-if="kpis.data.value && kpis.data.value.sla.expected === 0" class="text-sm text-muted">
      {{ t('common.noCoverage') }}
    </p>

    <section
      class="grid gap-3 sm:grid-cols-3"
      :class="kpis.loading.value ? 'opacity-60' : ''"
      aria-live="polite"
    >
      <KpiTile
        big
        :title="t('kpi.sla')"
        :hint="t('kpi.slaHint')"
        :pct="kpis.data.value?.sla.pct"
        :counts="kpis.data.value?.sla"
      />
      <KpiTile big :title="t('kpi.ola')" :hint="t('kpi.olaHint')" :pct="kpis.data.value?.ola.pct" />
      <KpiTile
        :title="t('kpi.pooled')"
        :hint="t('kpi.pooledHint')"
        :pct="kpis.data.value?.pooled.pct"
        :counts="kpis.data.value?.pooled"
      />
    </section>

    <CdpPanel :kpis="kpis.data.value" :status="status.data.value" />

    <section v-if="info" :aria-label="t('site.title')">
      <h2 class="label mb-2">{{ t('site.title') }}</h2>
      <div class="grid gap-3 md:grid-cols-3">
        <SiteCard
          v-for="s in info.sites"
          :key="s.slug"
          :system-code="code"
          :site="s"
          :availability="kpis.data.value?.sites.find((x) => x.slug === s.slug)?.availability ?? null"
          :live="status.data.value?.sites.find((x) => x.slug === s.slug) ?? null"
        />
      </div>
    </section>

    <AvailabilityCalendar :system-code="code" :cdps="info?.cdps.map((c) => c.code) ?? []" @day="openDay" />
    <HistoryChart :system-code="code" :period="period" />
  </div>
</template>
