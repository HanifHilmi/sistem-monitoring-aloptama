<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import { api } from '@/api/client'
import type { SystemSummary } from '@/api/types'
import { useLoader } from '@/composables/useLoader'
import { usePolling } from '@/composables/usePolling'
import type { Locale } from '@/i18n'
import { useDisplayStore } from '@/stores/display'
import { formatPct, LEVEL_TEXT, levelFor } from '@/utils/format'
import { formatUtc } from '@/utils/time'

const { t, locale } = useI18n()
const display = useDisplayStore()
const lc = computed(() => locale.value as Locale)
const loader = useLoader<SystemSummary[]>(() => api.systems())
usePolling(() => loader.load({ silent: loader.data.value !== null }), 60_000)
</script>

<template>
  <div class="space-y-4">
    <h1 class="text-xl font-semibold">{{ t('overview.title') }}</h1>
    <p v-if="loader.error.value" class="text-sm text-warn" role="alert">
      {{ t('common.error') }}
      <button type="button" class="btn-ghost" @click="loader.load()">{{ t('common.retry') }}</button>
    </p>
    <div v-if="!loader.data.value && loader.loading.value" class="h-40 animate-pulse rounded-lg bg-panel" />
    <div class="grid gap-4 md:grid-cols-2">
      <RouterLink
        v-for="s in loader.data.value ?? []"
        :key="s.code"
        :to="`/systems/${s.code}`"
        class="panel block space-y-3 transition-colors hover:border-accent"
      >
        <div class="flex items-baseline justify-between gap-2">
          <h2 class="text-lg font-semibold">{{ s.name[lc] }}</h2>
          <span class="font-mono text-xs text-muted">{{ s.icao }}</span>
        </div>
        <dl class="grid grid-cols-3 gap-2">
          <div>
            <dt class="text-xs text-muted">{{ t('overview.slaToday') }}</dt>
            <dd
              class="text-xl font-bold tabular-nums"
              :class="LEVEL_TEXT[levelFor(s.sla_today.pct, display.thresholds)]"
            >
              {{ formatPct(s.sla_today.pct, lc) }}
            </dd>
          </div>
          <div>
            <dt class="text-xs text-muted">{{ t('overview.slaMonth') }}</dt>
            <dd
              class="text-xl font-bold tabular-nums"
              :class="LEVEL_TEXT[levelFor(s.sla_month.pct, display.thresholds)]"
            >
              {{ formatPct(s.sla_month.pct, lc) }}
            </dd>
          </div>
          <div>
            <dt class="text-xs text-muted">{{ t('overview.olaMonth') }}</dt>
            <dd
              class="text-xl font-bold tabular-nums"
              :class="LEVEL_TEXT[levelFor(s.ola_month.pct, display.thresholds)]"
            >
              {{ formatPct(s.ola_month.pct, lc) }}
            </dd>
          </div>
        </dl>
        <p class="flex flex-wrap justify-between gap-2 text-xs text-muted">
          <span :class="s.problems ? 'text-warn' : 'text-good'">
            {{ s.problems ? t('problems.count', s.problems) : `✓ ${t('problems.none')}` }}
          </span>
          <span>{{ t('common.lastData') }}: {{ formatUtc(s.last_data_minute) }}</span>
        </p>
      </RouterLink>
    </div>
  </div>
</template>
