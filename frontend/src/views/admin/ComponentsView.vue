<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import { api, ApiProblem } from '@/api/client'
import type { ComponentRow, JobRow } from '@/api/types'
import SidePanel from '@/components/SidePanel.vue'
import { useLoader } from '@/composables/useLoader'
import type { Locale } from '@/i18n'
import { DEFAULT_SYSTEM } from '@/stores/live'
import { formatUtc } from '@/utils/time'

// Components and their in-service period (FR-REG-006): minutes outside it are not expected, so a sensor that is
// removed, not yet installed or being replaced does not count against availability. Metadata and calibration
// join this page in R2.5.
const { t, locale } = useI18n()
const lc = computed(() => locale.value as Locale)
const loader = useLoader<ComponentRow[]>(() => api.components(DEFAULT_SYSTEM))
void loader.load()

const sites = computed(() => {
  const by = new Map<string, { site: string; name: ComponentRow['site_name']; rows: ComponentRow[] }>()
  for (const c of loader.data.value ?? []) {
    const g = by.get(c.site) ?? { site: c.site, name: c.site_name, rows: [] }
    g.rows.push(c)
    by.set(c.site, g)
  }
  return [...by.values()]
})
const now = Date.now()
function status(c: ComponentRow): 'in' | 'notYet' | 'out' {
  if (c.in_service_from && Date.parse(c.in_service_from) > now) return 'notYet'
  if (c.in_service_to && Date.parse(c.in_service_to) <= now) return 'out'
  return 'in'
}
const TONE = { in: 'text-ink-2', notYet: 'text-warn', out: 'text-ink-3' }

// -------------------------------------------------------------- edit
const editing = ref<ComponentRow | null>(null)
const from = ref('')
const to = ref('')
const busy = ref(false)
const error = ref<string | null>(null)
const job = ref<JobRow | null>(null)
// <input type="datetime-local"> holds a UTC time here: the labels say so, and nothing is converted.
const toInput = (iso: string | null) => (iso ? iso.slice(0, 16) : '')
const fromInput = (v: string) => (v ? `${v}:00Z` : null)
function edit(c: ComponentRow) {
  editing.value = c
  from.value = toInput(c.in_service_from)
  to.value = toInput(c.in_service_to)
  error.value = null
  job.value = null
}
const problem = computed(() => (from.value && to.value && from.value >= to.value ? 'order' : null))
const unchanged = computed(
  () =>
    !!editing.value &&
    fromInput(from.value) ===
      (editing.value.in_service_from ? toInput(editing.value.in_service_from) + ':00Z' : null) &&
    fromInput(to.value) ===
      (editing.value.in_service_to ? toInput(editing.value.in_service_to) + ':00Z' : null),
)
async function save() {
  if (!editing.value || problem.value || busy.value) return
  busy.value = true
  error.value = null
  try {
    const r = await api.saveInService(editing.value.id, fromInput(from.value), fromInput(to.value))
    editing.value = r.component
    job.value = r.job
    await loader.load({ silent: true })
  } catch (e) {
    error.value = e instanceof ApiProblem ? e.code : 'network_error'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="flex flex-col gap-4">
    <header>
      <h2 class="text-base font-semibold">{{ t('components.title') }}</h2>
      <p class="text-sm text-ink-2">{{ t('components.subtitle') }}</p>
    </header>

    <p v-if="loader.error.value" class="text-sm text-warn" role="alert">{{ t('common.error') }}</p>
    <div v-else-if="!loader.data.value" class="h-60 animate-pulse rounded-lg bg-sunken" aria-busy="true" />
    <section
      v-for="g in sites"
      v-else
      :key="g.site"
      class="overflow-hidden rounded-lg border border-line bg-surface"
      :aria-label="g.name[lc]"
    >
      <h3 class="border-b border-line bg-sunken/60 px-4 py-2 text-sm font-semibold">{{ g.name[lc] }}</h3>
      <ul>
        <li
          v-for="c in g.rows"
          :key="c.id"
          class="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-line px-4 py-2.5 last:border-0"
        >
          <span class="min-w-0 flex-1 text-sm">
            {{ c.name[lc] }} <span class="text-xs text-ink-3">· {{ c.type }}</span>
          </span>
          <span class="text-xs" :class="TONE[status(c)]">
            <template v-if="status(c) === 'in'">{{
              c.in_service_from || c.in_service_to
                ? t('components.inSince', {
                    from: c.in_service_from ? formatUtc(c.in_service_from) : '—',
                    to: c.in_service_to ? formatUtc(c.in_service_to) : t('components.open'),
                  })
                : t('components.always')
            }}</template>
            <template v-else-if="status(c) === 'notYet'">{{
              t('components.notYet', { time: formatUtc(c.in_service_from) })
            }}</template>
            <template v-else>{{ t('components.out', { time: formatUtc(c.in_service_to) }) }}</template>
          </span>
          <button v-if="!c.is_dcp" type="button" class="btn py-1 text-xs" @click="edit(c)">
            {{ t('components.edit') }}
          </button>
          <span v-else class="text-xs text-ink-3" :title="t('components.dcpHint')">{{
            t('components.dcp')
          }}</span>
        </li>
      </ul>
    </section>
    <p class="text-xs text-ink-3">{{ t('components.later') }}</p>

    <SidePanel
      :open="editing !== null"
      :title="editing ? editing.name[lc] : ''"
      :subtitle="editing ? `${editing.site_name[lc]} · ${editing.type}` : undefined"
      @close="editing = null"
    >
      <form v-if="editing" class="flex flex-col gap-4 py-1" novalidate @submit.prevent="save">
        <p class="text-sm text-ink-2">{{ t('components.explain') }}</p>
        <p v-if="error" class="rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-sm" role="alert">
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
        <p v-if="problem" class="text-xs text-bad">{{ t('components.order') }}</p>
        <p class="rounded-md border border-line bg-sunken/60 p-3 text-xs text-ink-2">
          {{ t('components.effect') }}
        </p>
        <p v-if="job" class="text-xs text-ink-2" role="status">
          {{ t('mandatory.saved') }}
          <RouterLink to="/admin/jobs" class="text-accent hover:underline">{{
            t('mandatory.jobLink', { id: job.id })
          }}</RouterLink>
        </p>
        <div class="flex flex-wrap gap-2 border-t border-line pt-4">
          <button type="submit" class="btn-primary" :disabled="!!problem || unchanged || busy">
            {{ t('components.save') }}
          </button>
          <button type="button" class="btn" @click="editing = null">{{ t('common.close') }}</button>
        </div>
      </form>
    </SidePanel>
  </div>
</template>
