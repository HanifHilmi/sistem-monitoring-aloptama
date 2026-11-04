<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Locale } from '@/i18n'
import { useDisplayStore } from '@/stores/display'
import { delta, int, LEVEL_TEXT, level, pct } from '@/utils/format'
import Sparkline from './Sparkline.vue'

export interface KpiItem {
  key: string
  label: string
  hint: string
  value: number | null
  previous: number | null
  spark: (number | null)[]
  valid?: number
  expected?: number
}

const props = defineProps<{ items: KpiItem[]; previousLabel: string; loading?: boolean }>()
const { t, locale } = useI18n()
const lc = computed(() => locale.value as Locale)
const display = useDisplayStore()

function diff(it: KpiItem): number | null {
  return it.value === null || it.previous === null ? null : Math.round((it.value - it.previous) * 100) / 100
}
</script>

<template>
  <section
    class="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-line bg-line sm:grid-cols-5"
    :class="loading ? 'opacity-60' : ''"
    :aria-label="t('board.kpis')"
    aria-live="polite"
  >
    <div
      v-for="(it, i) in props.items"
      :key="it.key"
      class="flex min-w-0 flex-col gap-0.5 bg-surface px-3 py-2.5"
      :class="i === 0 ? 'col-span-2 sm:col-span-1' : ''"
    >
      <div class="flex items-baseline justify-between gap-2">
        <span class="eyebrow truncate" :title="it.hint">{{ it.label }}</span>
        <span
          v-if="diff(it) !== null"
          class="num text-[0.6875rem]"
          :class="(diff(it) ?? 0) < 0 ? 'text-bad' : (diff(it) ?? 0) > 0 ? 'text-ok' : 'text-ink-3'"
          :title="t('board.vsPrevious', { period: previousLabel })"
        >
          {{ delta(diff(it), lc) }}
        </span>
      </div>
      <div class="flex items-end justify-between gap-2">
        <p
          class="num text-[1.7rem] leading-none font-semibold"
          :class="LEVEL_TEXT[level(it.value, display.thresholds)]"
          :title="
            it.expected
              ? t('common.validOfExpected', { valid: int(it.valid, lc), expected: int(it.expected, lc) })
              : undefined
          "
        >
          {{ pct(it.value, lc) }}<span class="text-sm font-normal text-ink-3">%</span>
        </p>
        <Sparkline
          :values="it.spark"
          :width="72"
          :height="18"
          :min-span="1"
          class="h-[1.125rem] w-[4.5rem] shrink-0 text-ink-3"
        />
      </div>
      <p class="truncate text-[0.6875rem] text-ink-3">
        <template v-if="it.expected">{{
          t('board.missing', { n: int((it.expected ?? 0) - (it.valid ?? 0), lc) })
        }}</template>
        <template v-else>{{ it.hint }}</template>
      </p>
    </div>
  </section>
</template>
