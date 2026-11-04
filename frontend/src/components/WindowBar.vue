<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  fromUtcInput,
  MAX_WINDOW_MS,
  toUtcInput,
  windowFromPreset,
  type ChartWindow,
  type WindowPreset,
} from '@/utils/time'

const props = defineProps<{ modelValue: ChartWindow }>()
const emit = defineEmits<{ 'update:modelValue': [ChartWindow] }>()
const { t } = useI18n()
const PRESETS: WindowPreset[] = ['3h', '24h', '7d', '31d']
const custom = ref(props.modelValue.preset === 'custom')
const from = ref(toUtcInput(props.modelValue.from))
const to = ref(toUtcInput(props.modelValue.to))
const invalid = ref(false)

function pick(p: WindowPreset) {
  custom.value = false
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
  <div class="flex flex-wrap items-center gap-2">
    <div class="seg" role="group" :aria-label="t('window.label')">
      <button
        v-for="p in PRESETS"
        :key="p"
        type="button"
        :aria-pressed="!custom && modelValue.preset === p"
        @click="pick(p)"
      >
        {{ t(`window.preset.${p}`) }}
      </button>
      <button type="button" :aria-pressed="custom" @click="custom = true">{{ t('window.custom') }}</button>
    </div>
    <form v-if="custom" class="flex flex-wrap items-center gap-1.5" @submit.prevent="apply">
      <input v-model="from" type="datetime-local" class="field" :aria-label="t('common.from')" />
      <span class="text-xs text-ink-3">–</span>
      <input v-model="to" type="datetime-local" class="field" :aria-label="t('common.to')" />
      <span class="text-xs text-ink-3">UTC</span>
      <button type="submit" class="icon-btn">{{ t('common.apply') }}</button>
      <span
        class="text-xs"
        :class="invalid ? 'text-bad' : 'text-ink-3'"
        :role="invalid ? 'alert' : undefined"
        >{{ t('window.max31') }}</span
      >
    </form>
  </div>
</template>
