<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import { api, ApiProblem } from '@/api/client'
import type { Calibration, CalibrationDraft, ComponentMeta, ComponentRow, JobRow } from '@/api/types'
import { useLoader } from '@/composables/useLoader'
import { addMonths, formatUtc } from '@/utils/time'
import CalibrationChip from './CalibrationChip.vue'

// One sensor in the registry (FR-REG-004/005/006): its record, its calibration history (status derived from the
// latest record), and its in-service period. Every change is audited on the server.
export type PanelTab = 'details' | 'calibration' | 'service'
const props = defineProps<{ component: ComponentRow; tab?: PanelTab }>()
const emit = defineEmits<{ changed: [] }>()
const { t } = useI18n()
const tab = ref<PanelTab>(props.tab ?? 'details')
const TABS: PanelTab[] = ['details', 'calibration', 'service']
const c = computed(() => props.component)
const today = new Date().toISOString().slice(0, 10)
const errorText = (code: string) =>
  t(`records.error.${code}`) === `records.error.${code}` ? t('common.error') : t(`records.error.${code}`)

// ---- details (FR-REG-004) ----------------------------------------------------------------------------
const META_KEYS = [
  'sensor_type',
  'manufacturer',
  'model',
  'part_number',
  'serial_number',
  'installed_on',
  'firmware',
  'notes',
] as const
const meta = reactive<Record<(typeof META_KEYS)[number], string>>(
  Object.fromEntries(META_KEYS.map((k) => [k, ''])) as Record<(typeof META_KEYS)[number], string>,
)
function resetMeta() {
  for (const k of META_KEYS) meta[k] = (c.value.meta[k] as string | null | undefined) ?? ''
}
resetMeta()
const metaDirty = computed(() =>
  META_KEYS.some((k) => meta[k].trim() !== ((c.value.meta[k] as string | null | undefined) ?? '')),
)
const metaIssue = computed(() => (meta.installed_on && meta.installed_on > today ? 'date_in_future' : null))
const metaBusy = ref(false)
const metaError = ref<string | null>(null)
const metaSaved = ref(false)
async function saveMeta() {
  metaBusy.value = true
  metaError.value = null
  try {
    const body = Object.fromEntries(
      META_KEYS.map((k) => [k, meta[k].trim() || null]),
    ) as unknown as ComponentMeta
    await api.saveComponentMeta(c.value.id, body)
    metaSaved.value = true
    emit('changed')
  } catch (e) {
    metaError.value = e instanceof ApiProblem ? e.code : 'network_error'
  } finally {
    metaBusy.value = false
  }
}

// ---- calibration (FR-REG-005) ------------------------------------------------------------------------
const history = useLoader<Calibration[]>(() => api.calibrations(c.value.id))
if (!c.value.is_dcp) void history.load()
const editing = ref<Calibration | 'new' | null>(null)
const draft = reactive({
  date: today,
  performed_by: '',
  certificate: '',
  mode: 'interval' as 'interval' | 'date',
  interval: 12,
  next_due: '',
  validated_on: '',
  notes: '',
})
function startNew() {
  Object.assign(draft, {
    date: today,
    performed_by: '',
    certificate: '',
    mode: 'interval',
    interval: 12,
    next_due: '',
    validated_on: '',
    notes: '',
  })
  editing.value = 'new'
  calError.value = null
}
function startEdit(r: Calibration) {
  Object.assign(draft, {
    date: r.date,
    performed_by: r.performed_by,
    certificate: r.certificate ?? '',
    mode: r.interval_months ? 'interval' : 'date',
    interval: r.interval_months ?? 12,
    next_due: r.next_due,
    validated_on: r.validated_on ?? '',
    notes: r.notes ?? '',
  })
  editing.value = r
  calError.value = null
}
const nextDue = computed(() =>
  draft.mode === 'interval' && draft.date && Number.isInteger(draft.interval) && draft.interval > 0
    ? addMonths(draft.date, draft.interval)
    : draft.next_due,
)
const daysUntil = (date: string) =>
  Math.round((Date.parse(`${date}T00:00:00Z`) - Date.parse(`${today}T00:00:00Z`)) / 86_400_000)
const calIssue = computed(() => {
  if (!draft.date) return 'invalid_date'
  if (draft.date > today) return 'date_in_future'
  if (!draft.performed_by.trim()) return 'performed_by_required'
  if (
    draft.mode === 'interval' &&
    !(Number.isInteger(draft.interval) && draft.interval >= 1 && draft.interval <= 120)
  )
    return 'invalid_interval'
  if (!nextDue.value) return 'next_due_required'
  if (nextDue.value <= draft.date) return 'next_due_before_date'
  if (draft.validated_on && draft.validated_on > today) return 'date_in_future'
  if (draft.validated_on && draft.validated_on < draft.date) return 'validated_before_date'
  return null
})
const calBusy = ref(false)
const calError = ref<string | null>(null)
const confirmRemove = ref<number | null>(null)
async function saveCal() {
  if (calIssue.value || calBusy.value) return
  calBusy.value = true
  calError.value = null
  const body: CalibrationDraft = {
    component_id: c.value.id,
    date: draft.date,
    performed_by: draft.performed_by.trim(),
    certificate: draft.certificate.trim() || null,
    next_due: draft.mode === 'date' ? draft.next_due : null,
    interval_months: draft.mode === 'interval' ? draft.interval : null,
    validated_on: draft.validated_on || null,
    notes: draft.notes.trim() || null,
  }
  try {
    if (editing.value === 'new') await api.addCalibration(body)
    else if (editing.value) await api.updateCalibration(editing.value.id, body)
    editing.value = null
    await history.load({ silent: true })
    emit('changed')
  } catch (e) {
    calError.value = e instanceof ApiProblem ? e.code : 'network_error'
  } finally {
    calBusy.value = false
  }
}
async function removeCal(id: number) {
  calBusy.value = true
  try {
    await api.removeCalibration(id)
    confirmRemove.value = null
    await history.load({ silent: true })
    emit('changed')
  } catch (e) {
    calError.value = e instanceof ApiProblem ? e.code : 'network_error'
  } finally {
    calBusy.value = false
  }
}

// ---- in-service period (FR-REG-006, from R2.2) --------------------------------------------------------
const toInput = (iso: string | null) => (iso ? iso.slice(0, 16) : '')
const fromInput = (v: string) => (v ? `${v}:00Z` : null)
const from = ref(toInput(c.value.in_service_from))
const to = ref(toInput(c.value.in_service_to))
watch(
  () => c.value.id,
  () => {
    from.value = toInput(c.value.in_service_from)
    to.value = toInput(c.value.in_service_to)
    resetMeta()
  },
)
const serviceIssue = computed(() => (from.value && to.value && from.value >= to.value ? 'order' : null))
const serviceUnchanged = computed(
  () =>
    fromInput(from.value) === (c.value.in_service_from ? toInput(c.value.in_service_from) + ':00Z' : null) &&
    fromInput(to.value) === (c.value.in_service_to ? toInput(c.value.in_service_to) + ':00Z' : null),
)
const serviceBusy = ref(false)
const serviceError = ref<string | null>(null)
const job = ref<JobRow | null>(null)
async function saveService() {
  if (serviceIssue.value || serviceBusy.value) return
  serviceBusy.value = true
  serviceError.value = null
  try {
    const r = await api.saveInService(c.value.id, fromInput(from.value), fromInput(to.value))
    job.value = r.job
    emit('changed')
  } catch (e) {
    serviceError.value = e instanceof ApiProblem ? e.code : 'network_error'
  } finally {
    serviceBusy.value = false
  }
}
</script>

<template>
  <div class="flex flex-col gap-4 py-1">
    <div class="seg self-start" role="group" :aria-label="t('records.tabs')">
      <button v-for="k in TABS" :key="k" type="button" :aria-pressed="tab === k" @click="tab = k">
        {{ t(`records.tab.${k}`) }}
      </button>
    </div>

    <!-- details -->
    <form v-if="tab === 'details'" class="flex flex-col gap-3" novalidate @submit.prevent="saveMeta">
      <p v-if="metaError" class="rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-sm" role="alert">
        {{ errorText(metaError) }}
      </p>
      <div class="grid gap-3 sm:grid-cols-2">
        <label
          v-for="k in ['sensor_type', 'manufacturer', 'model', 'firmware'] as const"
          :key="k"
          class="flex flex-col gap-1.5"
        >
          <span class="label">{{ t(`records.meta.${k}`) }}</span>
          <input v-model="meta[k]" type="text" maxlength="100" class="input py-1.5" />
        </label>
        <label v-for="k in ['part_number', 'serial_number'] as const" :key="k" class="flex flex-col gap-1.5">
          <span class="label">{{ t(`records.meta.${k}`) }}</span>
          <input v-model="meta[k]" type="text" maxlength="100" class="input num py-1.5" />
        </label>
        <label class="flex flex-col gap-1.5">
          <span class="label">{{ t('records.meta.installed_on') }}</span>
          <input v-model="meta.installed_on" type="date" :max="today" class="input num py-1.5" />
        </label>
      </div>
      <p class="-mt-1 text-xs text-ink-3">{{ t('records.serialHint') }}</p>
      <label class="flex flex-col gap-1.5">
        <span class="label">{{ t('records.meta.notes') }}</span>
        <textarea v-model="meta.notes" rows="2" maxlength="500" class="input" />
      </label>
      <p v-if="metaIssue" class="text-xs text-bad">{{ errorText(metaIssue) }}</p>
      <div class="flex flex-wrap items-center gap-2 border-t border-line pt-3">
        <button type="submit" class="btn-primary" :disabled="!metaDirty || !!metaIssue || metaBusy">
          {{ t('records.save') }}
        </button>
        <span v-if="metaSaved && !metaDirty" class="text-xs text-ok" role="status">{{
          t('settings.saved')
        }}</span>
      </div>
    </form>

    <!-- calibration -->
    <section
      v-else-if="tab === 'calibration'"
      class="flex flex-col gap-3"
      :aria-label="t('records.tab.calibration')"
    >
      <p v-if="c.is_dcp" class="text-sm text-ink-2">{{ t('calibration.dcp') }}</p>
      <template v-else>
        <div class="flex flex-wrap items-center gap-2">
          <CalibrationChip :calibration="c.calibration" />
          <span v-if="c.calibration.next_due" class="num text-xs text-ink-2">{{
            t('calibration.nextDue', { date: c.calibration.next_due })
          }}</span>
          <button
            v-if="editing === null"
            type="button"
            class="btn-primary ml-auto py-1 text-xs"
            @click="startNew"
          >
            {{ t('calibration.record') }}
          </button>
        </div>

        <form
          v-if="editing !== null"
          class="flex flex-col gap-3 rounded-md border border-line bg-sunken/60 p-3"
          novalidate
          data-testid="calibration-form"
          @submit.prevent="saveCal"
        >
          <h3 class="text-sm font-semibold">
            {{ editing === 'new' ? t('calibration.record') : t('calibration.edit') }}
          </h3>
          <p v-if="calError" class="rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-sm" role="alert">
            {{ errorText(calError) }}
          </p>
          <div class="grid gap-3 sm:grid-cols-2">
            <label class="flex flex-col gap-1.5">
              <span class="label">{{ t('calibration.date') }}</span>
              <input v-model="draft.date" type="date" :max="today" class="input num py-1.5" />
            </label>
            <label class="flex flex-col gap-1.5">
              <span class="label">{{ t('calibration.performedBy') }}</span>
              <input v-model="draft.performed_by" type="text" maxlength="100" class="input py-1.5" />
            </label>
            <label class="flex flex-col gap-1.5">
              <span class="label">{{ t('calibration.certificate') }}</span>
              <input v-model="draft.certificate" type="text" maxlength="100" class="input num py-1.5" />
            </label>
            <label class="flex flex-col gap-1.5">
              <span class="label">{{ t('calibration.validatedOn') }}</span>
              <input
                v-model="draft.validated_on"
                type="date"
                :min="draft.date"
                :max="today"
                class="input num py-1.5"
                aria-describedby="validated-hint"
              />
              <span id="validated-hint" class="text-[0.6875rem] text-ink-3">{{
                t('calibration.validatedHint')
              }}</span>
            </label>
          </div>
          <fieldset class="flex flex-col gap-2">
            <legend class="label mb-1">{{ t('calibration.nextDueLabel') }}</legend>
            <div class="flex flex-wrap items-center gap-3 text-sm">
              <label class="flex items-center gap-2">
                <input v-model="draft.mode" type="radio" value="interval" class="accent-[var(--s-accent)]" />
                {{ t('calibration.every') }}
                <input
                  v-model.number="draft.interval"
                  type="number"
                  min="1"
                  max="120"
                  class="input num w-20 py-1"
                  :disabled="draft.mode !== 'interval'"
                  :aria-label="t('calibration.months')"
                />
                {{ t('calibration.months') }}
              </label>
              <label class="flex items-center gap-2">
                <input v-model="draft.mode" type="radio" value="date" class="accent-[var(--s-accent)]" />
                {{ t('calibration.onDate') }}
                <input
                  v-model="draft.next_due"
                  type="date"
                  class="input num py-1"
                  :disabled="draft.mode !== 'date'"
                  :aria-label="t('calibration.nextDueLabel')"
                />
              </label>
            </div>
            <p v-if="nextDue && !calIssue" class="num text-xs text-ink-2" data-testid="next-due-preview">
              {{ t('calibration.preview', { date: nextDue, n: daysUntil(nextDue) }, daysUntil(nextDue)) }}
            </p>
          </fieldset>
          <label class="flex flex-col gap-1.5">
            <span class="label">{{ t('records.meta.notes') }}</span>
            <textarea v-model="draft.notes" rows="2" maxlength="500" class="input" />
          </label>
          <p v-if="calIssue && draft.performed_by" class="text-xs text-bad">{{ errorText(calIssue) }}</p>
          <div class="flex gap-2">
            <button type="submit" class="btn-primary" :disabled="!!calIssue || calBusy">
              {{ t('calibration.save') }}
            </button>
            <button type="button" class="btn" @click="editing = null">{{ t('flags.form.cancel') }}</button>
          </div>
        </form>

        <h3 class="eyebrow mt-1">{{ t('calibration.history') }}</h3>
        <div v-if="!history.data.value" class="h-16 animate-pulse rounded bg-sunken" aria-busy="true" />
        <p v-else-if="!history.data.value.length" class="text-sm text-ink-3">{{ t('calibration.none') }}</p>
        <ol v-else class="flex flex-col" data-testid="calibration-history">
          <li
            v-for="(r, i) in history.data.value"
            :key="r.id"
            class="flex gap-3 border-t border-line py-2 text-sm"
          >
            <span class="num w-24 shrink-0" :class="i ? 'text-ink-3' : 'font-semibold'">{{ r.date }}</span>
            <span class="min-w-0 flex-1">
              {{ r.performed_by }}
              <span v-if="r.certificate" class="num text-ink-3">· {{ r.certificate }}</span>
              <span class="num block text-xs" :class="r.validated_on ? 'text-ink-2' : 'font-medium text-ink'">
                {{
                  r.validated_on
                    ? t('calibration.validated', { date: r.validated_on })
                    : `… ${t('calibration.pending')}`
                }}
              </span>
              <span class="num block text-xs text-ink-2">
                {{ t('calibration.nextDue', { date: r.next_due }) }}
                <template v-if="r.interval_months">
                  · {{ t('calibration.interval', { n: r.interval_months }) }}</template
                >
              </span>
              <span v-if="r.notes" class="block text-xs text-ink-2">{{ r.notes }}</span>
              <span class="block text-xs text-ink-3">{{ r.created_by }} · {{ formatUtc(r.created_at) }}</span>
              <span
                v-if="confirmRemove === r.id"
                class="mt-1 flex flex-wrap items-center gap-2 text-xs"
                role="alertdialog"
              >
                {{ t('calibration.removeConfirm') }}
                <button
                  type="button"
                  class="btn-danger py-0.5 text-xs"
                  :disabled="calBusy"
                  @click="removeCal(r.id)"
                >
                  {{ t('calibration.remove') }}
                </button>
                <button type="button" class="btn py-0.5 text-xs" @click="confirmRemove = null">
                  {{ t('flags.form.keep') }}
                </button>
              </span>
            </span>
            <span v-if="editing === null && confirmRemove !== r.id" class="flex shrink-0 gap-2 text-xs">
              <button type="button" class="text-accent hover:underline" @click="startEdit(r)">
                {{ t('flags.edit') }}
              </button>
              <button type="button" class="text-bad hover:underline" @click="confirmRemove = r.id">
                {{ t('calibration.remove') }}
              </button>
            </span>
          </li>
        </ol>
      </template>
    </section>

    <!-- in-service period -->
    <form v-else class="flex flex-col gap-4" novalidate @submit.prevent="saveService">
      <p class="text-sm text-ink-2">{{ t('components.explain') }}</p>
      <p v-if="c.is_dcp" class="text-sm text-ink-3">{{ t('components.dcpHint') }}</p>
      <template v-else>
        <p
          v-if="serviceError"
          class="rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-sm"
          role="alert"
        >
          {{ t('common.error') }}
        </p>
        <label class="flex flex-col gap-1.5">
          <span class="label">{{ t('components.from') }}</span>
          <input v-model="from" type="datetime-local" class="input py-1.5" />
          <span class="text-xs text-ink-3">{{ t('components.fromHint') }}</span>
        </label>
        <label class="flex flex-col gap-1.5">
          <span class="label">{{ t('components.to') }}</span>
          <input v-model="to" type="datetime-local" class="input py-1.5" />
          <span class="text-xs text-ink-3">{{ t('components.toHint') }}</span>
        </label>
        <p v-if="serviceIssue" class="text-xs text-bad">{{ t('components.order') }}</p>
        <p class="rounded-md border border-line bg-sunken/60 p-3 text-xs text-ink-2">
          {{ t('components.effect') }}
        </p>
        <p v-if="job" class="text-xs text-ink-2" role="status">
          {{ t('mandatory.saved') }}
          <RouterLink to="/admin/jobs" class="text-accent hover:underline">{{
            t('mandatory.jobLink', { id: job.id })
          }}</RouterLink>
        </p>
        <div class="flex gap-2 border-t border-line pt-4">
          <button
            type="submit"
            class="btn-primary"
            :disabled="!!serviceIssue || serviceUnchanged || serviceBusy"
          >
            {{ t('components.save') }}
          </button>
        </div>
      </template>
    </form>
  </div>
</template>
