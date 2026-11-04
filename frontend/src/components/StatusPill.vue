<script setup lang="ts">
import { useI18n } from 'vue-i18n'

// Live component status (UX-002): dot + text, never colour alone.
defineProps<{ status: string }>()
const { t } = useI18n()
const DOT: Record<string, string> = {
  valid: 'bg-ok',
  field_missing: 'bg-warn',
  no_data: 'bg-bad',
  stale: 'bg-ink-3',
  not_in_service: 'bg-ink-3',
  unknown: 'bg-ink-3',
}
</script>

<template>
  <span class="inline-flex items-center gap-1.5 text-[0.6875rem] text-ink-2">
    <span class="h-2 w-2 rounded-full" :class="DOT[status] ?? 'bg-ink-3'" aria-hidden="true" />
    {{ t(`status.${status}`) }}
  </span>
</template>
