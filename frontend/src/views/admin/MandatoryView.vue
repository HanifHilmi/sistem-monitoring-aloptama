<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import { api, ApiProblem } from '@/api/client'
import type { JobRow, MandatoryPreview, MandatoryType } from '@/api/types'
import { useLoader } from '@/composables/useLoader'
import type { Locale } from '@/i18n'
import { useDisplayStore } from '@/stores/display'
import { DEFAULT_SYSTEM } from '@/stores/live'
import { figureLevel, LEVEL_TEXT, pct } from '@/utils/format'

// Mandatory fields per component type (FR-REG-003): a component counts as available in a minute only when all of
// its mandatory fields have a value. A change applies to every period (OPEN-12) and recomputes the figures.
const { t, locale } = useI18n()
const lc = computed(() => locale.value as Locale)
const display = useDisplayStore()
const loader = useLoader<MandatoryType[]>(() => api.mandatoryFields(DEFAULT_SYSTEM))
void loader.load()

/** Proposed mandatory sets, per component type, while being edited. */
const draft = reactive<Record<string, string[]>>({})
const preview = ref<Record<string, MandatoryPreview | 'loading' | 'error'>>({})
const saving = ref<string | null>(null)
const done = ref<Record<string, JobRow>>({})
const error = ref<Record<string, string>>({})

const current = (m: MandatoryType) => m.fields.filter((f) => f.mandatory).map((f) => f.code)
const chosen = (m: MandatoryType) => draft[m.type] ?? current(m)
const changed = (m: MandatoryType) =>
  draft[m.type] !== undefined && [...draft[m.type]!].sort().join() !== current(m).sort().join()

function toggle(m: MandatoryType, code: string) {
  const set = new Set(chosen(m))
  if (set.has(code)) {
    if (set.size === 1) return // at least one mandatory field (FR-REG-003.4)
    set.delete(code)
  } else set.add(code)
  draft[m.type] = m.fields.map((f) => f.code).filter((c) => set.has(c))
  delete done.value[m.type]
  void loadPreview(m)
}
async function loadPreview(m: MandatoryType) {
  if (!changed(m)) {
    preview.value = Object.fromEntries(Object.entries(preview.value).filter(([k]) => k !== m.type))
    return
  }
  preview.value = { ...preview.value, [m.type]: 'loading' }
  try {
    const p = await api.previewMandatory(DEFAULT_SYSTEM, m.type, chosen(m))
    if (changed(m)) preview.value = { ...preview.value, [m.type]: p }
  } catch {
    preview.value = { ...preview.value, [m.type]: 'error' }
  }
}
function discard(m: MandatoryType) {
  delete draft[m.type]
  void loadPreview(m)
}
async function save(m: MandatoryType) {
  saving.value = m.type
  error.value = { ...error.value, [m.type]: '' }
  try {
    const { job } = await api.saveMandatory(DEFAULT_SYSTEM, m.type, chosen(m))
    done.value = { ...done.value, [m.type]: job }
    await loader.load({ silent: true })
    delete draft[m.type]
    void loadPreview(m)
  } catch (e) {
    error.value = { ...error.value, [m.type]: e instanceof ApiProblem ? e.code : 'network_error' }
  } finally {
    saving.value = null
  }
}
watch(
  () => loader.data.value,
  () => {
    for (const k of Object.keys(draft)) if (!loader.data.value?.some((m) => m.type === k)) delete draft[k]
  },
)
const coverage = computed(() => display.systems[DEFAULT_SYSTEM]?.coverage_start.slice(0, 10) ?? '2025-12-24')
void display.system(DEFAULT_SYSTEM)
const level = (a: { pct: number | null; missing: number }) => LEVEL_TEXT[figureLevel(a, display.thresholds)]
</script>

<template>
  <div class="flex flex-col gap-4">
    <header>
      <h2 class="text-base font-semibold">{{ t('admin.section.mandatory') }}</h2>
      <p class="text-sm text-ink-2">{{ t('mandatory.subtitle', { date: coverage }) }}</p>
    </header>

    <p v-if="loader.error.value" class="text-sm text-warn" role="alert">{{ t('common.error') }}</p>
    <div v-else-if="!loader.data.value" class="h-60 animate-pulse rounded-lg bg-sunken" aria-busy="true" />
    <ul v-else class="overflow-hidden rounded-lg border border-line bg-surface">
      <li
        v-for="m in loader.data.value"
        :key="m.type"
        class="flex flex-col gap-3 border-b border-line px-4 py-3 last:border-0"
        :class="changed(m) ? 'bg-accent-soft/40' : ''"
      >
        <div class="flex flex-wrap items-center gap-x-4 gap-y-2">
          <p class="w-full text-sm font-medium sm:w-52">
            {{ m.name[lc] }}
            <span class="block text-xs font-normal text-ink-3">{{ m.type }}</span>
          </p>
          <p v-if="m.is_dcp" class="flex-1 text-xs text-ink-2">{{ t('mandatory.dcp') }}</p>
          <div
            v-else
            class="flex flex-1 flex-wrap gap-1.5"
            role="group"
            :aria-label="t('mandatory.fieldsOf', { name: m.name[lc] })"
          >
            <button
              v-for="f in m.fields"
              :key="f.code"
              type="button"
              class="flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs"
              :class="
                chosen(m).includes(f.code)
                  ? 'border-accent bg-accent-soft font-medium text-ink'
                  : 'border-line text-ink-2 hover:border-line-strong'
              "
              :aria-pressed="chosen(m).includes(f.code)"
              :title="f.name[lc]"
              :disabled="chosen(m).length === 1 && chosen(m).includes(f.code)"
              @click="toggle(m, f.code)"
            >
              <span aria-hidden="true">{{ chosen(m).includes(f.code) ? '✓' : '○' }}</span>
              <span class="num">{{ f.code }}</span>
              <span class="hidden text-ink-3 sm:inline"
                >· {{ chosen(m).includes(f.code) ? t('mandatory.required') : t('mandatory.optional') }}</span
              >
            </button>
          </div>
        </div>

        <div
          v-if="changed(m)"
          class="flex flex-col gap-2 rounded-md border border-line bg-surface p-3 text-xs sm:ml-56"
        >
          <p class="font-medium text-ink">{{ t('mandatory.previewTitle') }}</p>
          <p v-if="preview[m.type] === 'loading' || !preview[m.type]" class="text-ink-3">
            {{ t('mandatory.previewLoading') }}
          </p>
          <p v-else-if="preview[m.type] === 'error'" class="text-warn">{{ t('common.error') }}</p>
          <table v-else class="w-full max-w-md">
            <thead class="text-left text-ink-3">
              <tr>
                <th class="py-1 font-medium">{{ t('mandatory.site') }}</th>
                <th class="py-1 text-right font-medium">{{ t('mandatory.now') }}</th>
                <th class="py-1 text-right font-medium">{{ t('mandatory.after') }}</th>
              </tr>
            </thead>
            <tbody class="num">
              <tr v-for="s in (preview[m.type] as MandatoryPreview).sites" :key="s.slug">
                <td class="py-1 font-sans text-ink-2">{{ s.name[lc] }}</td>
                <td class="py-1 text-right" :class="level(s.current)">{{ pct(s.current.pct, lc) }} %</td>
                <td class="py-1 text-right font-semibold" :class="level(s.proposed)">
                  {{ pct(s.proposed.pct, lc) }} %
                </td>
              </tr>
            </tbody>
          </table>
          <p class="text-ink-3">{{ t('mandatory.applies') }}</p>
          <p v-if="error[m.type]" class="text-bad">
            {{ error[m.type] === 'job_running' ? t('jobs.error.running') : t('common.error') }}
          </p>
          <div class="flex flex-wrap gap-2 pt-1">
            <button type="button" class="btn-primary" :disabled="saving !== null" @click="save(m)">
              {{ t('mandatory.save') }}
            </button>
            <button type="button" class="btn" @click="discard(m)">{{ t('users.cancel') }}</button>
          </div>
        </div>
        <p v-else-if="done[m.type]" class="text-xs text-ink-2 sm:ml-56" role="status">
          {{ t('mandatory.saved') }}
          <RouterLink to="/admin/jobs" class="text-accent hover:underline">{{
            t('mandatory.jobLink', { id: done[m.type]!.id })
          }}</RouterLink>
        </p>
      </li>
    </ul>
  </div>
</template>
