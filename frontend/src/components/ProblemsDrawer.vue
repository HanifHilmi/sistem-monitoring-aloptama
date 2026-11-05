<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import type { Problem } from '@/api/types'
import { useLiveStore } from '@/stores/live'
import { formatUtc } from '@/utils/time'
import SidePanel from './SidePanel.vue'

defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: [] }>()
const live = useLiveStore()
const { t } = useI18n()

const TONE: Record<string, string> = {
  critical: 'bg-bad text-white',
  major: 'bg-bad/15 text-bad',
  minor: 'bg-warn/15 text-warn',
  info: 'bg-sunken text-ink-2',
}

function message(p: Problem): string {
  const params: Record<string, string | number> = {}
  for (const [k, v] of Object.entries(p.params))
    if (v !== null && v !== undefined) params[k === 'lag_min' ? 'lag' : k] = v
  return typeof params.n === 'number'
    ? t(`problems.code.${p.code}`, params, params.n)
    : t(`problems.code.${p.code}`, params)
}
// The API's links (/systems/{code}, /systems/{code}/sites/{slug}) are the app's own paths.
const link = (p: Problem) => p.link
</script>

<template>
  <SidePanel
    :open="open"
    :title="t('problems.title')"
    :subtitle="live.updatedAt ? t('common.asOf', { time: formatUtc(live.updatedAt) }) : undefined"
    @close="emit('close')"
  >
    <p v-if="live.error" class="mb-3 text-sm text-warn" role="alert">{{ t('live.unavailable') }}</p>
    <p v-if="!live.problems.length" class="text-sm text-ink-2">✓ {{ t('problems.noneLong') }}</p>
    <ul class="flex flex-col">
      <li v-for="(p, i) in live.problems" :key="i" class="flex items-start gap-3 border-b border-line py-2.5">
        <span
          class="mt-0.5 rounded px-1.5 py-0.5 text-[0.625rem] font-semibold uppercase"
          :class="TONE[p.severity]"
        >
          {{ t(`problems.severity.${p.severity}`) }}
        </span>
        <div class="min-w-0 flex-1">
          <RouterLink :to="link(p)" class="text-sm hover:text-accent" @click="emit('close')">{{
            message(p)
          }}</RouterLink>
          <p v-if="p.params.since" class="num text-[0.6875rem] text-ink-3">
            {{ t('problems.since', { time: formatUtc(String(p.params.since)) }) }}
          </p>
        </div>
      </li>
    </ul>
  </SidePanel>
</template>
