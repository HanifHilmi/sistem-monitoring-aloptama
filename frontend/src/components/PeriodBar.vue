<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  formatUtc,
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

const KINDS: PeriodKind[] = ['week', 'month', 'quarter', 'year', 'custom']
const showCustom = ref(props.modelValue.kind === 'custom')
const from = ref(toUtcInput(props.modelValue.from))
const to = ref(toUtcInput(props.modelValue.to))
const invalid = ref(false)

const fmt = (d: Date, o: Intl.DateTimeFormatOptions) =>
  new Intl.DateTimeFormat(locale.value === 'id' ? 'id-ID' : 'en-GB', { timeZone: 'UTC', ...o }).format(d)

const label = computed(() => {
  const p = props.modelValue
  switch (p.kind) {
    case 'week':
      return `${fmt(p.from, { day: 'numeric', month: 'short' })} – ${fmt(new Date(p.to.getTime() - 1), { day: 'numeric', month: 'short', year: 'numeric' })}`
    case 'month':
      return fmt(p.from, { month: 'long', year: 'numeric' })
    case 'quarter':
      return `Q${Math.floor(p.from.getUTCMonth() / 3) + 1} ${p.from.getUTCFullYear()}`
    case 'year':
      return String(p.from.getUTCFullYear())
    case 'day':
      return fmt(p.from, { day: 'numeric', month: 'long', year: 'numeric' })
    default:
      return `${formatUtc(p.from)} – ${formatUtc(p.to)}`
  }
})

const isCurrent = computed(() => {
  const now = Date.now()
  return props.modelValue.from.getTime() <= now && now < props.modelValue.to.getTime()
})

function pick(kind: PeriodKind) {
  if (kind === 'custom') {
    showCustom.value = true
    from.value = toUtcInput(props.modelValue.from)
    to.value = toUtcInput(props.modelValue.to)
    return
  }
  showCustom.value = false
  emit('update:modelValue', periodContaining(kind, new Date()))
}

function apply() {
  const a = fromUtcInput(from.value)
  const b = fromUtcInput(to.value)
  invalid.value = !a || !b || a >= b
  if (!invalid.value && a && b) emit('update:modelValue', { kind: 'custom', from: a, to: b })
}
</script>

<template>
  <div class="flex flex-wrap items-center gap-2">
    <div class="seg" role="group" :aria-label="t('period.label')">
      <button
        v-for="k in KINDS"
        :key="k"
        type="button"
        :aria-pressed="k === 'custom' ? showCustom : !showCustom && modelValue.kind === k"
        @click="pick(k)"
      >
        {{ t(`period.${k}`) }}
      </button>
    </div>
    <div v-if="!showCustom && modelValue.kind !== 'custom'" class="flex items-center gap-1">
      <button
        type="button"
        class="icon-btn"
        :aria-label="t('period.previous')"
        @click="emit('update:modelValue', shiftPeriod(modelValue, -1))"
      >
        ‹
      </button>
      <span class="min-w-[8.5rem] text-center text-sm font-medium" aria-live="polite">{{ label }}</span>
      <button
        type="button"
        class="icon-btn"
        :aria-label="t('period.next')"
        :disabled="isCurrent"
        @click="emit('update:modelValue', shiftPeriod(modelValue, 1))"
      >
        ›
      </button>
      <button
        v-if="!isCurrent && modelValue.kind !== 'day'"
        type="button"
        class="icon-btn"
        @click="
          emit(
            'update:modelValue',
            periodContaining(modelValue.kind as Exclude<PeriodKind, 'custom'>, new Date()),
          )
        "
      >
        {{ t('period.current') }}
      </button>
    </div>
    <form v-else class="flex flex-wrap items-center gap-1.5" @submit.prevent="apply">
      <input v-model="from" type="datetime-local" class="field" :aria-label="t('common.from')" />
      <span class="text-xs text-ink-3">–</span>
      <input v-model="to" type="datetime-local" class="field" :aria-label="t('common.to')" />
      <span class="text-xs text-ink-3">UTC</span>
      <button type="submit" class="icon-btn">{{ t('common.apply') }}</button>
      <span v-if="invalid" class="text-xs text-bad" role="alert">{{ t('period.invalid') }}</span>
    </form>
  </div>
</template>
