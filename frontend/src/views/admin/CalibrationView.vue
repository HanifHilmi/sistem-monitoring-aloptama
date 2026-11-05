<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '@/api/client'
import { CALIBRATION_STATUSES, type CalibrationStatus, type ComponentRow } from '@/api/types'
import ComponentPanel from '@/components/records/ComponentPanel.vue'
import CalibrationChip from '@/components/records/CalibrationChip.vue'
import SidePanel from '@/components/SidePanel.vue'
import { useLoader } from '@/composables/useLoader'
import type { Locale } from '@/i18n'
import { DEFAULT_SYSTEM } from '@/stores/live'

// Calibration (FR-REG-005, J5): every sensor by when it falls due: overdue first, then due soon, unknown, OK.
// Recording a calibration opens the sensor's calibration tab.
const { t, locale } = useI18n()
const lc = computed(() => locale.value as Locale)
const loader = useLoader<ComponentRow[]>(() => api.components(DEFAULT_SYSTEM))
void loader.load()

const ORDER: Record<CalibrationStatus, number> = { overdue: 0, due_soon: 1, unknown: 2, ok: 3 }
const filter = ref<CalibrationStatus | ''>('')
const rows = computed(() =>
  (loader.data.value ?? [])
    .filter((c) => !c.is_dcp && (!filter.value || c.calibration.status === filter.value))
    .sort(
      (a, b) =>
        ORDER[a.calibration.status] - ORDER[b.calibration.status] ||
        (a.calibration.next_due ?? '9999').localeCompare(b.calibration.next_due ?? '9999') ||
        a.id - b.id,
    ),
)
const counts = computed(() => {
  const out = Object.fromEntries(CALIBRATION_STATUSES.map((s) => [s, 0])) as Record<CalibrationStatus, number>
  for (const c of loader.data.value ?? []) if (!c.is_dcp) out[c.calibration.status]++
  return out
})
const open = ref<number | null>(null)
const openRow = computed(() => loader.data.value?.find((c) => c.id === open.value) ?? null)
</script>

<template>
  <div class="flex flex-col gap-4">
    <header class="max-w-2xl">
      <h2 class="text-base font-semibold">{{ t('calibration.title') }}</h2>
      <p class="text-sm text-ink-2">{{ t('calibration.subtitle') }}</p>
    </header>

    <div class="seg self-start" role="group" :aria-label="t('calibration.filter')">
      <button type="button" :aria-pressed="filter === ''" @click="filter = ''">
        {{ t('calibration.all') }}
      </button>
      <button
        v-for="s in CALIBRATION_STATUSES"
        :key="s"
        type="button"
        :aria-pressed="filter === s"
        @click="filter = s"
      >
        {{ t(`calibration.status.${s}`) }} <span class="num text-ink-3">{{ counts[s] }}</span>
      </button>
    </div>

    <p v-if="loader.error.value" class="text-sm text-warn" role="alert">{{ t('common.error') }}</p>
    <div v-else-if="!loader.data.value" class="h-60 animate-pulse rounded-lg bg-sunken" aria-busy="true" />
    <section
      v-else
      class="overflow-hidden rounded-lg border border-line bg-surface"
      :aria-label="t('calibration.title')"
    >
      <div
        class="hidden grid-cols-[minmax(0,1.6fr)_7rem_9rem_minmax(0,1fr)_auto] gap-3 border-b border-line bg-sunken/60 px-4 py-2 text-xs text-ink-3 md:grid"
      >
        <span>{{ t('review.component') }}</span>
        <span>{{ t('calibration.last') }}</span>
        <span>{{ t('calibration.nextDueLabel') }}</span>
        <span>{{ t('calibration.status.label') }}</span>
        <span />
      </div>
      <ul>
        <li
          v-for="c in rows"
          :key="c.id"
          class="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 border-b border-line px-4 py-2.5 last:border-0 md:grid-cols-[minmax(0,1.6fr)_7rem_9rem_minmax(0,1fr)_auto]"
          data-testid="calibration-row"
        >
          <span class="min-w-0 text-sm">
            {{ c.site_name[lc] }} · {{ c.name[lc] }}
            <span class="num block text-xs text-ink-3">{{
              [c.meta.manufacturer, c.meta.model].filter(Boolean).join(' ')
            }}</span>
          </span>
          <span class="num text-xs text-ink-2 max-md:hidden">{{ c.calibration.last ?? '—' }}</span>
          <span
            class="num text-xs max-md:hidden"
            :class="c.calibration.status === 'overdue' ? 'text-bad' : ''"
            >{{ c.calibration.next_due ?? '—' }}</span
          >
          <span class="max-md:col-start-1 max-md:row-start-2"
            ><CalibrationChip :calibration="c.calibration"
          /></span>
          <button
            type="button"
            class="btn py-1 text-xs max-md:col-start-2 max-md:row-span-2 max-md:row-start-1"
            @click="open = c.id"
          >
            {{ t('calibration.record') }}
          </button>
        </li>
      </ul>
    </section>
    <p class="text-xs text-ink-3">{{ t('calibration.windowNote') }}</p>

    <SidePanel
      :open="openRow !== null"
      :title="openRow ? openRow.name[lc] : ''"
      :subtitle="openRow ? `${openRow.site_name[lc]} · ${openRow.type}` : undefined"
      @close="open = null"
    >
      <ComponentPanel
        v-if="openRow"
        :key="openRow.id"
        :component="openRow"
        tab="calibration"
        @changed="loader.load({ silent: true })"
      />
    </SidePanel>
  </div>
</template>
