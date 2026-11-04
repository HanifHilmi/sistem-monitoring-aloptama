<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Availability } from '@/api/types'
import type { Locale } from '@/i18n'
import { useDisplayStore } from '@/stores/display'
import { formatInt, formatPct, LEVEL_TEXT, levelFor } from '@/utils/format'

const props = defineProps<{
  title: string
  hint: string
  pct: number | null | undefined
  counts?: Availability | null
  sub?: string
  big?: boolean
}>()

const { t, locale } = useI18n()
const display = useDisplayStore()
const open = ref(false)
const lc = computed(() => locale.value as Locale)
const level = computed(() => levelFor(props.pct, display.thresholds))
</script>

<template>
  <div class="panel flex flex-col gap-1">
    <div class="flex items-baseline justify-between gap-2">
      <h3 class="label">{{ title }}</h3>
      <button
        v-if="counts"
        type="button"
        class="text-xs text-muted underline-offset-2 hover:underline"
        :aria-expanded="open"
        @click="open = !open"
      >
        {{ t('kpi.details') }}
      </button>
    </div>
    <p
      :class="[LEVEL_TEXT[level], big ? 'text-4xl' : 'text-2xl']"
      class="font-bold tabular-nums"
      :title="
        counts ? t('common.validOfExpected', { valid: counts.valid, expected: counts.expected }) : undefined
      "
    >
      {{ pct === null || pct === undefined ? t('common.none') : formatPct(pct, lc) }}
    </p>
    <p class="text-xs text-muted">{{ hint }}</p>
    <p v-if="sub" class="text-xs text-muted">{{ sub }}</p>
    <p v-if="counts && open" class="text-xs text-text tabular-nums">
      {{
        t('common.validOfExpected', {
          valid: formatInt(counts.valid, lc),
          expected: formatInt(counts.expected, lc),
        })
      }}
      · {{ t('common.missingMinutes', { n: formatInt(counts.missing, lc) }) }}
    </p>
  </div>
</template>
