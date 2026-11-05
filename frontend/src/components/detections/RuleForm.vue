<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import { api, ApiProblem } from '@/api/client'
import {
  RULE_TYPES,
  type FieldHistory,
  type Rule,
  type RuleChange,
  type RuleDraft,
  type RuleDryRun,
  type RuleParams,
  type RuleType,
  type RuleVersion,
  type SystemInfo,
} from '@/api/types'
import { useLoader } from '@/composables/useLoader'
import type { Locale } from '@/i18n'
import { formatDuration, formatRange } from '@/utils/flags'
import { int } from '@/utils/format'
import { evidenceText, ruleText, value } from '@/utils/rules'
import { formatUtc } from '@/utils/time'

// Create or change a validity rule (FR-DQ-001/002). The history box shows what the field's data looks like and the
// proposed starting values (OPEN-08); the dry run shows what the draft would have raised over the last 30 days.
// Saving makes a new version that replaces the old one: the old versions' open suspects are withdrawn, decided
// detections keep their version. A rule that never raised anything may be deleted.
const props = defineProps<{
  system: string
  info: SystemInfo
  componentType: string
  field: string
  rule?: Rule | null
  /** rule types already used for this field and scope (a new rule may not repeat one) */
  taken?: string[]
  /** the field's other rules, for the overlap warnings */
  siblings?: Rule[]
}>()
const emit = defineEmits<{ done: [change: RuleChange | null]; cancel: [] }>()
const { t, locale } = useI18n()
const lc = computed(() => locale.value as Locale)
const unit = computed(() => props.info.fields[props.field]?.unit ?? null)
const sites = computed(() =>
  props.info.sites.filter((s) =>
    s.components.some((c) => c.type === props.componentType && c.fields.includes(props.field)),
  ),
)

const type = ref<RuleType>(props.rule?.type ?? 'range')
const site = ref<string>(props.rule?.site ?? '')
const enabled = ref(props.rule ? props.rule.enabled || props.rule.proposed : false)
const p = props.rule?.params ?? {}
const min = ref(p.min ?? null)
const max = ref(p.max ?? null)
const minutes = ref(p.minutes ?? 180)
const ignore = ref((p.ignore ?? []).join(', '))
const change = ref(p.max_change ?? null)
const win = ref(p.window ?? 1)

/** An emptied number input gives '' rather than null. */
const numOrNull = (x: unknown) => (x === '' || x === null || x === undefined ? null : Number(x))
const params = computed<RuleParams>(() => {
  if (type.value === 'range') return { min: numOrNull(min.value), max: numOrNull(max.value) }
  if (type.value === 'stuck') {
    const values = ignore.value
      .split(',')
      .map((x) => x.trim().replace(',', '.'))
      .filter(Boolean)
      .map(Number)
    return { minutes: minutes.value, ...(values.length ? { ignore: values } : {}) }
  }
  return { max_change: numOrNull(change.value) ?? 0, ...(win.value > 1 ? { window: win.value } : {}) }
})
const issue = computed<string | null>(() => {
  const v = params.value
  if (type.value === 'range') {
    if (v.min === null && v.max === null) return 'range_needs_a_limit'
    if (v.min !== null && v.max !== null && v.min! >= v.max!) return 'invalid_range'
  }
  if (type.value === 'stuck') {
    if (!Number.isInteger(v.minutes) || v.minutes! < 5 || v.minutes! > 1440) return 'invalid_minutes'
    if (v.ignore?.some((x) => Number.isNaN(x))) return 'invalid_ignore'
  }
  if (type.value === 'spike') {
    if (!((v.max_change ?? 0) > 0)) return 'invalid_change'
    if (!Number.isInteger(win.value) || win.value < 1 || win.value > 60) return 'invalid_window'
  }
  if (!props.rule && props.taken?.includes(`${type.value}|${site.value}`)) return 'rule_exists'
  return null
})
const draft = computed<RuleDraft>(() => ({
  system: props.system,
  component_type: props.componentType,
  field: props.field,
  site: site.value || null,
  type: type.value,
  params: params.value,
  enabled: enabled.value,
}))
/** Parameters in one key order, so "unchanged" does not depend on how the server ordered them. */
const canon = (p: RuleParams) =>
  JSON.stringify(
    Object.entries(p)
      .filter(([, v]) => v !== undefined)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([k, v]) => [k, Array.isArray(v) ? [...v].sort((x, y) => x - y) : v]),
  )
const unchanged = computed(
  () =>
    !!props.rule &&
    !props.rule.proposed &&
    canon(props.rule.params) === canon(params.value) &&
    props.rule.enabled === enabled.value &&
    (props.rule.site ?? '') === site.value,
)

// ---- overlap warnings ----------------------------------------------------------------------------------
const sameKind = computed(() => (props.siblings ?? []).filter((r) => r.type === type.value))
/** A site rule replaces the all-sites rule of the same kind there; an all-sites rule gives way to site rules. */
const replaces = computed(() => (site.value ? sameKind.value.find((r) => !r.site) : undefined))
const keptAt = computed(() => (site.value ? [] : sameKind.value.filter((r) => r.site)))

// ---- history and proposed values -----------------------------------------------------------------------
const history = useLoader<FieldHistory>(() =>
  api.fieldHistory(props.system, props.componentType, props.field),
)
void history.load()
function useProposal() {
  const h = history.data.value
  if (!h) return
  const v = h.proposed[type.value]
  if (!v) return
  if (type.value === 'range') {
    min.value = v.min ?? null
    max.value = v.max ?? null
  } else if (type.value === 'stuck') {
    minutes.value = v.minutes ?? 180
    ignore.value = (v.ignore ?? []).join(', ')
  } else {
    change.value = v.max_change ?? null
    win.value = v.window ?? 1
  }
}

// ---- dry run ---------------------------------------------------------------------------------------------
const dry = ref<RuleDryRun | 'loading' | 'error' | null>(null)
let timer: ReturnType<typeof setTimeout> | undefined
let seq = 0
watch(
  () => JSON.stringify([draft.value.type, draft.value.site, draft.value.params, issue.value]),
  () => {
    clearTimeout(timer)
    if (issue.value) {
      dry.value = null
      return
    }
    dry.value = 'loading'
    timer = setTimeout(async () => {
      const mine = ++seq
      try {
        const r = await api.dryRun(draft.value, props.rule?.id)
        if (mine === seq) dry.value = r
      } catch {
        if (mine === seq) dry.value = 'error'
      }
    }, 300)
  },
  { immediate: true },
)
onBeforeUnmount(() => clearTimeout(timer))

// ---- versions, save --------------------------------------------------------------------------------------
const versions = useLoader<RuleVersion[]>(() => api.ruleVersions(props.rule!.id))
if (props.rule) void versions.load()
const busy = ref(false)
const error = ref<string | null>(null)
const result = ref<RuleChange | null>(null)
async function save() {
  if (issue.value || busy.value) return
  busy.value = true
  error.value = null
  try {
    result.value = props.rule
      ? await api.updateRule(props.rule.id, draft.value)
      : await api.createRule(draft.value)
  } catch (e) {
    error.value = e instanceof ApiProblem ? e.code : 'network_error'
  } finally {
    busy.value = false
  }
}
const confirmingDelete = ref(false)
async function remove() {
  if (!props.rule || busy.value) return
  busy.value = true
  error.value = null
  try {
    await api.deleteRule(props.rule.id)
    emit('done', null)
  } catch (e) {
    error.value = e instanceof ApiProblem ? e.code : 'network_error'
  } finally {
    busy.value = false
    confirmingDelete.value = false
  }
}

/** What each version changed compared with the one before it (versions come newest first). */
function changes(i: number): string {
  const list = versions.data.value ?? []
  const v = list[i]!
  const prev = list[i + 1]
  if (!prev) return v.created_by === 'system' ? t('rules.version.proposed') : t('rules.version.created')
  const out: string[] = []
  if (canon(v.params) !== canon(prev.params))
    out.push(
      t('rules.version.values', { rule: ruleText(props.rule!.type, v.params, unit.value, lc.value, t) }),
    )
  if ((v.site ?? '') !== (prev.site ?? '')) out.push(t('rules.version.scope', { site: siteName(v.site) }))
  if (v.enabled !== prev.enabled) out.push(v.enabled ? t('rules.version.on') : t('rules.version.off'))
  if (!out.length)
    out.push(prev.created_by === 'system' ? t('rules.version.approved') : t('rules.version.saved'))
  return out.join(' · ')
}
const errorText = (code: string) =>
  t(`rules.error.${code}`) === `rules.error.${code}` ? t('common.error') : t(`rules.error.${code}`)
const siteName = (slug: string | null) =>
  slug ? (props.info.sites.find((s) => s.slug === slug)?.name[lc.value] ?? slug) : t('rules.allSites')
</script>

<template>
  <div v-if="result" class="flex flex-col gap-3 py-1" role="status" data-testid="rule-result">
    <p class="rounded-md border border-ok/40 bg-ok/10 px-3 py-2 text-sm">
      {{ t('rules.form.saved', { v: result.rule.version }) }}
    </p>
    <p class="text-sm text-ink-2">
      <template v-if="result.job">
        {{ t('rules.form.rerun') }}
        <RouterLink to="/admin/jobs" class="text-accent hover:underline">{{
          t('mandatory.jobLink', { id: result.job.id })
        }}</RouterLink>
      </template>
      <template v-else>{{ t('rules.form.off') }}</template>
    </p>
    <p v-if="result.withdrawn" class="text-sm text-ink-2" data-testid="withdrawn">
      {{ t('rules.form.withdrawn', { n: result.withdrawn }, result.withdrawn) }}
    </p>
    <p class="text-xs text-ink-3">{{ t('rules.form.keepVersion') }}</p>
    <div>
      <button type="button" class="btn-primary" @click="emit('done', result)">
        {{ t('flags.form.done') }}
      </button>
    </div>
  </div>

  <form v-else class="flex flex-col gap-4 py-1" novalidate @submit.prevent="save">
    <p v-if="error" class="rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-sm" role="alert">
      {{ errorText(error) }}
    </p>
    <p v-if="rule?.proposed" class="rounded-md border border-accent/40 bg-accent-soft px-3 py-2 text-xs">
      {{ t('rules.form.proposedNote') }}
    </p>

    <fieldset>
      <legend class="label mb-1.5">{{ t('rules.form.type') }}</legend>
      <div class="flex flex-wrap gap-1.5" role="radiogroup" :aria-label="t('rules.form.type')">
        <button
          v-for="r in RULE_TYPES"
          :key="r"
          type="button"
          role="radio"
          :aria-checked="type === r"
          :disabled="!!rule && rule.type !== r"
          class="rounded-md border px-2.5 py-1 text-sm disabled:opacity-40"
          :class="
            type === r
              ? 'border-accent bg-accent-soft font-medium text-ink'
              : 'border-line text-ink-2 hover:border-line-strong'
          "
          @click="type = r"
        >
          {{ t(`rules.type.${r}`) }}
        </button>
      </div>
      <p class="mt-1.5 text-xs text-ink-3">{{ t(`rules.typeHint.${type}`) }}</p>
    </fieldset>

    <label class="flex flex-col gap-1.5">
      <span class="label">{{ t('rules.form.scope') }}</span>
      <select v-model="site" class="input py-1.5">
        <option value="">{{ t('rules.allSites') }}</option>
        <option v-for="s in sites" :key="s.slug" :value="s.slug">
          {{ t('rules.onlySite', { site: s.name[lc] }) }}
        </option>
      </select>
      <span class="text-xs text-ink-3">{{ t('rules.form.scopeHint') }}</span>
    </label>
    <p
      v-if="replaces"
      class="-mt-2 rounded-md border border-warn/50 bg-warn/10 px-3 py-2 text-xs"
      data-testid="overlap-warning"
    >
      {{
        t('rules.form.replaces', {
          site: siteName(site),
          rule: ruleText(replaces.type, replaces.params, unit, lc, t),
        })
      }}
    </p>
    <p
      v-else-if="keptAt.length"
      class="-mt-2 rounded-md border border-warn/50 bg-warn/10 px-3 py-2 text-xs"
      data-testid="overlap-warning"
    >
      {{ t('rules.form.keptAt', { sites: keptAt.map((r) => siteName(r.site)).join(', ') }) }}
    </p>

    <div v-if="type === 'range'" class="grid grid-cols-2 gap-3">
      <label class="flex flex-col gap-1.5">
        <span class="label"
          >{{ t('rules.form.min') }} <span class="text-ink-3">{{ unit }}</span></span
        >
        <input v-model.number="min" type="number" step="any" class="input num py-1.5" />
      </label>
      <label class="flex flex-col gap-1.5">
        <span class="label"
          >{{ t('rules.form.max') }} <span class="text-ink-3">{{ unit }}</span></span
        >
        <input v-model.number="max" type="number" step="any" class="input num py-1.5" />
      </label>
    </div>
    <div v-else-if="type === 'stuck'" class="grid grid-cols-2 gap-3">
      <label class="flex flex-col gap-1.5">
        <span class="label">{{ t('rules.form.minutes') }}</span>
        <input v-model.number="minutes" type="number" min="5" max="1440" step="1" class="input num py-1.5" />
      </label>
      <label class="flex flex-col gap-1.5">
        <span class="label">{{ t('rules.form.ignore') }}</span>
        <input v-model="ignore" type="text" inputmode="decimal" class="input num py-1.5" placeholder="0" />
        <span class="text-xs text-ink-3">{{ t('rules.form.ignoreHint') }}</span>
      </label>
    </div>
    <div v-else class="grid grid-cols-2 gap-3">
      <label class="flex flex-col gap-1.5">
        <span class="label"
          >{{ t('rules.form.change') }} <span class="text-ink-3">{{ unit }}</span></span
        >
        <input v-model.number="change" type="number" step="any" min="0" class="input num py-1.5" />
      </label>
      <label class="flex flex-col gap-1.5">
        <span class="label">{{ t('rules.form.window') }}</span>
        <input v-model.number="win" type="number" min="1" max="60" step="1" class="input num py-1.5" />
        <span class="text-xs text-ink-3">{{ t('rules.form.windowHint') }}</span>
      </label>
    </div>
    <p v-if="issue" class="-mt-2 text-xs text-bad">{{ errorText(issue) }}</p>

    <section
      class="rounded-md border border-line bg-sunken/60 p-3 text-xs"
      :aria-label="t('rules.form.history')"
    >
      <h3 class="eyebrow mb-1.5">{{ t('rules.form.history') }}</h3>
      <div v-if="!history.data.value" class="h-12 animate-pulse rounded bg-sunken" aria-busy="true" />
      <template v-else>
        <dl class="num grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-0.5 text-ink-2">
          <dt>{{ t('rules.form.histUsual') }}</dt>
          <dd class="text-right">
            {{ value(history.data.value.p001, null, lc) }} – {{ value(history.data.value.p999, unit, lc) }}
          </dd>
          <dt>{{ t('rules.form.histExtremes') }}</dt>
          <dd class="text-right">
            {{ value(history.data.value.min, null, lc) }} – {{ value(history.data.value.max, unit, lc) }}
          </dd>
          <dt>{{ t('rules.form.histRun') }}</dt>
          <dd class="text-right">{{ formatDuration(history.data.value.longest_run_minutes, t) }}</dd>
          <dt>{{ t('rules.form.histStep') }}</dt>
          <dd class="text-right">
            {{ value(history.data.value.step_p999, null, lc) }} /
            {{ value(history.data.value.largest_step, unit, lc) }}
          </dd>
        </dl>
        <p v-if="!history.data.value.proposed[type]" class="mt-2 text-ink-3">
          {{ t('rules.form.noProposal') }}
        </p>
        <p v-else class="mt-2 flex flex-wrap items-center gap-2">
          <span class="text-ink">{{
            t('rules.form.proposal', {
              rule: ruleText(type, history.data.value.proposed[type]!, unit, lc, t),
            })
          }}</span>
          <button type="button" class="btn ml-auto px-2 py-0.5 text-xs" @click="useProposal">
            {{ t('rules.form.useProposal') }}
          </button>
        </p>
        <p class="mt-1 text-ink-3">
          {{
            t('rules.form.histBasis', {
              n: int(history.data.value.minutes, lc),
              from: (history.data.value.from ?? '—').slice(0, 10),
              to: (history.data.value.to ?? '—').slice(0, 10),
            })
          }}
        </p>
      </template>
    </section>

    <section
      v-if="dry"
      class="rounded-md border p-3 text-xs"
      :class="
        typeof dry === 'object' && dry.intervals > 50
          ? 'border-warn/50 bg-warn/10'
          : 'border-line bg-sunken/60'
      "
      :aria-label="t('rules.form.dryRun')"
      data-testid="dry-run"
    >
      <h3 class="eyebrow mb-1.5">{{ t('rules.form.dryRun') }}</h3>
      <div v-if="dry === 'loading'" class="h-10 animate-pulse rounded bg-sunken" aria-busy="true" />
      <p v-else-if="dry === 'error'" class="text-warn">{{ t('common.error') }}</p>
      <template v-else>
        <p class="text-ink">
          {{
            t(
              'rules.form.dryResult',
              { n: int(dry.intervals, lc), minutes: int(dry.minutes, lc), sites: dry.sites },
              dry.intervals,
            )
          }}
        </p>
        <p v-if="dry.intervals > 50" class="mt-1 font-medium text-warn">{{ t('rules.form.dryTooMany') }}</p>
        <p v-if="dry.overlapping" class="mt-1 font-medium text-warn" data-testid="dry-overlap">
          {{
            t(
              'rules.form.dryOverlap',
              {
                n: int(dry.overlapping, lc),
                rules: (dry.overlapping_types ?? []).map((x) => t(`rules.type.${x}`)).join(', '),
              },
              dry.overlapping,
            )
          }}
        </p>
        <ul v-if="dry.examples.length" class="num mt-1.5 flex flex-col gap-0.5 text-ink-2">
          <li v-for="(e, i) in dry.examples" :key="i">
            {{ siteName(e.site) }} · {{ formatRange(e.start, e.end, lc) }} ·
            {{ evidenceText(type, e.evidence, unit, lc, t) }}
          </li>
        </ul>
      </template>
    </section>

    <label class="flex items-start gap-2 text-sm">
      <input v-model="enabled" type="checkbox" class="mt-0.5 h-4 w-4 accent-[var(--s-accent)]" />
      <span>
        {{ rule?.proposed ? t('rules.form.approve') : t('rules.form.enabled') }}
        <span class="block text-xs text-ink-3">{{ t('rules.form.enabledHint') }}</span>
      </span>
    </label>

    <div class="flex flex-wrap gap-2 border-t border-line pt-4">
      <button type="submit" class="btn-primary" :disabled="!!issue || unchanged || busy">
        {{ rule ? t('rules.form.saveVersion', { v: rule.version + 1 }) : t('rules.form.create') }}
      </button>
      <button type="button" class="btn" @click="emit('cancel')">{{ t('flags.form.cancel') }}</button>
      <template v-if="rule">
        <button
          v-if="!rule.detections && !confirmingDelete"
          type="button"
          class="btn-danger ml-auto"
          :disabled="busy"
          @click="confirmingDelete = true"
        >
          {{ t('rules.form.delete') }}
        </button>
        <span v-else-if="rule.detections" class="ml-auto self-center text-xs text-ink-3">{{
          t('rules.form.noDelete', { n: int(rule.detections, lc) }, rule.detections)
        }}</span>
      </template>
    </div>
    <div
      v-if="rule && confirmingDelete"
      class="flex flex-col gap-2 rounded-md border border-bad/40 bg-bad/5 p-3 text-sm"
      role="alertdialog"
      :aria-label="t('rules.form.delete')"
    >
      <p>{{ t('rules.form.deleteConfirm') }}</p>
      <div class="flex gap-2">
        <button type="button" class="btn-danger" :disabled="busy" @click="remove">
          {{ t('rules.form.deleteYes') }}
        </button>
        <button type="button" class="btn" @click="confirmingDelete = false">
          {{ t('flags.form.keep') }}
        </button>
      </div>
    </div>

    <section v-if="rule && versions.data.value" :aria-label="t('rules.form.versions')">
      <h3 class="eyebrow mb-1.5">{{ t('rules.form.versions') }}</h3>
      <ol class="flex flex-col text-xs" data-testid="versions">
        <li
          v-for="(v, i) in versions.data.value"
          :key="v.version"
          class="flex gap-2 border-t border-line py-1.5"
        >
          <span class="num w-8 shrink-0 font-medium" :class="i ? 'text-ink-3' : ''">v{{ v.version }}</span>
          <span class="min-w-0 flex-1" :class="i ? 'text-ink-2' : ''">
            <span
              class="mr-1.5 rounded px-1.5 py-px text-[0.625rem] font-medium"
              :class="i ? 'bg-sunken text-ink-3' : v.enabled ? 'bg-ok/15 text-ok' : 'bg-sunken text-ink-2'"
              >{{
                i
                  ? t('rules.version.replaced', { time: formatUtc(versions.data.value[i - 1]!.created_at) })
                  : v.enabled
                    ? t('rules.version.inEffect')
                    : t('rules.version.currentOff')
              }}</span
            >
            {{ changes(i) }}
            <span class="block text-ink-3">{{ v.created_by }} · {{ formatUtc(v.created_at) }}</span>
          </span>
        </li>
      </ol>
      <p class="mt-1 text-[0.6875rem] text-ink-3">{{ t('rules.form.versionsNote') }}</p>
    </section>
  </form>
</template>
