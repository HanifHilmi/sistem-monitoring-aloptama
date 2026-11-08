<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import { api } from '@/api/client'
import type { Definitions, SystemInfo } from '@/api/types'
import type { Locale } from '@/i18n'
import { useDisplayStore } from '@/stores/display'
import { DEFAULT_SYSTEM } from '@/stores/live'
import { formatUtc } from '@/utils/time'

// FR-KPI-010: how every figure is worked out (PRD §7.3.1), in plain words, with the mandatory fields in force now
// and the definitions version. Public. Values that are settings (grace, colours, mandatory fields) are read live.
const props = withDefaults(defineProps<{ code?: string }>(), { code: DEFAULT_SYSTEM })
const { t, te, tm, rt, locale } = useI18n()
const lc = computed(() => locale.value as Locale)
const display = useDisplayStore()
const info = ref<SystemInfo | null>(null)
const defs = ref<Definitions | null>(null)
const grace = ref(3)
onMounted(async () => {
  const [i, d, s] = await Promise.allSettled([
    display.system(props.code),
    api.definitions(),
    api.displaySettings(),
  ])
  if (i.status === 'fulfilled') info.value = i.value
  if (d.status === 'fulfilled') defs.value = d.value
  if (s.status === 'fulfilled') grace.value = s.value.grace_minutes
  void display.loadSettings()
})

const KPIS = ['sla', 'uptime', 'reach', 'component', 'dcp', 'site', 'ola', 'pooled'] as const
const list = (key: string, params: Record<string, unknown> = {}) =>
  (tm(key) as unknown[]).map((m) => rt(m as Parameters<typeof rt>[0], params))

/** One row per sensor type: its mandatory fields and the other fields it reports, as configured now. */
const sensors = computed(() => {
  const out = new Map<string, { name: string; mandatory: Set<string>; other: Set<string>; dcp: boolean }>()
  for (const s of info.value?.sites ?? [])
    for (const c of s.components) {
      const row = out.get(c.type) ?? {
        name: c.name[lc.value],
        mandatory: new Set(),
        other: new Set(),
        dcp: c.is_dcp,
      }
      for (const f of c.fields) (c.mandatory.includes(f) ? row.mandatory : row.other).add(f)
      out.set(c.type, row)
    }
  return [...out.entries()].map(([type, r]) => ({ type, ...r }))
})
const field = (code: string) => info.value?.fields[code]?.name[lc.value] ?? code
</script>

<template>
  <div class="mx-auto flex w-full max-w-4xl flex-col gap-6 px-3 py-5 sm:px-5">
    <header>
      <h1 class="text-lg font-semibold">{{ t('definitions.title') }}</h1>
      <p class="text-sm text-ink-2">{{ t('definitions.subtitle') }}</p>
      <p
        v-if="defs"
        class="num mt-2 inline-block rounded-md border border-line bg-surface px-2.5 py-1 text-xs"
        data-testid="definitions-version"
      >
        {{ t('definitions.version', { v: defs.version, date: defs.effective_from, source: defs.source }) }}
      </p>
    </header>

    <section :aria-labelledby="'d-count'">
      <h2 id="d-count" class="mb-2 text-base font-semibold">{{ t('definitions.counting.title') }}</h2>
      <ul class="flex list-disc flex-col gap-1.5 pl-5 text-sm text-ink-2">
        <li
          v-for="(item, i) in list('definitions.counting.items', {
            grace,
            coverage: info ? formatUtc(info.coverage_start) : '…',
          })"
          :key="i"
        >
          {{ item }}
        </li>
      </ul>
    </section>

    <section :aria-labelledby="'d-kpi'">
      <h2 id="d-kpi" class="mb-2 text-base font-semibold">{{ t('definitions.kpi.title') }}</h2>
      <div class="grid gap-3 md:grid-cols-2">
        <article
          v-for="k in KPIS"
          :key="k"
          class="flex flex-col gap-2 rounded-lg border border-line bg-surface px-4 py-3"
          :data-testid="`kpi-${k}`"
        >
          <h3 class="text-sm font-semibold">{{ t(`definitions.kpi.${k}.name`) }}</h3>
          <p class="text-sm text-ink-2">{{ t(`definitions.kpi.${k}.what`) }}</p>
          <p class="num rounded-md bg-sunken px-2.5 py-1.5 text-xs text-ink">
            {{ t(`definitions.kpi.${k}.formula`) }}
          </p>
          <p v-if="te(`definitions.kpi.${k}.note`)" class="text-xs text-ink-3">
            {{ t(`definitions.kpi.${k}.note`) }}
          </p>
        </article>
      </div>
    </section>

    <section :aria-labelledby="'d-mand'">
      <h2 id="d-mand" class="mb-1 text-base font-semibold">{{ t('definitions.mandatory.title') }}</h2>
      <p class="mb-2 text-sm text-ink-2">{{ t('definitions.mandatory.intro') }}</p>
      <div class="overflow-x-auto rounded-lg border border-line bg-surface">
        <table class="w-full min-w-[520px] text-sm" data-testid="definitions-mandatory">
          <thead class="border-b border-line bg-sunken/60 text-left text-xs text-ink-3">
            <tr>
              <th class="px-3 py-2 font-normal">{{ t('definitions.mandatory.sensor') }}</th>
              <th class="px-3 py-2 font-normal">{{ t('definitions.mandatory.required') }}</th>
              <th class="px-3 py-2 font-normal">{{ t('definitions.mandatory.other') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="s in sensors" :key="s.type" class="border-b border-line align-top last:border-0">
              <td class="px-3 py-2">
                {{ s.name }} <span class="num text-xs text-ink-3">{{ s.type }}</span>
              </td>
              <td class="px-3 py-2">
                <template v-if="s.dcp">{{ t('definitions.mandatory.dcp') }}</template>
                <span
                  v-for="f in s.mandatory"
                  :key="f"
                  class="mb-1 mr-1.5 inline-block rounded bg-sunken px-1.5 py-px text-xs"
                  >{{ field(f) }} <span class="num text-ink-3">{{ f }}</span></span
                >
              </td>
              <td class="px-3 py-2 text-xs text-ink-2">
                {{ [...s.other].map(field).join(', ') || '—' }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section :aria-labelledby="'d-change'">
      <h2 id="d-change" class="mb-2 text-base font-semibold">{{ t('definitions.changes.title') }}</h2>
      <ul class="flex list-disc flex-col gap-1.5 pl-5 text-sm text-ink-2">
        <li v-for="(item, i) in list('definitions.changes.items')" :key="i">{{ item }}</li>
      </ul>
      <p class="mt-2 text-sm">
        <RouterLink :to="`/systems/${code}/data-quality`" class="text-accent hover:underline"
          >{{ t('definitions.changes.link') }} →</RouterLink
        >
      </p>
    </section>

    <section :aria-labelledby="'d-round'">
      <h2 id="d-round" class="mb-2 text-base font-semibold">{{ t('definitions.rounding.title') }}</h2>
      <ul class="flex list-disc flex-col gap-1.5 pl-5 text-sm text-ink-2">
        <li
          v-for="(item, i) in list('definitions.rounding.items', {
            good: display.thresholds.good,
            warning: display.thresholds.warning,
          })"
          :key="i"
        >
          {{ item }}
        </li>
      </ul>
    </section>

    <p v-if="defs" class="text-xs text-ink-3">{{ t('definitions.versionNote') }}</p>
  </div>
</template>
