<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { api, ApiProblem } from '@/api/client'
import type { ComponentRow, Part, PartDraft } from '@/api/types'
import { useLoader } from '@/composables/useLoader'
import { useDisplayStore } from '@/stores/display'
import { DEFAULT_SYSTEM } from '@/stores/live'
import { missingParts, partModel, sortParts, usualParts } from '@/utils/parts'

// A sensor's physical parts (R3.7): each with its own numbers. Replacing a part closes the old one and adds the new
// one, so the history of what was installed when stays. Parts never change the sensor's figures.
const props = defineProps<{ component: ComponentRow }>()
const emit = defineEmits<{ changed: [] }>()
const { t } = useI18n()
const display = useDisplayStore()
const today = new Date().toISOString().slice(0, 10)
const errorText = (code: string) =>
  t(`records.error.${code}`) === `records.error.${code}` ? t('common.error') : t(`records.error.${code}`)

// Every part ever recorded; the installed ones are those not removed.
const all = useLoader<Part[]>(() => api.parts(props.component.id, true))
void all.load()
const fields = ref<string[]>([])
void display.system(DEFAULT_SYSTEM).then((info) => {
  const site = info.sites.find((s) => s.slug === props.component.site)
  fields.value = site?.components.find((c) => c.type === props.component.type)?.fields ?? []
})
const usual = computed(() => usualParts(props.component.type, fields.value))
const installed = computed(() =>
  sortParts(
    (all.data.value ?? []).filter((p) => p.removed_on === null),
    usual.value,
  ),
)
const removed = computed(() =>
  (all.data.value ?? [])
    .filter((p) => p.removed_on !== null)
    .sort((a, b) => (b.removed_on ?? '').localeCompare(a.removed_on ?? '')),
)
const missing = computed(() => (all.data.value ? missingParts(usual.value, installed.value) : []))
const showRemoved = ref(false)
const byId = (id: number | null) => (id === null ? null : (all.data.value ?? []).find((p) => p.id === id))

// ---- one form at a time: add, edit, replace or remove ----------------------------------------------------
type Mode = { kind: 'add' } | { kind: 'edit' | 'replace' | 'remove'; part: Part }
const mode = ref<Mode | null>(null)
const KEYS = [
  'role',
  'manufacturer',
  'model',
  'part_number',
  'serial_number',
  'firmware',
  'installed_on',
  'notes',
] as const
const draft = reactive<Record<(typeof KEYS)[number], string>>(
  Object.fromEntries(KEYS.map((k) => [k, ''])) as Record<(typeof KEYS)[number], string>,
)
const removal = reactive({ on: today, notes: '' })
const busy = ref(false)
const error = ref<string | null>(null)

function fill(from: Partial<Record<(typeof KEYS)[number], string | null | undefined>>) {
  for (const k of KEYS) draft[k] = from[k] ?? ''
}
function startAdd(role = '') {
  fill({ role, installed_on: today })
  mode.value = { kind: 'add' }
  error.value = null
}
function startEdit(p: Part) {
  fill(p)
  mode.value = { kind: 'edit', part: p }
  error.value = null
}
function startReplace(p: Part) {
  // the new part is usually the same model: keep what it is, ask for its own serial number
  fill({
    role: p.role,
    manufacturer: p.manufacturer,
    model: p.model,
    part_number: p.part_number,
    installed_on: today,
  })
  Object.assign(removal, { on: today, notes: '' })
  mode.value = { kind: 'replace', part: p }
  error.value = null
}
function startRemove(p: Part) {
  Object.assign(removal, { on: today, notes: '' })
  mode.value = { kind: 'remove', part: p }
  error.value = null
}
const body = (): PartDraft =>
  Object.fromEntries(KEYS.map((k) => [k, draft[k].trim() || null])) as unknown as PartDraft

const issue = computed(() => {
  const m = mode.value
  if (!m) return null
  if (m.kind !== 'remove') {
    if (!draft.role.trim()) return 'role_required'
    if (draft.installed_on && draft.installed_on > today) return 'date_in_future'
  }
  if (m.kind === 'replace' || m.kind === 'remove') {
    if (!removal.on) return 'invalid_date'
    if (removal.on > today) return 'date_in_future'
    if (m.part.installed_on && removal.on < m.part.installed_on) return 'removed_before_installed'
  }
  if (m.kind === 'replace' && draft.installed_on && draft.installed_on < removal.on)
    return 'installed_before_removed'
  return null
})

async function submit() {
  const m = mode.value
  if (!m || issue.value || busy.value) return
  busy.value = true
  error.value = null
  try {
    if (m.kind === 'add') await api.addPart(props.component.id, body())
    else if (m.kind === 'edit') await api.updatePart(m.part.id, body())
    else if (m.kind === 'replace')
      await api.replacePart(m.part.id, {
        removed_on: removal.on,
        notes: removal.notes.trim() || null,
        part: body(),
      })
    else await api.removePart(m.part.id, removal.on, removal.notes.trim() || null)
    mode.value = null
    await all.load({ silent: true })
    emit('changed')
  } catch (e) {
    error.value = e instanceof ApiProblem ? e.code : 'network_error'
  } finally {
    busy.value = false
  }
}
const formTitle = computed(() => {
  const m = mode.value
  if (!m) return ''
  return m.kind === 'add' ? t('parts.addTitle') : t(`parts.${m.kind}Title`, { role: m.part.role })
})
const saveLabel = computed(() =>
  mode.value?.kind === 'replace'
    ? t('parts.saveReplace')
    : mode.value?.kind === 'remove'
      ? t('parts.saveRemove')
      : t('parts.save'),
)
</script>

<template>
  <section class="flex flex-col gap-3" :aria-label="t('records.tab.parts')">
    <p class="text-sm text-ink-2">{{ t('parts.intro') }}</p>

    <div class="flex flex-wrap items-center gap-2">
      <h3 class="eyebrow">{{ t('parts.installed', { n: installed.length }, installed.length) }}</h3>
      <button v-if="mode === null" type="button" class="btn-primary ml-auto py-1 text-xs" @click="startAdd()">
        {{ t('parts.add') }}
      </button>
    </div>

    <!-- add / edit / replace / remove -->
    <form
      v-if="mode !== null"
      class="flex flex-col gap-3 rounded-md border border-line bg-sunken/60 p-3"
      novalidate
      data-testid="part-form"
      @submit.prevent="submit"
    >
      <h3 class="text-sm font-semibold">{{ formTitle }}</h3>
      <p v-if="error" class="rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-sm" role="alert">
        {{ errorText(error) }}
      </p>

      <!-- the part that comes out -->
      <fieldset v-if="mode.kind === 'replace' || mode.kind === 'remove'" class="flex flex-col gap-3">
        <legend v-if="mode.kind === 'replace'" class="label mb-1">{{ t('parts.replaceOld') }}</legend>
        <p class="num text-xs text-ink-2">
          {{ mode.part.role }} · {{ partModel(mode.part) || '—' }}
          <template v-if="mode.part.serial_number">
            · {{ t('records.sn', { sn: mode.part.serial_number }) }}</template
          >
          <template v-if="mode.part.installed_on">
            · {{ t('parts.installedOn', { date: mode.part.installed_on }) }}</template
          >
        </p>
        <div class="grid gap-3 sm:grid-cols-2">
          <label class="flex flex-col gap-1.5">
            <span class="label">{{ t('parts.removedOn') }}</span>
            <input
              v-model="removal.on"
              type="date"
              :min="mode.part.installed_on ?? undefined"
              :max="today"
              class="input num py-1.5"
            />
          </label>
          <label class="flex flex-col gap-1.5">
            <span class="label">{{ t('parts.reason') }}</span>
            <input v-model="removal.notes" type="text" maxlength="500" class="input py-1.5" />
          </label>
        </div>
        <p v-if="mode.kind === 'remove'" class="text-xs text-ink-3">{{ t('parts.removeHint') }}</p>
      </fieldset>

      <!-- the part that goes in, or the part being added or edited -->
      <fieldset v-if="mode.kind !== 'remove'" class="flex flex-col gap-3">
        <legend v-if="mode.kind === 'replace'" class="label mb-1">{{ t('parts.replaceNew') }}</legend>
        <div class="grid gap-3 sm:grid-cols-2">
          <div class="flex flex-col gap-1.5 sm:col-span-2">
            <label for="part-role" class="label">{{ t('parts.role') }}</label>
            <input
              id="part-role"
              v-model="draft.role"
              type="text"
              maxlength="60"
              class="input py-1.5"
              list="part-roles"
              aria-describedby="part-role-hint"
            />
            <datalist id="part-roles">
              <option v-for="r in usual" :key="r" :value="r" />
            </datalist>
            <span id="part-role-hint" class="text-[0.6875rem] text-ink-3">{{ t('parts.roleHint') }}</span>
          </div>
          <label v-for="k in ['manufacturer', 'model'] as const" :key="k" class="flex flex-col gap-1.5">
            <span class="label">{{ t(`records.meta.${k}`) }}</span>
            <input v-model="draft[k]" type="text" maxlength="100" class="input py-1.5" />
          </label>
          <label
            v-for="k in ['part_number', 'serial_number'] as const"
            :key="k"
            class="flex flex-col gap-1.5"
          >
            <span class="label">{{ t(`records.meta.${k}`) }}</span>
            <input v-model="draft[k]" type="text" maxlength="100" class="input num py-1.5" />
          </label>
          <label class="flex flex-col gap-1.5">
            <span class="label">{{ t('records.meta.firmware') }}</span>
            <input v-model="draft.firmware" type="text" maxlength="100" class="input py-1.5" />
          </label>
          <label class="flex flex-col gap-1.5">
            <span class="label">{{ t('records.meta.installed_on') }}</span>
            <input v-model="draft.installed_on" type="date" :max="today" class="input num py-1.5" />
          </label>
        </div>
        <label class="flex flex-col gap-1.5">
          <span class="label">{{ t('records.meta.notes') }}</span>
          <textarea v-model="draft.notes" rows="2" maxlength="500" class="input" />
        </label>
        <p class="-mt-1 text-xs text-ink-3">{{ t('records.serialHint') }}</p>
      </fieldset>

      <p v-if="issue && (mode.kind === 'remove' || draft.role)" class="text-xs text-bad">
        {{ errorText(issue) }}
      </p>
      <div class="flex gap-2">
        <button
          type="submit"
          :class="mode.kind === 'remove' ? 'btn-danger' : 'btn-primary'"
          :disabled="!!issue || busy"
        >
          {{ saveLabel }}
        </button>
        <button type="button" class="btn" @click="mode = null">{{ t('flags.form.cancel') }}</button>
      </div>
    </form>

    <!-- installed now -->
    <div v-if="!all.data.value" class="h-24 animate-pulse rounded bg-sunken" aria-busy="true" />
    <template v-else>
      <p v-if="!installed.length && !missing.length" class="text-sm text-ink-3">{{ t('parts.none') }}</p>
      <ul class="flex flex-col" data-testid="parts-installed">
        <li
          v-for="p in installed"
          :key="p.id"
          class="grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-0.5 border-t border-line py-2 text-sm"
          data-testid="part-row"
        >
          <span class="min-w-0">
            <span class="font-medium">{{ p.role }}</span>
            <span class="text-ink-2"> · {{ partModel(p) || '—' }}</span>
            <span class="num block text-xs text-ink-2">
              {{ t('records.meta.part_number') }} {{ p.part_number ?? '—' }} ·
              {{ t('records.meta.serial_number') }} {{ p.serial_number ?? '—' }}
              <template v-if="p.firmware"> · {{ t('records.meta.firmware') }} {{ p.firmware }}</template>
            </span>
            <span class="num block text-xs text-ink-3">
              {{
                p.installed_on
                  ? t('parts.installedOn', { date: p.installed_on })
                  : t('parts.installedUnknown')
              }}
              <template v-if="byId(p.replaces)?.serial_number">
                · {{ t('parts.replaces', { sn: byId(p.replaces)!.serial_number }) }}</template
              >
            </span>
            <span v-if="p.notes" class="block text-xs text-ink-2">{{ p.notes }}</span>
          </span>
          <span v-if="mode === null" class="flex shrink-0 items-start gap-3 text-xs">
            <button type="button" class="text-accent hover:underline" @click="startEdit(p)">
              {{ t('flags.edit') }}
            </button>
            <button type="button" class="text-accent hover:underline" @click="startReplace(p)">
              {{ t('parts.replace') }}
            </button>
            <button type="button" class="text-bad hover:underline" @click="startRemove(p)">
              {{ t('parts.remove') }}
            </button>
          </span>
        </li>
        <!-- usual parts with no record yet -->
        <li
          v-for="r in missing"
          :key="`missing-${r}`"
          class="flex items-center gap-3 border-t border-dashed border-line py-2 text-sm"
          data-testid="part-missing"
        >
          <span class="min-w-0 flex-1 text-ink-3">
            {{ r }} <span class="text-xs">· {{ t('parts.notRecorded') }}</span>
          </span>
          <button v-if="mode === null" type="button" class="btn py-0.5 text-xs" @click="startAdd(r)">
            {{ t('parts.addOne') }}
          </button>
        </li>
      </ul>

      <!-- history -->
      <template v-if="removed.length">
        <button
          type="button"
          class="self-start text-xs text-accent hover:underline"
          :aria-expanded="showRemoved"
          @click="showRemoved = !showRemoved"
        >
          {{ showRemoved ? t('parts.hideRemoved') : t('parts.showRemoved', { n: removed.length }) }}
        </button>
        <ol v-if="showRemoved" class="flex flex-col" data-testid="parts-removed">
          <li v-for="p in removed" :key="p.id" class="border-t border-line py-2 text-xs text-ink-2">
            <span class="font-medium text-ink">{{ p.role }}</span> · {{ partModel(p) || '—' }}
            <template v-if="p.serial_number"> · {{ t('records.sn', { sn: p.serial_number }) }}</template>
            <span class="num block">
              {{ t('parts.span', { from: p.installed_on ?? '?', to: p.removed_on }) }}
              <template v-if="byId(p.replaced_by)?.serial_number">
                · {{ t('parts.replacedBy', { sn: byId(p.replaced_by)!.serial_number }) }}</template
              >
            </span>
            <span v-if="p.removed_reason" class="block">{{ p.removed_reason }}</span>
            <span v-if="p.notes" class="block text-ink-3">{{ p.notes }}</span>
          </li>
        </ol>
      </template>
    </template>
  </section>
</template>
