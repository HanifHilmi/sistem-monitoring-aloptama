<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import { api } from '@/api/client'
import type { SystemInfo, SystemSummary } from '@/api/types'
import { useLoader } from '@/composables/useLoader'
import { usePolling } from '@/composables/usePolling'
import type { Locale } from '@/i18n'
import { useDisplayStore } from '@/stores/display'
import { figureLevel, int, LEVEL_TEXT, pct } from '@/utils/format'
import { boardPath, sitePath } from '@/utils/paths'
import { formatUtc } from '@/utils/time'

// Dashboard: every system at a glance (AWOS CAT. III now; AWOS CAT. I and others later).
const { t, locale } = useI18n()
const lc = computed(() => locale.value as Locale)
const display = useDisplayStore()
const loader = useLoader<SystemSummary[]>(() => api.systems())
void loader.load()
usePolling(() => loader.load({ silent: true }), 60_000)

const infos = ref<Record<string, SystemInfo>>({})
watch(
  () => loader.data.value,
  async (list) => {
    for (const s of list ?? []) if (!infos.value[s.code]) infos.value[s.code] = await display.system(s.code)
  },
)
const STALE_MS = 5 * 60_000
const stale = (s: SystemSummary) =>
  !s.last_data_minute || Date.now() - Date.parse(s.last_data_minute) > STALE_MS
</script>

<template>
  <div class="flex flex-col gap-4">
    <header>
      <h1 class="text-xl font-semibold tracking-tight">{{ t('overview.title') }}</h1>
      <p class="text-sm text-ink-2">{{ t('overview.subtitle') }}</p>
    </header>

    <p v-if="loader.error.value" class="text-sm text-warn" role="alert">
      {{ t('common.error') }}
      <button type="button" class="icon-btn" @click="loader.load()">{{ t('common.retry') }}</button>
    </p>
    <div v-else-if="!loader.data.value" class="h-40 animate-pulse rounded-lg bg-sunken" aria-busy="true" />

    <div v-else class="grid gap-4 md:grid-cols-2">
      <article
        v-for="s in loader.data.value"
        :key="s.code"
        class="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4"
        :aria-label="s.name[lc]"
      >
        <header class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h2 class="text-base font-semibold">
            <RouterLink :to="boardPath(s.code)" class="hover:text-accent">{{ s.name[lc] }}</RouterLink>
          </h2>
          <span v-if="s.icao && !s.name[lc].includes(s.icao)" class="num text-xs text-ink-3">{{
            s.icao
          }}</span>
          <span
            class="ml-auto rounded px-1.5 py-0.5 text-[0.6875rem]"
            :class="s.problems ? 'bg-warn/15 text-warn' : 'bg-sunken text-ink-3'"
            >{{
              s.problems
                ? t('overview.problems', { n: int(s.problems, lc) }, s.problems)
                : t('overview.noProblems')
            }}</span
          >
        </header>

        <dl class="grid grid-cols-3 gap-3">
          <div>
            <dt class="text-[0.6875rem] text-ink-3">{{ t('overview.slaMonth') }}</dt>
            <dd
              class="num text-xl font-semibold"
              :class="LEVEL_TEXT[figureLevel(s.sla_month, display.thresholds)]"
            >
              {{ pct(s.sla_month.pct, lc) }}<span class="text-sm font-normal text-ink-3"> %</span>
            </dd>
          </div>
          <div>
            <dt class="text-[0.6875rem] text-ink-3">{{ t('overview.olaMonth') }}</dt>
            <dd class="num text-xl font-semibold">
              {{ pct(s.ola_month.pct, lc) }}<span class="text-sm font-normal text-ink-3"> %</span>
            </dd>
          </div>
          <div>
            <dt class="text-[0.6875rem] text-ink-3">{{ t('overview.slaToday') }}</dt>
            <dd
              class="num text-xl font-semibold"
              :class="LEVEL_TEXT[figureLevel(s.sla_today, display.thresholds)]"
            >
              {{ pct(s.sla_today.pct, lc) }}<span class="text-sm font-normal text-ink-3"> %</span>
            </dd>
          </div>
        </dl>

        <p class="num text-xs" :class="stale(s) ? 'font-medium text-warn' : 'text-ink-3'">
          {{ t('overview.lastData', { time: formatUtc(s.last_data_minute) }) }}
        </p>

        <div class="flex flex-wrap items-center gap-2 border-t border-line pt-3">
          <RouterLink
            :to="boardPath(s.code)"
            class="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-white hover:opacity-90"
            >{{ t('overview.open') }}</RouterLink
          >
          <RouterLink
            v-for="x in infos[s.code]?.sites ?? []"
            :key="x.slug"
            :to="sitePath(s.code, x.slug)"
            class="rounded-md border border-line px-2.5 py-1.5 text-sm text-ink-2 hover:bg-sunken hover:text-ink"
            >{{ x.name[lc] }}</RouterLink
          >
        </div>
      </article>
    </div>
  </div>
</template>
