<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { api, ApiProblem } from '@/api/client'
import { JOB_SOURCES, type JobDetail, type JobRow, type JobSource, type NewJob } from '@/api/types'
import SidePanel from '@/components/SidePanel.vue'
import { useLoader } from '@/composables/useLoader'
import { usePolling } from '@/composables/usePolling'
import type { Locale } from '@/i18n'
import { useDisplayStore } from '@/stores/display'
import { DEFAULT_SYSTEM } from '@/stores/live'
import { formatUtc } from '@/utils/time'

// Jobs (FR-ADM-002): reprocess from the CDP files or recompute figures, with progress, log and cancel.
const { t, locale } = useI18n()
const lc = computed(() => locale.value as Locale)
const display = useDisplayStore()
const loader = useLoader<JobRow[]>(() => api.jobs())
void loader.load()
const active = computed(() =>
  (loader.data.value ?? []).filter((j) => j.status === 'queued' || j.status === 'running'),
)
usePolling(() => (active.value.length || detail.value ? refresh() : Promise.resolve()), 4_000)

const SECONDS_PER_DAY = { reprocess: 4, recompute: 1 } // measured on staging, 2026-11-05

const day = (iso: string | undefined) =>
  iso
    ? new Intl.DateTimeFormat(lc.value === 'id' ? 'id-ID' : 'en-GB', {
        day: 'numeric',
        month: 'short',
        year: 'numeric',
        timeZone: 'UTC',
      }).format(new Date(`${iso.slice(0, 10)}T00:00:00Z`))
    : '—'
const days = (from?: string, to?: string) =>
  from && to ? Math.round((Date.parse(to) - Date.parse(from)) / 86_400_000) + 1 : 0
const range = (j: JobRow) =>
  `${day(j.params.from)} – ${day(j.params.to)} · ${t('jobs.days', days(j.params.from, j.params.to))}`
const sourcesNote = (j: JobRow) =>
  j.params.sources?.length ? ` · ${j.params.sources.map((x) => t(`jobs.source.${x}`)).join(', ')}` : ''
function took(j: JobRow): string {
  const end = j.finished_at ? Date.parse(j.finished_at) : j.started_at ? Date.now() : null
  if (!j.started_at || end === null) return '—'
  const s = Math.max(0, Math.round((end - Date.parse(j.started_at)) / 1000))
  return s < 90 ? t('jobs.seconds', { n: s }) : t('jobs.minutes', { n: Math.round(s / 60) })
}
const TONE: Record<string, string> = {
  queued: 'bg-sunken text-ink-2',
  running: 'bg-accent-soft text-accent',
  done: 'bg-sunken text-ink-2',
  failed: 'bg-bad/15 text-bad',
  cancelled: 'bg-sunken text-ink-3',
  interrupted: 'bg-warn/15 text-warn',
}

// -------------------------------------------------------------- detail
const detail = ref<JobDetail | null>(null)
const confirmCancel = ref(false)
async function open(j: JobRow) {
  confirmCancel.value = false
  detail.value = { ...j, log: '' }
  detail.value = await api.job(j.id)
}
async function refresh() {
  await loader.load({ silent: true })
  if (detail.value) detail.value = await api.job(detail.value.id)
}
async function cancel() {
  if (!detail.value) return
  await api.cancelJob(detail.value.id)
  confirmCancel.value = false
  await refresh()
}

// -------------------------------------------------------------- new job
const today = new Date().toISOString().slice(0, 10)
const form = reactive<NewJob & { sources: JobSource[] }>({
  type: 'reprocess',
  system: DEFAULT_SYSTEM,
  from: today,
  to: today,
  sources: [...JOB_SOURCES],
})
const creating = ref(false)
const busy = ref(false)
const error = ref<string | null>(null)
const coverage = computed(() => display.systems[DEFAULT_SYSTEM]?.coverage_start.slice(0, 10) ?? '2025-12-24')
void display.system(DEFAULT_SYSTEM)
function preset(kind: 'yesterday' | 'week' | 'lastMonth' | 'all') {
  const d = new Date(`${today}T00:00:00Z`)
  const iso = (x: Date) => x.toISOString().slice(0, 10)
  const shift = (n: number) => new Date(d.getTime() + n * 86_400_000)
  if (kind === 'yesterday') form.from = form.to = iso(shift(-1))
  if (kind === 'week') Object.assign(form, { from: iso(shift(-6)), to: today })
  if (kind === 'lastMonth') {
    const first = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth() - 1, 1))
    const last = new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), 0))
    Object.assign(form, { from: iso(first), to: iso(last) })
  }
  if (kind === 'all') Object.assign(form, { from: coverage.value, to: today })
}
const formDays = computed(() => days(form.from, form.to))
const formProblem = computed(() =>
  form.type === 'reprocess' && !form.sources.length
    ? 'sources'
    : !form.from || !form.to
      ? 'missing'
      : form.from > form.to
        ? 'order'
        : form.to > today
          ? 'future'
          : form.from < coverage.value
            ? 'coverage'
            : null,
)
const estimate = computed(() => Math.max(1, Math.round((formDays.value * SECONDS_PER_DAY[form.type]) / 60)))
async function start() {
  if (formProblem.value || busy.value) return
  busy.value = true
  error.value = null
  try {
    const { sources, ...rest } = form
    // Reading every source again is the default and needs no list.
    const job = await api.startJob(
      rest.type === 'reprocess' && sources.length < JOB_SOURCES.length
        ? { ...rest, sources: [...sources] }
        : rest,
    )
    creating.value = false
    await loader.load({ silent: true })
    await open(job)
  } catch (e) {
    error.value = e instanceof ApiProblem ? e.code : 'network_error'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="flex flex-col gap-4">
    <header class="flex flex-wrap items-end justify-between gap-3">
      <div>
        <h2 class="text-base font-semibold">{{ t('admin.section.jobs') }}</h2>
        <p class="text-sm text-ink-2">{{ t('jobs.subtitle') }}</p>
      </div>
      <button type="button" class="btn-primary" @click="creating = true">{{ t('jobs.new') }}</button>
    </header>

    <section
      v-for="j in active"
      :key="`a${j.id}`"
      class="flex flex-col gap-2 rounded-lg border border-accent/40 bg-accent-soft p-4"
    >
      <div class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <p class="text-sm font-medium">#{{ j.id }} · {{ t(`jobs.type.${j.type}`) }}</p>
        <span class="text-xs text-ink-2">{{ range(j) }}{{ sourcesNote(j) }}</span>
        <span class="ml-auto text-xs text-ink-2"
          >{{ t('jobs.by', { who: j.created_by }) }} · {{ took(j) }}</span
        >
      </div>
      <div
        class="h-2 overflow-hidden rounded-full bg-surface"
        role="progressbar"
        :aria-valuenow="Math.round(j.progress * 100)"
        aria-valuemin="0"
        aria-valuemax="100"
      >
        <div
          class="h-full rounded-full bg-accent transition-[width]"
          :style="{ width: `${Math.round(j.progress * 100)}%` }"
        />
      </div>
      <div class="flex items-center gap-3 text-xs text-ink-2">
        <span class="num">{{ Math.round(j.progress * 100) }} %</span>
        <span>{{ t(`jobs.status.${j.status}`) }}</span>
        <button type="button" class="btn ml-auto py-1 text-xs" @click="open(j)">
          {{ t('jobs.details') }}
        </button>
      </div>
    </section>

    <p v-if="loader.error.value" class="text-sm text-warn" role="alert">{{ t('common.error') }}</p>
    <div v-else-if="!loader.data.value" class="h-40 animate-pulse rounded-lg bg-sunken" aria-busy="true" />
    <ol v-else class="overflow-hidden rounded-lg border border-line bg-surface">
      <li v-for="j in loader.data.value" :key="j.id" class="border-b border-line last:border-0">
        <button
          type="button"
          class="grid w-full grid-cols-[3rem_minmax(0,1fr)_auto] items-center gap-x-3 gap-y-0.5 px-4 py-2.5 text-left hover:bg-sunken sm:grid-cols-[3rem_minmax(0,1fr)_7rem_8rem_6rem]"
          @click="open(j)"
        >
          <span class="num text-xs text-ink-3">#{{ j.id }}</span>
          <span class="min-w-0">
            <span class="block truncate text-sm">{{ t(`jobs.type.${j.type}`) }}</span>
            <span class="block truncate text-xs text-ink-3">{{ range(j) }}{{ sourcesNote(j) }}</span>
          </span>
          <span class="justify-self-end sm:justify-self-start"
            ><span class="rounded px-1.5 py-0.5 text-xs" :class="TONE[j.status]">{{
              t(`jobs.status.${j.status}`)
            }}</span></span
          >
          <span class="hidden truncate text-xs text-ink-2 sm:block">{{ j.created_by }}</span>
          <span class="num hidden text-right text-xs text-ink-3 sm:block">{{ took(j) }}</span>
        </button>
      </li>
    </ol>

    <SidePanel
      :open="detail !== null"
      :title="detail ? `#${detail.id} · ${t(`jobs.type.${detail.type}`)}` : ''"
      :subtitle="detail ? range(detail) : undefined"
      @close="detail = null"
    >
      <div v-if="detail" class="flex flex-col gap-4 py-1">
        <dl class="grid grid-cols-[8rem_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-sm">
          <dt class="text-ink-3">{{ t('jobs.statusLabel') }}</dt>
          <dd>
            <span class="rounded px-1.5 py-0.5 text-xs" :class="TONE[detail.status]">{{
              t(`jobs.status.${detail.status}`)
            }}</span>
            <span class="num ml-1 text-xs text-ink-3">{{ Math.round(detail.progress * 100) }} %</span>
          </dd>
          <dt class="text-ink-3">{{ t('jobs.startedBy') }}</dt>
          <dd>{{ detail.created_by }}</dd>
          <dt class="text-ink-3">{{ t('jobs.created') }}</dt>
          <dd class="num text-xs">{{ formatUtc(detail.created_at) }}</dd>
          <dt class="text-ink-3">{{ t('jobs.duration') }}</dt>
          <dd class="num text-xs">{{ took(detail) }}</dd>
          <template v-if="detail.message">
            <dt class="text-ink-3">{{ t('jobs.result') }}</dt>
            <dd class="text-xs" :class="detail.status === 'failed' ? 'text-bad' : ''">
              {{ detail.message }}
            </dd>
          </template>
        </dl>
        <div
          v-if="detail.status === 'queued' || detail.status === 'running'"
          class="flex flex-wrap items-center gap-2"
        >
          <template v-if="confirmCancel">
            <span class="text-sm">{{ t('jobs.cancelConfirm') }}</span>
            <button type="button" class="btn-danger" @click="cancel">{{ t('jobs.cancelYes') }}</button>
            <button type="button" class="btn" @click="confirmCancel = false">{{ t('users.cancel') }}</button>
          </template>
          <button v-else type="button" class="btn" @click="confirmCancel = true">
            {{ t('jobs.cancel') }}
          </button>
        </div>
        <div>
          <p class="label mb-1.5">{{ t('jobs.log') }}</p>
          <pre
            class="num max-h-80 overflow-auto rounded-md border border-line bg-sunken p-3 text-[0.6875rem] leading-relaxed text-ink-2"
            >{{ detail.log || t('jobs.noLog') }}</pre>
        </div>
      </div>
    </SidePanel>

    <SidePanel :open="creating" :title="t('jobs.new')" @close="creating = false">
      <form class="flex flex-col gap-4 py-1" novalidate @submit.prevent="start">
        <p v-if="error" class="rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-sm" role="alert">
          {{ error === 'job_running' ? t('jobs.error.running') : t('common.error') }}
        </p>
        <fieldset class="flex flex-col gap-2">
          <legend class="label mb-1.5">{{ t('jobs.kind') }}</legend>
          <label
            v-for="k in ['reprocess', 'recompute'] as const"
            :key="k"
            class="flex cursor-pointer gap-3 rounded-md border px-3 py-2.5"
            :class="form.type === k ? 'border-accent bg-accent-soft' : 'border-line'"
          >
            <input
              v-model="form.type"
              type="radio"
              name="type"
              :value="k"
              class="mt-0.5 accent-[var(--s-accent)]"
            />
            <span>
              <span class="block text-sm font-medium">{{ t(`jobs.type.${k}`) }}</span>
              <span class="block text-xs text-ink-2">{{ t(`jobs.hint.${k}`) }}</span>
            </span>
          </label>
        </fieldset>
        <fieldset v-if="form.type === 'reprocess'" class="flex flex-col gap-1.5">
          <legend class="label mb-1">{{ t('jobs.sources') }}</legend>
          <label v-for="s in JOB_SOURCES" :key="s" class="flex items-center gap-2 text-sm">
            <input v-model="form.sources" type="checkbox" :value="s" class="accent-[var(--s-accent)]" />
            {{ t(`jobs.source.${s}`) }}
          </label>
          <span class="text-xs text-ink-3">{{ t('jobs.sourcesHint') }}</span>
        </fieldset>
        <div class="flex flex-col gap-2">
          <span class="label">{{ t('jobs.range') }}</span>
          <div class="flex flex-wrap gap-1.5">
            <button
              v-for="p in ['yesterday', 'week', 'lastMonth', 'all'] as const"
              :key="p"
              type="button"
              class="btn py-1 text-xs"
              @click="preset(p)"
            >
              {{ t(`jobs.preset.${p}`) }}
            </button>
          </div>
          <div class="grid grid-cols-2 gap-3">
            <label class="flex flex-col gap-1">
              <span class="text-xs text-ink-3">{{ t('jobs.from') }}</span>
              <input v-model="form.from" type="date" class="input py-1.5" :min="coverage" :max="today" />
            </label>
            <label class="flex flex-col gap-1">
              <span class="text-xs text-ink-3">{{ t('jobs.to') }}</span>
              <input v-model="form.to" type="date" class="input py-1.5" :min="coverage" :max="today" />
            </label>
          </div>
          <p v-if="formProblem" class="text-xs text-bad">
            {{ t(`jobs.problem.${formProblem}`, { date: day(coverage) }) }}
          </p>
          <p v-else class="text-xs text-ink-2">
            {{ t('jobs.days', formDays) }} · {{ t('jobs.estimate', { n: estimate }) }}
          </p>
        </div>
        <div class="flex flex-wrap gap-2 border-t border-line pt-4">
          <button type="submit" class="btn-primary" :disabled="!!formProblem || busy">
            {{ t('jobs.start') }}
          </button>
          <button type="button" class="btn" @click="creating = false">{{ t('users.cancel') }}</button>
        </div>
      </form>
    </SidePanel>
  </div>
</template>
