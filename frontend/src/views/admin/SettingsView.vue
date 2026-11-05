<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { api, ApiProblem } from '@/api/client'
import type { AdminSettings, ProblemThresholds, SettingKey } from '@/api/types'
import { useLoader } from '@/composables/useLoader'
import { useDisplayStore } from '@/stores/display'
import { formatUtc } from '@/utils/time'

// Settings (FR-ADM-003): validated, audited, each section saved on its own. They change how SIMOLA shows and
// judges data, never the stored minutes.
const { t } = useI18n()
const display = useDisplayStore()
const loader = useLoader<AdminSettings>(() => api.adminSettings())
void loader.load()

const colors = reactive({ good: 99, warning: 95 })
const grace = ref(3)
const problems = reactive<ProblemThresholds>({
  cdp_no_data_min: 2,
  cdp_unreachable_min: 2,
  site_no_data_min: 2,
  field_missing_min: 5,
  ingest_lag_min: 5,
})
function reset(s: AdminSettings) {
  Object.assign(colors, s.color_thresholds)
  grace.value = s.grace_minutes
  Object.assign(problems, s.problem_thresholds)
}
watch(
  () => loader.data.value,
  (s) => s && reset(s),
  { immediate: true },
)

const PROBLEM_KEYS: (keyof ProblemThresholds)[] = [
  'cdp_no_data_min',
  'cdp_unreachable_min',
  'site_no_data_min',
  'field_missing_min',
  'ingest_lag_min',
]
const dirty = computed(() => {
  const s = loader.data.value
  if (!s) return { color_thresholds: false, grace_minutes: false, problem_thresholds: false }
  return {
    color_thresholds:
      colors.good !== s.color_thresholds.good || colors.warning !== s.color_thresholds.warning,
    grace_minutes: grace.value !== s.grace_minutes,
    problem_thresholds: PROBLEM_KEYS.some((k) => problems[k] !== s.problem_thresholds[k]),
  }
})
const invalid = computed(() => ({
  color_thresholds: !(colors.good > colors.warning && colors.warning > 0 && colors.good <= 100)
    ? 'colors'
    : null,
  grace_minutes: !(Number.isInteger(grace.value) && grace.value >= 1 && grace.value <= 15) ? 'grace' : null,
  problem_thresholds: PROBLEM_KEYS.some(
    (k) => !(Number.isInteger(problems[k]) && problems[k] >= 1 && problems[k] <= 120),
  )
    ? 'problems'
    : null,
}))
const saving = ref<SettingKey | null>(null)
const saved = ref<SettingKey | null>(null)
const error = ref<Partial<Record<SettingKey, string>>>({})
async function save(key: SettingKey) {
  saving.value = key
  error.value = { ...error.value, [key]: undefined }
  try {
    const value =
      key === 'color_thresholds' ? { ...colors } : key === 'grace_minutes' ? grace.value : { ...problems }
    loader.data.value = await api.saveSetting(key, value as never)
    saved.value = key
    if (key === 'color_thresholds') display.thresholds = { ...colors }
  } catch (e) {
    error.value = { ...error.value, [key]: e instanceof ApiProblem ? e.code : 'network_error' }
  } finally {
    saving.value = null
  }
}
const changed = (key: SettingKey) => loader.data.value?.changed[key]
const swatches = computed(() => [
  { cls: 'bg-full', label: '100 %' },
  { cls: 'bg-good', label: `≥ ${colors.good} %` },
  { cls: 'bg-warn', label: `≥ ${colors.warning} %` },
  { cls: 'bg-bad', label: `< ${colors.warning} %` },
])
</script>

<template>
  <div class="flex flex-col gap-4">
    <header>
      <h2 class="text-base font-semibold">{{ t('admin.section.settings') }}</h2>
      <p class="text-sm text-ink-2">{{ t('settings.subtitle') }}</p>
    </header>

    <p v-if="loader.error.value" class="text-sm text-warn" role="alert">{{ t('common.error') }}</p>
    <div v-else-if="!loader.data.value" class="h-60 animate-pulse rounded-lg bg-sunken" aria-busy="true" />
    <template v-else>
      <!-- Availability colours (FR-DSH-012) -->
      <section
        class="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4"
        :aria-label="t('settings.colors.title')"
      >
        <div>
          <h3 class="text-sm font-semibold">{{ t('settings.colors.title') }}</h3>
          <p class="text-xs text-ink-2">{{ t('settings.colors.hint') }}</p>
        </div>
        <div class="flex flex-wrap items-end gap-4">
          <label class="flex flex-col gap-1">
            <span class="label">{{ t('settings.colors.good') }}</span>
            <span class="flex items-center gap-1.5"
              ><input
                v-model.number="colors.good"
                type="number"
                min="1"
                max="100"
                step="0.1"
                class="input w-24 py-1.5"
              />
              %</span
            >
          </label>
          <label class="flex flex-col gap-1">
            <span class="label">{{ t('settings.colors.warning') }}</span>
            <span class="flex items-center gap-1.5"
              ><input
                v-model.number="colors.warning"
                type="number"
                min="1"
                max="100"
                step="0.1"
                class="input w-24 py-1.5"
              />
              %</span
            >
          </label>
          <ul class="flex flex-wrap gap-2 text-xs" :aria-label="t('settings.colors.preview')">
            <li
              v-for="s in swatches"
              :key="s.label"
              class="flex items-center gap-1.5 rounded border border-line px-2 py-1"
            >
              <span class="h-3 w-3 rounded-[2px]" :class="s.cls" />
              <span class="num">{{ s.label }}</span>
            </li>
          </ul>
        </div>
        <footer class="flex flex-wrap items-center gap-3 border-t border-line pt-3 text-xs">
          <button
            type="button"
            class="btn-primary"
            :disabled="!dirty.color_thresholds || !!invalid.color_thresholds || saving !== null"
            @click="save('color_thresholds')"
          >
            {{ t('settings.save') }}
          </button>
          <span v-if="invalid.color_thresholds && dirty.color_thresholds" class="text-bad">{{
            t('settings.invalid.colors')
          }}</span>
          <span v-else-if="error.color_thresholds" class="text-bad">{{ t('common.error') }}</span>
          <span v-else-if="saved === 'color_thresholds' && !dirty.color_thresholds" class="text-ok">{{
            t('settings.saved')
          }}</span>
          <span v-if="changed('color_thresholds')" class="ml-auto text-ink-3">{{
            t('settings.changed', {
              who: changed('color_thresholds')!.by,
              time: formatUtc(changed('color_thresholds')!.at),
            })
          }}</span>
        </footer>
      </section>

      <!-- Freshness grace (FR-KPI-003) -->
      <section
        class="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4"
        :aria-label="t('settings.grace.title')"
      >
        <div>
          <h3 class="text-sm font-semibold">{{ t('settings.grace.title') }}</h3>
          <p class="text-xs text-ink-2">{{ t('settings.grace.hint') }}</p>
        </div>
        <label class="flex flex-col gap-1">
          <span class="label">{{ t('settings.grace.label') }}</span>
          <span class="flex items-center gap-1.5"
            ><input
              v-model.number="grace"
              type="number"
              min="1"
              max="15"
              step="1"
              class="input w-24 py-1.5"
            />
            {{ t('settings.minutes') }}</span
          >
        </label>
        <footer class="flex flex-wrap items-center gap-3 border-t border-line pt-3 text-xs">
          <button
            type="button"
            class="btn-primary"
            :disabled="!dirty.grace_minutes || !!invalid.grace_minutes || saving !== null"
            @click="save('grace_minutes')"
          >
            {{ t('settings.save') }}
          </button>
          <span v-if="invalid.grace_minutes && dirty.grace_minutes" class="text-bad">{{
            t('settings.invalid.grace')
          }}</span>
          <span v-else-if="error.grace_minutes" class="text-bad">{{ t('common.error') }}</span>
          <span v-else-if="saved === 'grace_minutes' && !dirty.grace_minutes" class="text-ok">{{
            t('settings.saved')
          }}</span>
          <span v-if="changed('grace_minutes')" class="ml-auto text-ink-3">{{
            t('settings.changed', {
              who: changed('grace_minutes')!.by,
              time: formatUtc(changed('grace_minutes')!.at),
            })
          }}</span>
        </footer>
      </section>

      <!-- Problems panel thresholds (FR-DSH-010) -->
      <section
        class="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4"
        :aria-label="t('settings.problems.title')"
      >
        <div>
          <h3 class="text-sm font-semibold">{{ t('settings.problems.title') }}</h3>
          <p class="text-xs text-ink-2">{{ t('settings.problems.hint') }}</p>
        </div>
        <div class="grid gap-x-6 gap-y-2 sm:grid-cols-2">
          <label
            v-for="k in PROBLEM_KEYS"
            :key="k"
            class="flex items-center justify-between gap-3 border-b border-line py-1.5 text-sm last:border-0 sm:[&:nth-last-child(2)]:border-0"
          >
            <span class="text-ink-2">{{ t(`settings.problems.${k}`) }}</span>
            <span class="flex shrink-0 items-center gap-1.5 text-xs text-ink-3"
              ><input
                v-model.number="problems[k]"
                type="number"
                min="1"
                max="120"
                step="1"
                class="input w-20 py-1"
              />
              {{ t('settings.min') }}</span
            >
          </label>
        </div>
        <footer class="flex flex-wrap items-center gap-3 border-t border-line pt-3 text-xs">
          <button
            type="button"
            class="btn-primary"
            :disabled="!dirty.problem_thresholds || !!invalid.problem_thresholds || saving !== null"
            @click="save('problem_thresholds')"
          >
            {{ t('settings.save') }}
          </button>
          <span v-if="invalid.problem_thresholds && dirty.problem_thresholds" class="text-bad">{{
            t('settings.invalid.problems')
          }}</span>
          <span v-else-if="error.problem_thresholds" class="text-bad">{{ t('common.error') }}</span>
          <span v-else-if="saved === 'problem_thresholds' && !dirty.problem_thresholds" class="text-ok">{{
            t('settings.saved')
          }}</span>
          <span v-if="changed('problem_thresholds')" class="ml-auto text-ink-3">{{
            t('settings.changed', {
              who: changed('problem_thresholds')!.by,
              time: formatUtc(changed('problem_thresholds')!.at),
            })
          }}</span>
        </footer>
      </section>
    </template>
  </div>
</template>
