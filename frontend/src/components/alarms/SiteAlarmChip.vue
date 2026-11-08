<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import type { ActiveAlarm, SystemInfo } from '@/api/types'
import Dropdown from '@/components/Dropdown.vue'
import type { Locale } from '@/i18n'
import { since, stateLabel } from '@/utils/alarms'
import { formatUtc } from '@/utils/time'
import AlarmTypeBadge from './AlarmTypeBadge.vue'

// A site's active AWOS alarms (FR-ALM-003, signed-in users) as a small chip in the site's status line; the list
// opens under it. Red when one of them is an error, amber for warnings only.
const props = defineProps<{
  alarms: ActiveAlarm[]
  info: SystemInfo | null
  code: string
  slug: string
  now: number
}>()
const { t, te, locale } = useI18n()
const lc = computed(() => locale.value as Locale)
const open = ref(false)
const errors = computed(() => props.alarms.filter((a) => a.type === 'error').length)
const site = computed(() => props.info?.sites.find((s) => s.slug === props.slug) ?? null)
/** The sensor's name; the whole site or the station when the alarm is not on one sensor. */
function where(a: ActiveAlarm): string {
  if (a.place.kind === 'component') {
    const c = site.value?.components.find((x) => x.type === a.place.component)
    return c?.name[lc.value] ?? a.place.component ?? ''
  }
  return a.place.kind === 'site' ? (site.value?.name[lc.value] ?? '') : t(`alarms.place.${a.place.kind}`)
}
</script>

<template>
  <Dropdown
    v-model:open="open"
    role="dialog"
    :label="t('alarms.atSite')"
    panel-class="w-[26rem] max-w-[calc(100vw-1rem)] p-1"
  >
    <template #trigger="{ toggle }">
      <button
        type="button"
        class="flex items-center gap-1 rounded-full border px-2 py-px text-[0.6875rem] font-medium"
        :class="errors ? 'border-bad/40 bg-bad/10 text-bad' : 'border-warn/50 bg-warn/15 text-ink'"
        aria-haspopup="dialog"
        :aria-expanded="open"
        data-testid="site-alarms"
        @click="toggle"
      >
        <span aria-hidden="true">⚠</span>
        {{ t('alarms.chip', { n: alarms.length }, alarms.length) }}
        <span class="text-[0.5625rem]" aria-hidden="true">▾</span>
      </button>
    </template>
    <ul class="flex max-h-80 flex-col overflow-y-auto" data-testid="site-alarm-list">
      <li
        v-for="a in alarms"
        :key="a.name"
        class="flex items-start gap-2 rounded-md px-2.5 py-2 hover:bg-sunken"
        :title="a.name"
        data-testid="active-alarm"
      >
        <AlarmTypeBadge :type="a.type" class="mt-px" />
        <span class="min-w-0 flex-1">
          <span class="block text-sm leading-snug">{{ a.message }}</span>
          <span class="num block text-[0.6875rem] text-ink-3">
            {{ where(a) }} ·
            <span :title="formatUtc(a.since, { seconds: true })">{{ since(a.since, now, t) }}</span>
            · {{ stateLabel(a.state, t, te) }}
          </span>
        </span>
      </li>
    </ul>
    <RouterLink
      :to="{ path: `/systems/${code}/alarms`, query: { tab: 'history', scope: `site:${slug}` } }"
      class="mt-1 block border-t border-line px-2.5 py-2 text-xs text-accent hover:underline"
      >{{ t('alarms.historyLink') }} →</RouterLink
    >
  </Dropdown>
</template>
