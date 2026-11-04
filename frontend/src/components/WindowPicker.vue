<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  fromUtcInput,
  MAX_WINDOW_MS,
  toUtcInput,
  WINDOW_PRESETS,
  windowFromPreset,
  type ChartWindow,
  type WindowPreset,
} from '@/utils/time'

const props = defineProps<{ modelValue: ChartWindow }>()
const emit = defineEmits<{ 'update:modelValue': [ChartWindow] }>()
const { t } = useI18n()

const showCustom = ref(props.modelValue.preset === 'custom')
const from = ref(toUtcInput(props.modelValue.from))
const to = ref(toUtcInput(props.modelValue.to))
const invalid = ref(false)

function selectPreset(p: WindowPreset) {
  showCustom.value = false
  emit('update:modelValue', windowFromPreset(p))
}

function apply() {
  const a = fromUtcInput(from.value)
  const b = fromUtcInput(to.value)
  invalid.value = !a || !b || a >= b || b.getTime() - a.getTime() > MAX_WINDOW_MS
  if (!invalid.value && a && b) emit('update:modelValue', { preset: 'custom', from: a, to: b })
}
</script>

<template>
  <div class="flex flex-wrap items-center gap-1" role="group" :aria-label="t('window.label')">
    <button
      v-for="p in WINDOW_PRESETS"
      :key="p"
      type="button"
      class="rounded px-2 py-1 text-xs"
      :class="modelValue.preset === p ? 'bg-accent/20 text-accent' : 'text-muted hover:bg-panel-2'"
      :aria-pressed="modelValue.preset === p"
      @click="selectPreset(p)"
    >
      {{ p }}
    </button>
    <button
      type="button"
      class="rounded px-2 py-1 text-xs"
      :class="modelValue.preset === 'custom' ? 'bg-accent/20 text-accent' : 'text-muted hover:bg-panel-2'"
      @click="showCustom = !showCustom"
    >
      {{ t('window.custom') }}
    </button>
    <form v-if="showCustom" class="flex w-full flex-wrap items-center gap-2 pt-1" @submit.prevent="apply">
      <input v-model="from" type="datetime-local" class="input" :aria-label="t('common.from')" />
      <input v-model="to" type="datetime-local" class="input" :aria-label="t('common.to')" />
      <span class="text-xs text-muted">UTC</span>
      <button type="submit" class="btn">{{ t('common.apply') }}</button>
      <span
        class="text-xs"
        :class="invalid ? 'text-bad' : 'text-muted'"
        :role="invalid ? 'alert' : undefined"
      >
        {{ t('window.max31') }}
      </span>
    </form>
  </div>
</template>
