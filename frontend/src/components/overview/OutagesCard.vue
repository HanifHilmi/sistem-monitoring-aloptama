<script setup lang="ts">
import { computed, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import { api } from '@/api/client'
import type { SystemInfo, SystemSummary } from '@/api/types'
import { useLoader } from '@/composables/useLoader'
import { usePolling } from '@/composables/usePolling'
import type { Locale } from '@/i18n'
import { useDisplayStore } from '@/stores/display'
import { formatDuration, formatRange } from '@/utils/flags'
import { int } from '@/utils/format'
import { largestOutages, outagePlace, type SystemOutage } from '@/utils/overview'
import { boardPath } from '@/utils/paths'
import { encodePeriod, floorMinute } from '@/utils/time'

// The largest outages of the last 7 days over every system (OLA scope: every component), as the board lists them.
const props = defineProps<{ systems: SystemSummary[] }>()
const { t, locale } = useI18n()
const lc = computed(() => locale.value as Locale)
const display = useDisplayStore()
const SHOWN = 4
const WEEK_MS = 7 * 86_400_000

const infos = shallowRef<Record<string, SystemInfo>>({})
watch(
  () => props.systems.map((s) => s.code).join(),
  async () => {
    for (const s of props.systems) {
      const i = await display.system(s.code).catch(() => null)
      if (i) infos.value = { ...infos.value, [s.code]: i }
    }
  },
  { immediate: true },
)

const data = useLoader(async () => {
  const to = floorMinute(new Date())
  const from = new Date(to.getTime() - WEEK_MS)
  const lists = await Promise.all(
    props.systems.map(async (s) => ({
      system: s.code,
      r: await api.outages(s.code, from, to, 'ola', SHOWN),
    })),
  )
  return { from, to, lists }
})
usePolling(() => data.load({ silent: !!data.data.value }), 300_000)

const total = computed(() => (data.data.value?.lists ?? []).reduce((n, l) => n + l.r.intervals_total, 0))
const minutes = computed(() =>
  (data.data.value?.lists ?? []).reduce((n, l) => n + l.r.availability.missing, 0),
)
const rows = computed(() =>
  largestOutages(
    (data.data.value?.lists ?? []).map((l) => ({ system: l.system, intervals: l.r.intervals })),
    SHOWN,
  ),
)
const several = computed(() => props.systems.length > 1)
const tag = (o: SystemOutage) => infos.value[o.system]?.name[lc.value] ?? o.system
const dayLink = (o: SystemOutage) => ({
  path: boardPath(o.system),
  query: { p: `day:${o.start.slice(0, 10)}` },
})
const weekLink = computed(() => {
  const d = data.data.value
  const first = props.systems[0]
  if (!d || !first || several.value) return null
  return {
    path: boardPath(first.code),
    query: { p: encodePeriod({ kind: 'custom', from: d.from, to: d.to }) },
  }
})
</script>

<template>
  <section
    class="flex flex-col gap-2.5 rounded-lg border border-line bg-surface p-4"
    data-testid="card-outages"
  >
    <h2 class="text-sm font-semibold">{{ t('overview.outagesCard.title') }}</h2>
    <p v-if="data.error.value && !data.data.value" class="text-sm text-warn" role="alert">
      {{ t('common.error') }}
      <button type="button" class="icon-btn" @click="data.load()">{{ t('common.retry') }}</button>
    </p>
    <div v-else-if="!data.data.value" class="h-24 animate-pulse rounded bg-sunken" aria-busy="true" />
    <template v-else>
      <p v-if="!total" class="text-sm text-ink-2">✓ {{ t('overview.outagesCard.none') }}</p>
      <template v-else>
        <p class="num text-xs text-ink-3">
          {{ t('outages.summary', { minutes: int(minutes, lc), n: int(total, lc) }, total) }}
        </p>
        <ul class="flex flex-col text-[0.8125rem]">
          <li v-for="(o, i) in rows" :key="i" class="border-t border-line first:border-t-0">
            <RouterLink
              :to="dayLink(o)"
              class="grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 py-1.5 hover:text-accent"
            >
              <span class="min-w-0"
                ><span v-if="several" class="mr-1 rounded bg-sunken px-1 text-[0.6875rem]">{{ tag(o) }}</span
                >{{ t(`outages.cause.${o.cause}`) }}</span
              >
              <span class="num text-right text-ink-2">{{ formatDuration(o.minutes, t) }}</span>
              <span class="num col-span-2 text-[0.6875rem] text-ink-3"
                >{{ formatRange(o.start, o.end, lc) }} ·
                {{ outagePlace(o, infos[o.system] ?? null, lc, t) }}</span
              >
            </RouterLink>
          </li>
        </ul>
      </template>
      <RouterLink v-if="weekLink" :to="weekLink" class="mt-auto text-[0.8125rem] text-accent hover:underline"
        >{{ t('overview.outagesCard.open') }} →</RouterLink
      >
    </template>
  </section>
</template>
