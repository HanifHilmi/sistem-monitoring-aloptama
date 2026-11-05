<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import { api, ApiProblem } from '@/api/client'
import {
  FLAG_REASONS,
  type ComponentRow,
  type FlagChange,
  type FlagPreview,
  type FlagReason,
  type FlagRow,
} from '@/api/types'
import { useLoader } from '@/composables/useLoader'
import type { Locale } from '@/i18n'
import { int } from '@/utils/format'
import { formatDays, formatDuration, fromInput, toInput } from '@/utils/flags'

// Create or edit a manual flag (FR-DQ-006): components, a UTC range to the minute, a reason and a note. Before
// anything is saved, the effect panel shows per component how many valid minutes will count as lost.
const props = defineProps<{
  system: string
  /** the flag being edited; absent for a new one */
  flag?: FlagRow | null
  /** a new flag started from a sensor chart or the minute map */
  initial?: { components?: { site: string; type: string }[]; start?: string; end?: string }
}>()
const emit = defineEmits<{ done: [change: FlagChange | null]; cancel: [] }>()
const { t, locale } = useI18n()
const lc = computed(() => locale.value as Locale)

const comps = useLoader<ComponentRow[]>(() => api.components(props.system))
void comps.load()

const selected = ref<number[]>([...(props.flag?.component_ids ?? [])].sort((a, b) => a - b))
const from = ref(toInput(props.flag?.start ?? props.initial?.start))
const to = ref(toInput(props.flag?.end ?? props.initial?.end))
const reason = ref<FlagReason | null>(props.flag?.reason ?? null)
const note = ref(props.flag?.note ?? '')
watch(
  () => comps.data.value,
  (list) => {
    const want = props.initial?.components
    if (!list || props.flag || !want) return
    selected.value = list
      .filter((c) => !c.is_dcp && want.some((w) => w.site === c.site && w.type === c.type))
      .map((c) => c.id)
  },
  { immediate: true },
)

const sites = computed(() => {
  const by = new Map<string, { site: string; name: ComponentRow['site_name']; rows: ComponentRow[] }>()
  for (const c of comps.data.value ?? []) {
    if (c.is_dcp) continue
    const g = by.get(c.site) ?? { site: c.site, name: c.site_name, rows: [] }
    g.rows.push(c)
    by.set(c.site, g)
  }
  return [...by.values()]
})
const byId = computed(() => new Map((comps.data.value ?? []).map((c) => [c.id, c])))
const label = (id: number) => {
  const c = byId.value.get(id)
  return c ? `${c.site_name[lc.value]} · ${c.name[lc.value]}` : `#${id}`
}
function toggle(id: number) {
  selected.value = selected.value.includes(id)
    ? selected.value.filter((x) => x !== id)
    : [...selected.value, id].sort((a, b) => a - b)
}

// ---- range ------------------------------------------------------------------------------------------
const startMs = computed(() => (from.value ? Date.parse(fromInput(from.value)) : NaN))
const endMs = computed(() => (to.value ? Date.parse(fromInput(to.value)) : NaN))
const issue = computed<'order' | 'future' | null>(() => {
  if (!from.value || !to.value) return null
  if (endMs.value <= startMs.value) return 'order'
  if (endMs.value > Math.ceil(Date.now() / 60_000) * 60_000) return 'future'
  return null
})
const minutes = computed(() =>
  from.value && to.value && !issue.value ? (endMs.value - startMs.value) / 60_000 : 0,
)
const long = computed(() => minutes.value > 31 * 1440)
const noteOk = computed(() => note.value.trim().length >= 3)
const ready = computed(() => selected.value.length > 0 && minutes.value > 0 && !!reason.value && noteOk.value)
const unchanged = computed(() => {
  const f = props.flag
  return (
    !!f &&
    [...f.component_ids].sort((x, y) => x - y).join() === selected.value.join() &&
    toInput(f.start) === from.value &&
    toInput(f.end) === to.value &&
    f.reason === reason.value &&
    f.note === note.value.trim()
  )
})

// ---- effect preview ---------------------------------------------------------------------------------
const preview = ref<FlagPreview | 'loading' | 'error' | null>(null)
let timer: ReturnType<typeof setTimeout> | undefined
let seq = 0
watch(
  () => `${selected.value.join()}|${from.value}|${to.value}|${issue.value}`,
  () => {
    clearTimeout(timer)
    if (!selected.value.length || !minutes.value) {
      preview.value = null
      return
    }
    preview.value = 'loading'
    timer = setTimeout(loadPreview, 250)
  },
  { immediate: true },
)
onBeforeUnmount(() => clearTimeout(timer))
async function loadPreview() {
  const mine = ++seq
  try {
    const p = await api.previewFlag(
      {
        system: props.system,
        component_ids: selected.value,
        start: fromInput(from.value),
        end: fromInput(to.value),
      },
      props.flag?.id,
    )
    if (mine === seq) preview.value = p
  } catch {
    if (mine === seq) preview.value = 'error'
  }
}
const lostTotal = computed(() =>
  typeof preview.value === 'object' && preview.value
    ? preview.value.components.reduce((n, c) => n + c.lost, 0)
    : 0,
)
const alreadyTotal = computed(() =>
  typeof preview.value === 'object' && preview.value
    ? preview.value.components.reduce((n, c) => n + c.already, 0)
    : 0,
)

// ---- save and remove --------------------------------------------------------------------------------
const busy = ref(false)
const error = ref<string | null>(null)
const result = ref<{ kind: 'saved' | 'removed'; change: FlagChange } | null>(null)
const confirming = ref(false)
async function run(kind: 'saved' | 'removed', call: () => Promise<FlagChange>) {
  busy.value = true
  error.value = null
  try {
    result.value = { kind, change: await call() }
  } catch (e) {
    error.value = e instanceof ApiProblem ? e.code : 'network_error'
  } finally {
    busy.value = false
    confirming.value = false
  }
}
function save() {
  if (!ready.value || busy.value) return
  const draft = {
    system: props.system,
    component_ids: selected.value,
    start: fromInput(from.value),
    end: fromInput(to.value),
    reason: reason.value!,
    note: note.value.trim(),
  }
  void run('saved', () => (props.flag ? api.updateFlag(props.flag.id, draft) : api.createFlag(draft)))
}
function remove() {
  if (props.flag) void run('removed', () => api.removeFlag(props.flag!.id))
}
const jobDays = (c: FlagChange) =>
  c.job?.params.from && c.job.params.to
    ? formatDays({ from: c.job.params.from, to: c.job.params.to }, lc.value)
    : ''
const errorText = (code: string) =>
  t(`flags.error.${code}`) === `flags.error.${code}` ? t('common.error') : t(`flags.error.${code}`)
</script>

<template>
  <div v-if="result" class="flex flex-col gap-3 py-1" role="status" data-testid="flag-result">
    <p class="rounded-md border border-ok/40 bg-ok/10 px-3 py-2 text-sm">
      {{ t(`flags.form.${result.kind}`, { id: result.change.flag.id }) }}
    </p>
    <p v-if="result.change.job" class="text-sm text-ink-2">
      {{ t('flags.form.recalc', { days: jobDays(result.change) }) }}
      <RouterLink to="/admin/jobs" class="text-accent hover:underline">{{
        t('mandatory.jobLink', { id: result.change.job.id })
      }}</RouterLink>
    </p>
    <div>
      <button type="button" class="btn-primary" @click="emit('done', result.change)">
        {{ t('flags.form.done') }}
      </button>
    </div>
  </div>

  <form v-else class="flex flex-col gap-4 py-1" novalidate @submit.prevent="save">
    <p v-if="error" class="rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-sm" role="alert">
      {{ errorText(error) }}
    </p>

    <fieldset class="flex flex-col gap-2">
      <legend class="label mb-1.5">{{ t('flags.form.components') }}</legend>
      <div v-if="!comps.data.value" class="h-24 animate-pulse rounded-md bg-sunken" aria-busy="true" />
      <div
        v-for="g in sites"
        v-else
        :key="g.site"
        class="grid grid-cols-[6.5rem_minmax(0,1fr)] items-start gap-2"
      >
        <span class="pt-1 text-xs text-ink-2">{{ g.name[lc] }}</span>
        <span class="flex flex-wrap gap-1" role="group" :aria-label="g.name[lc]">
          <button
            v-for="c in g.rows"
            :key="c.id"
            type="button"
            class="num rounded-md border px-2 py-0.5 text-xs"
            :class="
              selected.includes(c.id)
                ? 'border-flag bg-flag/15 font-medium text-ink'
                : 'border-line text-ink-2 hover:border-line-strong hover:text-ink'
            "
            :aria-pressed="selected.includes(c.id)"
            :title="c.name[lc]"
            :aria-label="`${c.name[lc]} (${c.type})`"
            @click="toggle(c.id)"
          >
            {{ c.type }}
          </button>
        </span>
      </div>
      <p v-if="selected.length" class="text-xs text-ink">
        {{ t('flags.form.selected', { list: selected.map(label).join('; ') }) }}
      </p>
      <p v-else-if="comps.data.value" class="text-xs text-warn">{{ t('flags.form.noneSelected') }}</p>
      <p class="text-xs text-ink-3">{{ t('flags.form.dcp') }}</p>
    </fieldset>

    <div class="grid gap-3 sm:grid-cols-2">
      <label class="flex flex-col gap-1.5">
        <span class="label">{{ t('flags.form.from') }}</span>
        <input v-model="from" type="datetime-local" step="60" class="input num py-1.5" />
      </label>
      <label class="flex flex-col gap-1.5">
        <span class="label">{{ t('flags.form.to') }}</span>
        <input v-model="to" type="datetime-local" step="60" class="input num py-1.5" />
      </label>
    </div>
    <p v-if="issue" class="-mt-2 text-xs text-bad">{{ t(`flags.form.${issue}`) }}</p>
    <p v-else-if="minutes" class="-mt-2 text-xs text-ink-2">
      {{ t('flags.form.duration', { d: formatDuration(minutes, t) }) }} ·
      <span class="text-ink-3">{{ t('flags.form.toHint') }}</span>
    </p>
    <p v-if="long" class="-mt-2 rounded-md border border-warn/40 bg-warn/10 px-3 py-2 text-xs">
      {{ t('flags.form.long') }}
    </p>

    <fieldset>
      <legend class="label mb-1.5">{{ t('flags.form.reason') }}</legend>
      <div class="flex flex-wrap gap-1.5" role="radiogroup" :aria-label="t('flags.form.reason')">
        <button
          v-for="r in FLAG_REASONS"
          :key="r"
          type="button"
          role="radio"
          :aria-checked="reason === r"
          class="rounded-md border px-2.5 py-1 text-sm"
          :class="
            reason === r
              ? 'border-flag bg-flag/15 font-medium text-ink'
              : 'border-line text-ink-2 hover:border-line-strong hover:text-ink'
          "
          @click="reason = r"
        >
          {{ t(`flags.reason.${r}`) }}
        </button>
      </div>
      <p v-if="reason" class="mt-1.5 text-xs text-ink-3">{{ t(`flags.reasonHint.${reason}`) }}</p>
    </fieldset>

    <label class="flex flex-col gap-1.5">
      <span class="label">{{ t('flags.form.note') }}</span>
      <textarea v-model="note" rows="3" maxlength="500" class="input" />
      <span class="flex justify-between gap-3 text-xs text-ink-3">
        <span>{{ t('flags.form.noteHint') }}</span>
        <span class="num shrink-0">{{ note.length }}/500</span>
      </span>
    </label>

    <section
      v-if="preview"
      class="rounded-md border border-line bg-sunken/60 p-3 text-xs"
      :aria-label="t('flags.form.effect')"
      data-testid="flag-effect"
    >
      <h3 class="eyebrow mb-2">{{ t('flags.form.effect') }}</h3>
      <div v-if="preview === 'loading'" class="h-14 animate-pulse rounded bg-sunken" aria-busy="true" />
      <p v-else-if="preview === 'error'" class="text-warn">{{ t('common.error') }}</p>
      <template v-else>
        <table class="w-full">
          <thead class="text-left text-ink-3">
            <tr>
              <th class="py-1 font-normal">{{ t('flags.form.colComponent') }}</th>
              <th class="text-right font-normal">{{ t('flags.form.colRange') }}</th>
              <th class="text-right font-normal">{{ t('flags.form.colLost') }}</th>
              <th class="text-right font-normal">{{ t('flags.form.colAlready') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="c in preview.components" :key="c.id" class="border-t border-line">
              <td class="py-1 pr-2">{{ label(c.id) }}</td>
              <td class="num text-right">{{ int(c.minutes, lc) }}</td>
              <td class="num text-right" :class="c.lost ? 'font-semibold text-flag' : 'text-ink-3'">
                {{ c.lost ? `−${int(c.lost, lc)}` : '0' }}
              </td>
              <td class="num text-right text-ink-3">{{ int(c.already, lc) }}</td>
            </tr>
          </tbody>
        </table>
        <p class="mt-2 text-ink-2">
          {{
            t(
              'flags.form.effectSummary',
              { lost: int(lostTotal, lc), days: preview.days ? formatDays(preview.days, lc) : '—' },
              lostTotal,
            )
          }}
        </p>
        <p v-if="alreadyTotal" class="mt-1 text-ink-3">{{ t('flags.form.effectAlready') }}</p>
      </template>
    </section>

    <div class="flex flex-wrap items-center gap-2 border-t border-line pt-4">
      <button type="submit" class="btn-primary" :disabled="!ready || unchanged || busy">
        {{ flag ? t('flags.form.saveEdit') : t('flags.form.save') }}
      </button>
      <button type="button" class="btn" @click="emit('cancel')">{{ t('flags.form.cancel') }}</button>
      <template v-if="flag">
        <button
          v-if="!confirming"
          type="button"
          class="btn-danger ml-auto"
          :disabled="busy"
          @click="confirming = true"
        >
          {{ t('flags.form.remove') }}
        </button>
      </template>
    </div>
    <div
      v-if="flag && confirming"
      class="flex flex-col gap-2 rounded-md border border-bad/40 bg-bad/5 p-3 text-sm"
      role="alertdialog"
      :aria-label="t('flags.form.remove')"
    >
      <p>{{ t('flags.form.removeConfirm') }}</p>
      <div class="flex gap-2">
        <button type="button" class="btn-danger" :disabled="busy" @click="remove">
          {{ t('flags.form.removeYes') }}
        </button>
        <button type="button" class="btn" @click="confirming = false">{{ t('flags.form.keep') }}</button>
      </div>
    </div>
  </form>
</template>
