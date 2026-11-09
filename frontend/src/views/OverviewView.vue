<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '@/api/client'
import type { SystemSummary } from '@/api/types'
import AlarmsCard from '@/components/overview/AlarmsCard.vue'
import CalibrationCard from '@/components/overview/CalibrationCard.vue'
import OutagesCard from '@/components/overview/OutagesCard.vue'
import ReportCard from '@/components/overview/ReportCard.vue'
import SystemPanel from '@/components/overview/SystemPanel.vue'
import { useLoader } from '@/composables/useLoader'
import { usePolling } from '@/composables/usePolling'
import { useAuthStore } from '@/stores/auth'
import { formatUtc } from '@/utils/time'

// Dashboard (FR-DSH-001): one panel per system (right now, the month so far, its sites), then cards that cover
// every system (outages, calibration; alarms and last month's report for signed-in users). Only configured
// systems are shown, never placeholders: a new system adds a panel and its share of each card.
const { t } = useI18n()
const auth = useAuthStore()
void auth.load()
const loader = useLoader<SystemSummary[]>(() => api.systems())
const now = ref(new Date())
usePolling(() => {
  now.value = new Date()
  return loader.load({ silent: !!loader.data.value })
}, 60_000)
</script>

<template>
  <div class="flex flex-col gap-4">
    <header class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
      <h1 class="text-xl font-semibold tracking-tight">{{ t('overview.title') }}</h1>
      <p class="text-sm text-ink-2">{{ t('overview.subtitle') }}</p>
      <p v-if="loader.updatedAt.value" class="num w-full text-xs text-ink-3 sm:ml-auto sm:w-auto">
        {{ t('overview.updated', { time: formatUtc(loader.updatedAt.value) }) }}
      </p>
    </header>

    <p v-if="loader.error.value && !loader.data.value" class="text-sm text-warn" role="alert">
      {{ t('common.error') }}
      <button type="button" class="icon-btn" @click="loader.load()">{{ t('common.retry') }}</button>
    </p>
    <div v-else-if="!loader.data.value" class="h-72 animate-pulse rounded-lg bg-sunken" aria-busy="true" />

    <template v-else>
      <SystemPanel v-for="s in loader.data.value" :key="s.code" :summary="s" :now="now" />
      <div class="grid gap-4 md:grid-cols-2" :class="auth.canView ? 'xl:grid-cols-4' : ''">
        <OutagesCard :systems="loader.data.value" />
        <CalibrationCard :systems="loader.data.value" />
        <template v-if="auth.canView">
          <AlarmsCard :systems="loader.data.value" />
          <ReportCard :systems="loader.data.value" />
        </template>
      </div>
    </template>
  </div>
</template>
