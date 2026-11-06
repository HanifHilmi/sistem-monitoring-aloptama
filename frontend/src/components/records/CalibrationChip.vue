<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { CalibrationSummary } from '@/api/types'

// Calibration status of a sensor (FR-REG-005): overdue, due soon, OK or unknown, with the days left, and a
// "certificate pending" mark while the latest calibration's document is not validated yet. Words and a mark,
// never colour alone (UX-005).
const props = defineProps<{ calibration: CalibrationSummary; compact?: boolean }>()
const { t } = useI18n()
const TONE = {
  overdue: 'border-bad/40 bg-bad/10 text-bad',
  due_soon: 'border-warn/50 bg-warn/10 text-ink',
  ok: 'border-ok/40 bg-ok/10 text-ok',
  unknown: 'border-line bg-sunken text-ink-3',
}
const MARK = { overdue: '!', due_soon: '◷', ok: '✓', unknown: '?' }
const text = computed(() => {
  const c = props.calibration
  const n = Math.abs(c.days_left ?? 0)
  if (c.status === 'overdue') return t('calibration.chip.overdue', { n }, n)
  if (c.status === 'due_soon')
    return n ? t('calibration.chip.dueSoon', { n }, n) : t('calibration.chip.dueToday')
  if (c.status === 'ok') return props.compact ? t('calibration.status.ok') : t('calibration.chip.ok')
  return t('calibration.chip.unknown')
})
</script>

<template>
  <span class="inline-flex shrink-0 flex-wrap items-center gap-1">
    <span
      class="inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-px text-[0.6875rem] whitespace-nowrap"
      :class="TONE[calibration.status]"
      :title="calibration.next_due ? t('calibration.nextDue', { date: calibration.next_due }) : undefined"
      data-testid="calibration-chip"
    >
      <span aria-hidden="true" class="font-semibold">{{ MARK[calibration.status] }}</span>
      {{ text }}
    </span>
    <span
      v-if="calibration.pending"
      class="inline-flex shrink-0 items-center gap-1 rounded-full border border-dashed border-warn/60 px-2 py-px text-[0.6875rem] whitespace-nowrap text-ink-2"
      :title="t('calibration.pendingHint')"
      data-testid="certificate-pending"
    >
      <span aria-hidden="true">…</span>{{ t('calibration.pending') }}
    </span>
  </span>
</template>
