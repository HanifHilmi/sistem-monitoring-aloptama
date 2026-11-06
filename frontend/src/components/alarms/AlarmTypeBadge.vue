<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import type { AlarmType } from '@/api/types'

// Error or warning, as the AWOS classed it: a word and a mark, never colour alone (UX-005).
defineProps<{ type: AlarmType }>()
const { t } = useI18n()
</script>

<template>
  <span
    class="inline-flex shrink-0 items-center gap-1 rounded px-1.5 py-px text-[0.6875rem] font-semibold whitespace-nowrap"
    :class="type === 'error' ? 'bg-bad/12 text-bad' : 'bg-warn/15 text-ink'"
    data-testid="alarm-type"
    ><span aria-hidden="true">{{ type === 'error' ? '✕' : '!' }}</span
    >{{ t(`alarms.type.${type}`) }}</span
  >
</template>
