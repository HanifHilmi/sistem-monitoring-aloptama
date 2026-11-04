<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  formatUtc,
  formatUtcDate,
  fromUtcInput,
  periodContaining,
  shiftPeriod,
  toUtcInput,
  type Period,
  type PeriodKind,
} from '@/utils/time'

const props = defineProps<{ modelValue: Period }>()
const emit = defineEmits<{ 'update:modelValue': [Period] }>()
const { t, locale } = useI18n()

const KINDS: PeriodKind[] = ['day', 'week', 'month', 'quarter', 'year', 'custom']
const customFrom = ref(toUtcInput(props.modelValue.from))
const customTo = ref(toUtcInput(props.modelValue.to))
const customError = ref(false)

const label = computed(() => {
  const p = props.modelValue
  const fmt = (d: Date, o: Intl.DateTimeFormatOptions) =>
    new Intl.DateTimeFormat(locale.value === 'id' ? 'id-ID' : 'en-GB', { timeZone: 'UTC', ...o }).format(d)
  switch (p.kind) {
    case 'day':
      return fmt(p.from, { day: 'numeric', month: 'long', year: 'numeric' })
    case 'week':
      return t('period.weekOf', { date: fmt(p.from, { day: 'numeric', month: 'short', year: 'numeric' }) })
    case 'month':
      return fmt(p.from, { month: 'long', year: 'numeric' })
    case 'quarter':
      return `Q${Math.floor(p.from.getUTCMonth() / 3) + 1} ${p.from.getUTCFullYear()}`
    case 'year':
      return String(p.from.getUTCFullYear())
    default:
      return `${formatUtc(p.from)} – ${formatUtc(p.to)}`
  }
})

function setKind(kind: PeriodKind) {
  if (kind === 'custom') {
    customFrom.value = toUtcInput(props.modelValue.from)
    customTo.value = toUtcInput(props.modelValue.to)
    emit('update:modelValue', { ...props.modelValue, kind: 'custom' })
    return
  }
  emit('update:modelValue', periodContaining(kind, new Date()))
}

function applyCustom() {
  const from = fromUtcInput(customFrom.value)
  const to = fromUtcInput(customTo.value)
  customError.value = !from || !to || from >= to
  if (!customError.value && from && to) emit('update:modelValue', { kind: 'custom', from, to })
}

const isCurrent = computed(() => {
  const now = Date.now()
  return props.modelValue.from.getTime() <= now && now < props.modelValue.to.getTime()
})
</script>

<template>
  <div class="flex flex-wrap items-center gap-2" role="group" :aria-label="t('period.label')">
    <label class="sr-only" for="period-kind">{{ t('period.label') }}</label>
    <select
      id="period-kind"
      class="input"
      :value="modelValue.kind"
      @change="setKind(($event.target as HTMLSelectElement).value as PeriodKind)"
    >
      <option v-for="k in KINDS" :key="k" :value="k">{{ t(`period.${k}`) }}</option>
    </select>
    <template v-if="modelValue.kind !== 'custom'">
      <button
        type="button"
        class="btn"
        :aria-label="t('period.previous')"
        @click="emit('update:modelValue', shiftPeriod(modelValue, -1))"
      >
        ‹
      </button>
      <span class="min-w-[9rem] text-center text-sm font-medium" aria-live="polite">{{ label }}</span>
      <button
        type="button"
        class="btn"
        :aria-label="t('period.next')"
        :disabled="isCurrent"
        @click="emit('update:modelValue', shiftPeriod(modelValue, 1))"
      >
        ›
      </button>
      <button
        v-if="!isCurrent"
        type="button"
        class="btn-ghost"
        @click="
          emit(
            'update:modelValue',
            periodContaining(modelValue.kind as Exclude<PeriodKind, 'custom'>, new Date()),
          )
        "
      >
        {{ t('period.current') }}
      </button>
    </template>
    <form v-else class="flex flex-wrap items-center gap-2" @submit.prevent="applyCustom">
      <label class="text-xs text-muted">
        {{ t('common.from') }}
        <input v-model="customFrom" type="datetime-local" class="input" :max="toUtcInput(new Date())" />
      </label>
      <label class="text-xs text-muted">
        {{ t('common.to') }}
        <input v-model="customTo" type="datetime-local" class="input" />
      </label>
      <span class="text-xs text-muted">UTC</span>
      <button type="submit" class="btn">{{ t('common.apply') }}</button>
      <span v-if="customError" class="text-xs text-bad" role="alert">{{ t('period.invalid') }}</span>
    </form>
    <span class="sr-only">{{ formatUtcDate(modelValue.from) }}</span>
  </div>
</template>
