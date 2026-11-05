<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink, useRoute } from 'vue-router'
import { api, ApiProblem } from '@/api/client'
import {
  RULE_TYPES,
  type Detection,
  type DetectionFilter,
  type DetectionPage,
  type DetectionStatus,
  type JobRow,
  type SystemInfo,
} from '@/api/types'
import DetectionPanel from '@/components/detections/DetectionPanel.vue'
import SidePanel from '@/components/SidePanel.vue'
import { useLoader } from '@/composables/useLoader'
import type { Locale } from '@/i18n'
import { useDisplayStore } from '@/stores/display'
import { DEFAULT_SYSTEM } from '@/stores/live'
import { formatDuration, formatRange } from '@/utils/flags'
import { int } from '@/utils/format'
import { evidenceText, ruleText } from '@/utils/rules'
import { formatUtc } from '@/utils/time'

// Review queue (FR-DQ-004, J3): suspect detections wait here with no effect on any figure. Confirm or reject one
// at a time from its chart, or several at once; confirmed and rejected ones stay listed and can be reversed.
const { t, locale } = useI18n()
const lc = computed(() => locale.value as Locale)
const route = useRoute()
const display = useDisplayStore()
const info = ref<SystemInfo | null>(null)
void display.system(DEFAULT_SYSTEM).then((s) => (info.value = s))

const STATUSES: DetectionStatus[] = ['suspect', 'confirmed', 'rejected']
const initial = STATUSES.includes(route.query.status as DetectionStatus)
  ? (route.query.status as DetectionStatus)
  : 'suspect'
const filter = reactive<DetectionFilter>({ status: initial, site: '', component: '', type: '' })
const loader = useLoader<DetectionPage>(() => api.reviewQueue(DEFAULT_SYSTEM, { ...filter }))
const selected = ref<number[]>([])
watch(
  () => JSON.stringify(filter),
  () => {
    selected.value = []
    void loader.load()
  },
  { immediate: true },
)
const rows = computed(() => loader.data.value?.detections ?? [])
const types = computed(() => [...new Set(info.value?.sites.flatMap((s) => s.components.map((c) => c.type)))])

const unit = (d: Detection) => info.value?.fields[d.field]?.unit ?? null
const siteName = (slug: string) => info.value?.sites.find((s) => s.slug === slug)?.name[lc.value] ?? slug
const compName = (d: Detection) =>
  info.value?.sites.find((s) => s.slug === d.site)?.components.find((c) => c.type === d.component)?.name[
    lc.value
  ] ?? d.component

// ---- selection and decisions -------------------------------------------------------------------------
const allSelected = computed(() => rows.value.length > 0 && selected.value.length === rows.value.length)
function toggle(id: number) {
  selected.value = selected.value.includes(id)
    ? selected.value.filter((x) => x !== id)
    : [...selected.value, id]
}
function toggleAll() {
  selected.value = allSelected.value ? [] : rows.value.map((d) => d.id)
}
const bulkNote = ref('')
const busy = ref(false)
const error = ref<string | null>(null)
const done = ref<{ n: number; decision: 'confirm' | 'reject'; job: JobRow | null } | null>(null)
/** `then` runs once the decision is stored, before the list reloads (the open panel moves on without closing). */
async function decide(ids: number[], decision: 'confirm' | 'reject', note: string, then?: () => void) {
  busy.value = true
  error.value = null
  try {
    const r = await api.decide({ ids, decision, note: note.trim() || undefined })
    then?.()
    done.value = { n: r.decided.length, decision, job: r.job }
    selected.value = []
    bulkNote.value = ''
    await loader.load({ silent: true })
    return true
  } catch (e) {
    error.value = e instanceof ApiProblem ? e.code : 'network_error'
    return false
  } finally {
    busy.value = false
  }
}

// ---- detail panel -------------------------------------------------------------------------------------
const openId = ref<number | null>(Number(route.query.id) || null)
const open = computed(() => rows.value.find((d) => d.id === openId.value) ?? null)
const position = computed(() => rows.value.findIndex((d) => d.id === openId.value) + 1)
function step(by: number) {
  const next = rows.value[position.value - 1 + by]
  if (next) openId.value = next.id
}
async function decideOpen(decision: 'confirm' | 'reject', note: string) {
  const d = open.value
  if (!d) return
  // The decided detection leaves this list: carry on with its neighbour, or close when it was the last.
  const index = position.value - 1
  const neighbour = rows.value[index + 1]?.id ?? rows.value[index - 1]?.id ?? null
  await decide([d.id], decision, note, () => (openId.value = neighbour))
}
</script>

<template>
  <div class="flex flex-col gap-4">
    <header class="max-w-2xl">
      <h2 class="text-base font-semibold">{{ t('review.title') }}</h2>
      <p class="text-sm text-ink-2">{{ t('review.subtitle') }}</p>
    </header>

    <div class="flex flex-wrap items-end gap-3">
      <div class="seg" role="group" :aria-label="t('review.statusLabel')">
        <button
          v-for="s in STATUSES"
          :key="s"
          type="button"
          :aria-pressed="filter.status === s"
          @click="filter.status = s"
        >
          {{ t(`review.tab.${s}`) }}
          <span class="num text-ink-3">{{ int(loader.data.value?.counts[s] ?? 0, lc) }}</span>
        </button>
      </div>
      <label class="flex flex-col gap-1">
        <span class="label">{{ t('flags.filterSite') }}</span>
        <select v-model="filter.site" class="input py-1.5">
          <option value="">{{ t('flags.allSites') }}</option>
          <option v-for="s in info?.sites ?? []" :key="s.slug" :value="s.slug">{{ s.name[lc] }}</option>
        </select>
      </label>
      <label class="flex flex-col gap-1">
        <span class="label">{{ t('review.component') }}</span>
        <select v-model="filter.component" class="input py-1.5">
          <option value="">{{ t('review.allComponents') }}</option>
          <option v-for="c in types.filter((x) => x !== 'DCP')" :key="c" :value="c">{{ c }}</option>
        </select>
      </label>
      <label class="flex flex-col gap-1">
        <span class="label">{{ t('review.rule') }}</span>
        <select v-model="filter.type" class="input py-1.5">
          <option value="">{{ t('review.allRules') }}</option>
          <option v-for="r in RULE_TYPES" :key="r" :value="r">{{ t(`rules.type.${r}`) }}</option>
        </select>
      </label>
    </div>

    <p v-if="error" class="rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-sm" role="alert">
      {{ t('common.error') }}
    </p>
    <p
      v-if="done"
      class="rounded-md border border-ok/40 bg-ok/10 px-3 py-2 text-sm"
      role="status"
      data-testid="decided"
    >
      {{ t(`review.done.${done.decision}`, { n: done.n }, done.n) }}
      <template v-if="done.job">
        {{ t('review.recalc') }}
        <RouterLink to="/admin/jobs" class="text-accent hover:underline">{{
          t('mandatory.jobLink', { id: done.job.id })
        }}</RouterLink>
      </template>
    </p>

    <div
      v-if="selected.length"
      class="sticky top-14 z-10 flex flex-wrap items-center gap-2 rounded-lg border border-accent/40 bg-accent-soft px-3 py-2"
      data-testid="bulk-bar"
    >
      <span class="text-sm font-medium">{{
        t('review.selected', { n: selected.length }, selected.length)
      }}</span>
      <input
        v-model="bulkNote"
        type="text"
        maxlength="500"
        class="input min-w-40 flex-1 py-1 text-xs"
        :placeholder="t('detections.notePlaceholder')"
        :aria-label="t('detections.note')"
      />
      <button
        v-if="filter.status !== 'confirmed'"
        type="button"
        class="btn-primary py-1 text-xs"
        :disabled="busy"
        @click="decide(selected, 'confirm', bulkNote)"
      >
        {{ t('review.confirmSelected') }}
      </button>
      <button
        v-if="filter.status !== 'rejected'"
        type="button"
        class="btn py-1 text-xs"
        :disabled="busy"
        @click="decide(selected, 'reject', bulkNote)"
      >
        {{ t('review.rejectSelected') }}
      </button>
    </div>

    <p v-if="loader.error.value" class="text-sm text-warn" role="alert">{{ t('common.error') }}</p>
    <div
      v-else-if="!loader.data.value || !info"
      class="h-60 animate-pulse rounded-lg bg-sunken"
      aria-busy="true"
    />
    <p
      v-else-if="!rows.length"
      class="rounded-lg border border-dashed border-line px-4 py-8 text-center text-sm text-ink-3"
    >
      {{ t(`review.empty.${filter.status}`) }}
    </p>
    <section
      v-else
      class="overflow-hidden rounded-lg border border-line bg-surface"
      :aria-label="t('review.title')"
    >
      <label class="flex items-center gap-3 border-b border-line bg-sunken/60 px-4 py-2 text-xs text-ink-2">
        <input
          type="checkbox"
          class="h-4 w-4 accent-[var(--s-accent)]"
          :checked="allSelected"
          @change="toggleAll"
        />
        {{ t('review.selectAll', { n: rows.length }) }}
      </label>
      <ul>
        <li
          v-for="d in rows"
          :key="d.id"
          class="flex items-start gap-3 border-b border-line px-4 py-3 last:border-0"
          :class="selected.includes(d.id) ? 'bg-accent-soft/50' : ''"
          data-testid="detection-row"
        >
          <input
            type="checkbox"
            class="mt-1 h-4 w-4 shrink-0 accent-[var(--s-accent)]"
            :checked="selected.includes(d.id)"
            :aria-label="`#${d.id} ${d.field}`"
            @change="toggle(d.id)"
          />
          <div class="flex min-w-0 flex-1 flex-col gap-0.5">
            <p class="flex flex-wrap items-baseline gap-x-2 text-sm">
              <span class="font-semibold">{{ t(`rules.type.${d.type}`) }} · {{ d.field }}</span>
              <span class="text-ink-2">{{ siteName(d.site) }} · {{ compName(d) }}</span>
            </p>
            <p class="num text-xs text-ink-2">
              {{ formatRange(d.start, d.end, lc, true) }} UTC · {{ formatDuration(d.minutes, t) }}
            </p>
            <p class="text-xs">
              <span class="font-medium">{{ evidenceText(d.type, d.evidence, unit(d), lc, t) }}</span>
              <span class="text-ink-3">
                · {{ ruleText(d.type, d.params, unit(d), lc, t) }} · v{{ d.rule_version }}</span
              >
            </p>
            <p class="text-xs" :class="d.mandatory ? 'text-detect' : 'text-ink-3'">
              {{ d.mandatory ? t('review.affects') : t('review.fieldOnly') }}
            </p>
            <p v-if="d.decided_by" class="text-xs text-ink-3">
              {{
                t(`detections.decidedBy.${d.status}`, { name: d.decided_by, time: formatUtc(d.decided_at) })
              }}
              <template v-if="d.note"> · “{{ d.note }}”</template>
            </p>
          </div>
          <button type="button" class="btn shrink-0 py-1 text-xs" @click="openId = d.id">
            {{ d.status === 'suspect' ? t('detections.review') : t('detections.open') }}
          </button>
        </li>
      </ul>
    </section>
    <p v-if="loader.data.value && loader.data.value.total > rows.length" class="text-xs text-ink-3">
      {{ t('review.more', { shown: rows.length, total: loader.data.value.total }) }}
    </p>

    <SidePanel
      :open="open !== null"
      :title="open ? `${t(`rules.type.${open.type}`)} · ${open.field}` : ''"
      :subtitle="open ? `${siteName(open.site)} · ${compName(open)}` : undefined"
      @close="openId = null"
    >
      <DetectionPanel
        v-if="open && info"
        :detection="open"
        :info="info"
        :position="position"
        :total="rows.length"
        :busy="busy"
        @prev="step(-1)"
        @next="step(1)"
        @decide="decideOpen"
      />
    </SidePanel>
  </div>
</template>
