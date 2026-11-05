<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '@/api/client'
import type { Detection, SeriesResponse, SystemInfo } from '@/api/types'
import { useLoader } from '@/composables/useLoader'
import type { Locale } from '@/i18n'
import { formatDays, formatDuration, formatRange } from '@/utils/flags'
import { evidenceText, ruleText } from '@/utils/rules'
import { formatUtc } from '@/utils/time'
import FieldChart from '../FieldChart.vue'

// One detection under review (FR-DQ-004, J3): the field's chart around it, what the rule saw, the rule as it was
// when it fired, and what confirming would change. Confirm or reject with an optional note; a decision can be
// reversed later (audited).
const props = defineProps<{
  detection: Detection
  info: SystemInfo
  position: number
  total: number
  busy?: boolean
}>()
const emit = defineEmits<{
  decide: [decision: 'confirm' | 'reject', note: string]
  prev: []
  next: []
}>()
const { t, locale } = useI18n()
const lc = computed(() => locale.value as Locale)
const note = ref('')
watch(
  () => props.detection.id,
  () => (note.value = ''),
)

const d = computed(() => props.detection)
const site = computed(() => props.info.sites.find((s) => s.slug === d.value.site))
const comp = computed(() => site.value?.components.find((c) => c.type === d.value.component))
const unit = computed(() => props.info.fields[d.value.field]?.unit ?? null)
const fieldName = computed(() => props.info.fields[d.value.field]?.name[lc.value] ?? d.value.field)

// The chart shows the detection with some time either side: as long as the detection, 30 min to 6 h.
const chartWindow = computed(() => {
  const a = Date.parse(d.value.start)
  const b = Date.parse(d.value.end)
  const pad = Math.min(6 * 3_600_000, Math.max(30 * 60_000, b - a))
  const to = Math.min(b + pad, Math.floor(Date.now() / 60_000) * 60_000)
  return { preset: 'custom' as const, from: new Date(a - pad), to: new Date(to) }
})
const series = useLoader<SeriesResponse>(() =>
  api.series(props.info.code, d.value.site, d.value.component, chartWindow.value.from, chartWindow.value.to),
)
watch(
  () => d.value.id,
  () => series.load(),
  { immediate: true },
)
const field = computed(() => series.data.value?.fields.find((f) => f.code === d.value.field) ?? null)
const days = computed(() =>
  formatDays(
    {
      from: d.value.start.slice(0, 10),
      to: new Date(Date.parse(d.value.end) - 60_000).toISOString().slice(0, 10),
    },
    lc.value,
  ),
)
</script>

<template>
  <div class="flex flex-col gap-4" data-testid="detection-panel">
    <div class="flex items-center gap-2 text-xs">
      <span
        class="rounded px-1.5 py-0.5 font-medium"
        :class="
          d.status === 'confirmed'
            ? 'bg-detect/15 text-detect'
            : d.status === 'suspect'
              ? 'border border-dashed border-detect/60 text-detect'
              : 'bg-sunken text-ink-3'
        "
        >{{ t(`detections.status.${d.status}`) }}</span
      >
      <span class="num text-ink-3">#{{ d.id }}</span>
      <span class="ml-auto flex items-center gap-1">
        <button type="button" class="icon-btn" :disabled="position <= 1" @click="emit('prev')">
          ← <span class="sr-only">{{ t('detections.prev') }}</span>
        </button>
        <span class="num px-1 text-ink-3">{{ position }} / {{ total }}</span>
        <button type="button" class="icon-btn" :disabled="position >= total" @click="emit('next')">
          → <span class="sr-only">{{ t('detections.next') }}</span>
        </button>
      </span>
    </div>

    <figure>
      <figcaption class="eyebrow mb-1">{{ fieldName }} · {{ d.field }}</figcaption>
      <div v-if="!field" class="h-[210px] animate-pulse rounded-md bg-sunken" aria-busy="true" />
      <FieldChart v-else :field="field" :name="fieldName" :window="chartWindow" :detections="[d]" />
      <p class="num mt-1 text-[0.6875rem] text-ink-3">
        {{
          t('detections.chartWindow', { from: formatUtc(chartWindow.from), to: formatUtc(chartWindow.to) })
        }}
      </p>
    </figure>

    <dl class="grid grid-cols-[7rem_minmax(0,1fr)] gap-x-3 gap-y-2 text-sm">
      <dt class="text-ink-3">{{ t('detections.where') }}</dt>
      <dd>{{ site?.name[lc] }} · {{ comp?.name[lc] ?? d.component }}</dd>
      <dt class="text-ink-3">{{ t('detections.when') }}</dt>
      <dd class="num">
        {{ formatRange(d.start, d.end, lc, true) }} UTC · {{ formatDuration(d.minutes, t) }}
      </dd>
      <dt class="text-ink-3">{{ t('detections.saw') }}</dt>
      <dd class="font-medium">{{ evidenceText(d.type, d.evidence, unit, lc, t) }}</dd>
      <dt class="text-ink-3">{{ t('detections.ruleLabel') }}</dt>
      <dd>
        {{ t(`rules.type.${d.type}`) }} · {{ ruleText(d.type, d.params, unit, lc, t) }}
        <span class="block text-xs text-ink-3">{{ t('detections.snapshot', { v: d.rule_version }) }}</span>
      </dd>
    </dl>

    <p
      class="rounded-md border px-3 py-2 text-xs"
      :class="d.mandatory ? 'border-detect/40 bg-detect/5' : 'border-line bg-sunken/60'"
    >
      {{
        d.mandatory
          ? t('detections.effectMandatory', {
              n: d.minutes,
              component: comp?.name[lc] ?? d.component,
              days,
            })
          : t('detections.effectOptional')
      }}
    </p>

    <p v-if="d.decided_by" class="text-xs text-ink-2">
      {{ t(`detections.decidedBy.${d.status}`, { name: d.decided_by, time: formatUtc(d.decided_at) }) }}
      <template v-if="d.note"> · “{{ d.note }}”</template>
    </p>

    <label class="flex flex-col gap-1.5">
      <span class="label">{{ t('detections.note') }}</span>
      <textarea
        v-model="note"
        rows="2"
        maxlength="500"
        class="input"
        :placeholder="t('detections.notePlaceholder')"
      />
    </label>
    <div class="flex flex-wrap gap-2 border-t border-line pt-4">
      <button
        v-if="d.status !== 'confirmed'"
        type="button"
        class="btn-primary"
        :disabled="busy"
        @click="emit('decide', 'confirm', note)"
      >
        {{ d.status === 'rejected' ? t('detections.reverseConfirm') : t('detections.confirm') }}
      </button>
      <button
        v-if="d.status !== 'rejected'"
        type="button"
        class="btn"
        :disabled="busy"
        @click="emit('decide', 'reject', note)"
      >
        {{ d.status === 'confirmed' ? t('detections.reverseReject') : t('detections.reject') }}
      </button>
    </div>
  </div>
</template>
