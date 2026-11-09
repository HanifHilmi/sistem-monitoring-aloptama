<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import { api } from '@/api/client'
import type { ActiveAlarms, SystemInfo, SystemSummary } from '@/api/types'
import ActiveAlarmList from '@/components/alarms/ActiveAlarms.vue'
import { useLoader } from '@/composables/useLoader'
import { usePolling } from '@/composables/usePolling'
import type { Locale } from '@/i18n'
import { useDisplayStore } from '@/stores/display'
import { int } from '@/utils/format'
import { boardPath } from '@/utils/paths'

// The AWOS's own active alarms (FR-ALM-001), for signed-in users: how many, the first few, and the way to the
// alarm page. Each system that has an alarm viewer gets its own block.
const props = defineProps<{ systems: SystemSummary[] }>()
const { t, locale } = useI18n()
const lc = computed(() => locale.value as Locale)
const display = useDisplayStore()
const SHOWN = 2
const now = ref(Date.now())

const data = useLoader(async () => {
  const each = await Promise.all(
    props.systems.map(async (s) => {
      const [alarms, info] = await Promise.all([
        api.activeAlarms(s.code).catch(() => null),
        display.system(s.code).catch(() => null),
      ])
      return { code: s.code, name: s.name[lc.value], alarms, info }
    }),
  )
  return each.filter(
    (e): e is { code: string; name: string; alarms: ActiveAlarms; info: SystemInfo | null } => !!e.alarms,
  )
})
usePolling(() => {
  now.value = Date.now()
  return data.load({ silent: !!data.data.value })
}, 60_000)
const several = computed(() => (data.data.value?.length ?? 0) > 1)
</script>

<template>
  <section
    class="flex flex-col gap-2.5 rounded-lg border border-line bg-surface p-4"
    data-testid="card-alarms"
  >
    <h2 class="flex items-baseline gap-2 text-sm font-semibold">
      {{ t('alarms.title') }}
      <span class="ml-auto text-[0.6875rem] font-normal text-ink-3">{{ t('overview.signedInOnly') }}</span>
    </h2>
    <p v-if="data.error.value && !data.data.value" class="text-sm text-warn" role="alert">
      {{ t('common.error') }}
      <button type="button" class="icon-btn" @click="data.load()">{{ t('common.retry') }}</button>
    </p>
    <div v-else-if="!data.data.value" class="h-24 animate-pulse rounded bg-sunken" aria-busy="true" />
    <template v-else>
      <div v-for="s in data.data.value" :key="s.code" class="flex flex-col gap-1.5">
        <p v-if="several" class="text-xs font-semibold text-ink-2">{{ s.name }}</p>
        <p class="flex flex-wrap items-baseline gap-x-2">
          <span class="num text-xl font-semibold" :class="s.alarms.active.length ? 'text-bad' : ''">{{
            int(s.alarms.active.length, lc)
          }}</span>
          <span class="text-[0.8125rem] text-ink-2">{{
            s.alarms.active.length ? t('overview.alarmsCard.active') : t('alarms.noneActive')
          }}</span>
        </p>
        <ActiveAlarmList
          v-if="s.alarms.active.length"
          :alarms="s.alarms.active.slice(0, SHOWN)"
          :info="s.info"
          :now="now"
          compact
        />
        <p v-if="s.alarms.active.length > SHOWN" class="text-xs text-ink-3">
          {{ t('overview.alarmsCard.more', { n: s.alarms.active.length - SHOWN }) }}
        </p>
        <p v-if="s.alarms.not_cleared.length" class="text-xs text-ink-3">
          {{ t('alarms.notCleared.title', { n: s.alarms.not_cleared.length }, s.alarms.not_cleared.length) }}
        </p>
        <RouterLink :to="`${boardPath(s.code)}/alarms`" class="text-[0.8125rem] text-accent hover:underline"
          >{{ t('overview.alarmsCard.open') }} →</RouterLink
        >
      </div>
    </template>
  </section>
</template>
