<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink, useRoute } from 'vue-router'
import { api } from '@/api/client'
import { FLAG_REASONS, type FlagReason, type FlagRow, type SystemInfo } from '@/api/types'
import FlagForm from '@/components/flags/FlagForm.vue'
import SidePanel from '@/components/SidePanel.vue'
import { useLoader } from '@/composables/useLoader'
import type { Locale } from '@/i18n'
import { useDisplayStore } from '@/stores/display'
import { DEFAULT_SYSTEM } from '@/stores/live'
import { formatDuration, formatRange } from '@/utils/flags'
import { sitePath } from '@/utils/paths'
import { formatUtc } from '@/utils/time'

// Manual flags (FR-DQ-006): every flag with its components, range, reason and note, newest first. A flag is
// usually made where the problem is seen (a sensor chart or the minute map); this page lists, edits and removes
// them, and can start one from scratch.
const { t, locale } = useI18n()
const lc = computed(() => locale.value as Locale)
const route = useRoute()
const display = useDisplayStore()
const info = ref<SystemInfo | null>(null)
void display.system(DEFAULT_SYSTEM).then((s) => (info.value = s))

const showRemoved = ref(false)
const site = ref('')
const reason = ref<FlagReason | ''>('')
const loader = useLoader<FlagRow[]>(() => api.adminFlags(DEFAULT_SYSTEM, showRemoved.value))
watch(showRemoved, () => loader.load(), { immediate: true })

const rows = computed(() =>
  (loader.data.value ?? [])
    .filter((f) => !site.value || f.components.some((c) => c.site === site.value))
    .filter((f) => !reason.value || f.reason === reason.value),
)
const monthFmt = computed(
  () =>
    new Intl.DateTimeFormat(lc.value === 'id' ? 'id-ID' : 'en-GB', {
      month: 'long',
      year: 'numeric',
      timeZone: 'UTC',
    }),
)
const months = computed(() => {
  const out: { key: string; label: string; flags: FlagRow[] }[] = []
  for (const f of rows.value) {
    const key = f.start.slice(0, 7)
    let m = out.find((x) => x.key === key)
    if (!m) out.push((m = { key, label: monthFmt.value.format(new Date(f.start)), flags: [] }))
    m.flags.push(f)
  }
  return out
})

const compName = (s: string, type: string) => {
  const x = info.value?.sites.find((v) => v.slug === s)
  const c = x?.components.find((v) => v.type === type)
  return x && c ? `${x.name[lc.value]} · ${c.name[lc.value]}` : `${s} · ${type}`
}
const minutes = (f: FlagRow) => (Date.parse(f.end) - Date.parse(f.start)) / 60_000
/** The flagged range on the site's charts, with an hour either side. */
function chartLink(f: FlagRow) {
  const pad = 3_600_000
  const from = new Date(Date.parse(f.start) - pad).toISOString()
  const to = new Date(Math.min(Date.parse(f.end) + pad, Date.parse(f.start) + 31 * 86_400_000)).toISOString()
  return `${sitePath(DEFAULT_SYSTEM, f.components[0]!.site)}?w=custom:${from}~${to}`
}

// ---- panel ------------------------------------------------------------------------------------------
const panel = ref<{ kind: 'new' } | { kind: 'edit'; flag: FlagRow } | null>(null)
const title = computed(() =>
  panel.value?.kind === 'edit'
    ? t('flags.form.titleEdit', { id: panel.value.flag.id })
    : t('flags.form.titleNew'),
)
function done() {
  panel.value = null
  void loader.load({ silent: true })
}
// /admin/flags?id=4 opens that flag (links from the minute view)
watch(
  () => loader.data.value,
  (list) => {
    const id = Number(route.query.id)
    const f = id ? list?.find((x) => x.id === id && !x.removed_at) : null
    if (f && !panel.value) panel.value = { kind: 'edit', flag: f }
  },
)
</script>

<template>
  <div class="flex flex-col gap-4">
    <header class="flex flex-wrap items-start justify-between gap-3">
      <div class="max-w-2xl">
        <h2 class="text-base font-semibold">{{ t('flags.title') }}</h2>
        <p class="text-sm text-ink-2">{{ t('flags.subtitle') }}</p>
      </div>
      <button type="button" class="btn-primary" @click="panel = { kind: 'new' }">
        {{ t('flags.new') }}
      </button>
    </header>

    <div class="flex flex-wrap items-end gap-3">
      <label class="flex flex-col gap-1">
        <span class="label">{{ t('flags.filterSite') }}</span>
        <select v-model="site" class="input py-1.5">
          <option value="">{{ t('flags.allSites') }}</option>
          <option v-for="s in info?.sites ?? []" :key="s.slug" :value="s.slug">{{ s.name[lc] }}</option>
        </select>
      </label>
      <label class="flex flex-col gap-1">
        <span class="label">{{ t('flags.filterReason') }}</span>
        <select v-model="reason" class="input py-1.5">
          <option value="">{{ t('flags.allReasons') }}</option>
          <option v-for="r in FLAG_REASONS" :key="r" :value="r">{{ t(`flags.reason.${r}`) }}</option>
        </select>
      </label>
      <label class="flex items-center gap-2 pb-2 text-sm text-ink-2">
        <input v-model="showRemoved" type="checkbox" class="h-4 w-4 accent-[var(--s-accent)]" />
        {{ t('flags.showRemoved') }}
      </label>
      <span v-if="loader.data.value" class="num ml-auto pb-2 text-xs text-ink-3">{{
        t('flags.count', { n: rows.length }, rows.length)
      }}</span>
    </div>

    <p v-if="loader.error.value" class="text-sm text-warn" role="alert">{{ t('common.error') }}</p>
    <div v-else-if="!loader.data.value" class="h-60 animate-pulse rounded-lg bg-sunken" aria-busy="true" />
    <p
      v-else-if="!rows.length"
      class="rounded-lg border border-dashed border-line px-4 py-8 text-center text-sm text-ink-3"
    >
      {{ loader.data.value.length ? t('flags.emptyFiltered') : t('flags.empty') }}
    </p>
    <section v-for="m in months" v-else :key="m.key" :aria-label="m.label">
      <h3 class="eyebrow mb-1.5">{{ m.label }}</h3>
      <ul class="overflow-hidden rounded-lg border border-line bg-surface">
        <li
          v-for="f in m.flags"
          :key="f.id"
          class="flex gap-3 border-b border-line px-4 py-3 last:border-0"
          :class="f.removed_at ? 'bg-sunken/50' : ''"
          data-testid="flag-row"
        >
          <span
            class="w-1 shrink-0 rounded-full"
            :class="f.removed_at ? 'bg-line-strong' : 'flag-hatch border border-flag/60'"
            aria-hidden="true"
          />
          <div class="flex min-w-0 flex-1 flex-col gap-1">
            <p class="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-sm">
              <span class="font-semibold" :class="f.removed_at ? 'text-ink-3 line-through' : ''">{{
                t(`flags.reason.${f.reason}`)
              }}</span>
              <span class="num text-ink-2" :class="f.removed_at ? 'line-through' : ''"
                >{{ formatRange(f.start, f.end, lc, true) }} UTC</span
              >
              <span class="num text-xs text-ink-3">{{ formatDuration(minutes(f), t) }} · #{{ f.id }}</span>
              <span
                v-if="f.removed_at"
                class="rounded bg-sunken px-1.5 py-0.5 text-[0.6875rem] text-ink-2"
                data-testid="flag-removed"
                >{{ t('flags.removedBy', { name: f.removed_by, time: formatUtc(f.removed_at) }) }}</span
              >
            </p>
            <p class="text-xs text-ink">
              {{ f.components.map((c) => compName(c.site, c.type)).join('; ') }}
            </p>
            <p class="text-sm text-ink-2">{{ f.note }}</p>
            <p class="text-xs text-ink-3">
              {{ t('flags.by', { name: f.created_by, time: formatUtc(f.created_at) }) }}
              <template v-if="f.updated_at">
                · {{ t('flags.edited', { name: f.updated_by, time: formatUtc(f.updated_at) }) }}</template
              >
            </p>
          </div>
          <div class="flex shrink-0 flex-col items-end gap-1.5 sm:flex-row sm:items-start">
            <RouterLink :to="chartLink(f)" class="btn py-1 text-xs">{{ t('flags.openChart') }}</RouterLink>
            <button
              v-if="!f.removed_at"
              type="button"
              class="btn py-1 text-xs"
              @click="panel = { kind: 'edit', flag: f }"
            >
              {{ t('flags.edit') }}
            </button>
          </div>
        </li>
      </ul>
    </section>

    <SidePanel :open="panel !== null" :title="title" @close="panel = null">
      <FlagForm
        v-if="panel"
        :key="panel.kind === 'edit' ? panel.flag.id : 'new'"
        :system="DEFAULT_SYSTEM"
        :flag="panel.kind === 'edit' ? panel.flag : null"
        @done="done"
        @cancel="panel = null"
      />
    </SidePanel>
  </div>
</template>
