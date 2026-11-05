<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import type { Detection, FieldInfo } from '@/api/types'
import type { Locale } from '@/i18n'
import { formatDuration, formatRange } from '@/utils/flags'
import { evidenceText, ruleText } from '@/utils/rules'
import { formatUtc } from '@/utils/time'

// Detections touching a chart window or a day (FR-DQ-007): confirmed ones for everyone; suspect and rejected ones
// reach signed-in users only (the API leaves them out for the public). Admins get a link to the review queue.
const props = defineProps<{
  detections: Detection[]
  fields: Record<string, FieldInfo>
  canReview?: boolean
}>()
const { t, locale } = useI18n()
const lc = computed(() => locale.value as Locale)
const unit = (d: Detection) => props.fields[d.field]?.unit ?? null
</script>

<template>
  <ul class="flex flex-col gap-2" data-testid="detection-list">
    <li v-for="d in detections" :key="d.id" class="flex items-start gap-2 text-xs">
      <span
        class="mt-0.5 h-3 w-3 shrink-0 rounded-[2px]"
        :class="
          d.status === 'confirmed'
            ? 'border border-detect bg-detect/35'
            : d.status === 'suspect'
              ? 'border border-dashed border-detect bg-detect/10'
              : 'border border-dashed border-line-strong'
        "
        aria-hidden="true"
      />
      <span class="min-w-0 flex-1 leading-snug">
        <span class="font-medium text-ink">{{ t(`rules.type.${d.type}`) }} · {{ d.field }}</span>
        <span
          class="ml-1.5 rounded px-1 py-px text-[0.625rem] font-medium"
          :class="
            d.status === 'confirmed'
              ? 'bg-detect/15 text-detect'
              : d.status === 'suspect'
                ? 'border border-dashed border-detect/60 text-detect'
                : 'bg-sunken text-ink-3'
          "
          >{{ t(`detections.status.${d.status}`) }}</span
        >
        <span class="num block text-ink-2">
          {{ formatRange(d.start, d.end, lc) }} UTC · {{ formatDuration(d.minutes, t) }} ·
          {{ evidenceText(d.type, d.evidence, unit(d), lc, t) }}
        </span>
        <span class="block text-ink-3">
          {{ t('detections.rule', { rule: ruleText(d.type, d.params, unit(d), lc, t), v: d.rule_version }) }}
          <template v-if="!d.mandatory"> · {{ t('detections.optional') }}</template>
        </span>
        <span v-if="d.decided_by" class="block text-ink-3">
          {{ t(`detections.decidedBy.${d.status}`, { name: d.decided_by, time: formatUtc(d.decided_at) }) }}
          <template v-if="d.note"> · “{{ d.note }}”</template>
        </span>
      </span>
      <RouterLink
        v-if="canReview"
        :to="`/admin/review?status=${d.status}&id=${d.id}`"
        class="shrink-0 text-accent hover:underline"
        >{{ d.status === 'suspect' ? t('detections.review') : t('detections.open') }}</RouterLink
      >
    </li>
  </ul>
</template>
