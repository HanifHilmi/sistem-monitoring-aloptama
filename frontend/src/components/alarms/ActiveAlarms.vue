<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ActiveAlarm, SystemInfo } from '@/api/types'
import type { Locale } from '@/i18n'
import { placeLabel, since, stateLabel } from '@/utils/alarms'
import { formatUtc } from '@/utils/time'
import AlarmTypeBadge from './AlarmTypeBadge.vue'

// Alarms whose latest change says active (FR-ALM-001), as the AWOS reported them. SIMOLA never acknowledges an
// alarm (FR-ALM-004): the state is the AWOS's own. "compact" drops the place and CDPs (a site page lists its own).
const props = defineProps<{
  alarms: ActiveAlarm[]
  info: SystemInfo | null
  compact?: boolean
  /** show when the latest change was logged instead of how long it has been active (no clear logged) */
  lastChange?: boolean
  now: number
}>()
const { t, te, locale } = useI18n()
const lc = computed(() => locale.value as Locale)
</script>

<template>
  <ul class="flex flex-col" data-testid="active-alarms">
    <li
      v-for="a in props.alarms"
      :key="a.name"
      class="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-0.5 border-b border-line py-2.5 last:border-0"
      data-testid="active-alarm"
    >
      <AlarmTypeBadge :type="a.type" class="mt-0.5 self-start" />
      <div class="min-w-0">
        <p class="text-sm">{{ a.message }}</p>
        <p class="flex flex-wrap gap-x-2 text-xs text-ink-2">
          <span class="num text-ink-3">{{ a.name }}</span>
          <span v-if="!compact">· {{ placeLabel(a.place, info, lc, t) }}</span>
        </p>
        <p class="num flex flex-wrap gap-x-2 text-[0.6875rem] text-ink-3">
          <span v-if="lastChange" :title="formatUtc(a.changed, { seconds: true })">{{
            t('alarms.lastLogged', { time: formatUtc(a.changed), ago: since(a.changed, now, t) })
          }}</span>
          <span v-else :title="formatUtc(a.since, { seconds: true })">{{
            t('alarms.activeFor', { since: formatUtc(a.since), for: since(a.since, now, t) })
          }}</span>
          <span>· {{ stateLabel(a.state, t, te) }}</span>
          <span v-if="!compact">· {{ a.cdps.join(' + ') }}</span>
        </p>
      </div>
    </li>
  </ul>
</template>
