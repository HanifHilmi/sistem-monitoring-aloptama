<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import { api } from '@/api/client'
import type { Rule, SystemInfo } from '@/api/types'
import RuleForm from '@/components/detections/RuleForm.vue'
import SidePanel from '@/components/SidePanel.vue'
import { useLoader } from '@/composables/useLoader'
import type { Locale } from '@/i18n'
import { useDisplayStore } from '@/stores/display'
import { DEFAULT_SYSTEM } from '@/stores/live'
import { ruleText } from '@/utils/rules'

// Validity rules (FR-DQ-001/002): per field of a component type, optionally for one site. A rule only raises
// suspects; nothing changes a figure until an Admin confirms (FR-DQ-004). Rules proposed from the history stay
// off until approved (OPEN-08).
const { t, locale } = useI18n()
const lc = computed(() => locale.value as Locale)
const display = useDisplayStore()
const info = ref<SystemInfo | null>(null)
void display.system(DEFAULT_SYSTEM).then((s) => (info.value = s))
const loader = useLoader<Rule[]>(() => api.rules(DEFAULT_SYSTEM))
void loader.load()
const onlyProposed = ref(false)

const proposed = computed(() => (loader.data.value ?? []).filter((r) => r.proposed).length)
/** Component types and their numeric fields, in registry order, each with its rules. */
const groups = computed(() => {
  const sy = info.value
  if (!sy) return []
  const out: {
    type: string
    name: string
    fields: { code: string; name: string; mandatory: boolean; rules: Rule[] }[]
  }[] = []
  for (const site of sy.sites)
    for (const c of site.components) {
      if (c.is_dcp || out.some((g) => g.type === c.type)) continue
      const codes = [
        ...new Set(
          sy.sites.flatMap((s) => s.components.filter((x) => x.type === c.type).flatMap((x) => x.fields)),
        ),
      ].filter((f) => sy.fields[f]?.type === 'numeric' && !['WGS', 'WGD'].includes(f))
      const fields = codes
        .map((code) => ({
          code,
          name: sy.fields[code]!.name[lc.value],
          mandatory: c.mandatory.includes(code),
          rules: (loader.data.value ?? []).filter((r) => r.component_type === c.type && r.field === code),
        }))
        .filter((f) => !onlyProposed.value || f.rules.some((r) => r.proposed))
      if (fields.length) out.push({ type: c.type, name: c.name[lc.value], fields })
    }
  return out
})
const siteName = (slug: string) => info.value?.sites.find((s) => s.slug === slug)?.name[lc.value] ?? slug
const unit = (code: string) => info.value?.fields[code]?.unit ?? null

const editing = ref<{ type: string; field: string; rule: Rule | null } | null>(null)
const taken = computed(() =>
  (loader.data.value ?? [])
    .filter((r) => r.component_type === editing.value?.type && r.field === editing.value?.field)
    .map((r) => `${r.type}|${r.site ?? ''}`),
)
const siblings = computed(() =>
  (loader.data.value ?? []).filter(
    (r) =>
      r.component_type === editing.value?.type &&
      r.field === editing.value?.field &&
      r.id !== editing.value?.rule?.id,
  ),
)
function done() {
  editing.value = null
  void loader.load({ silent: true })
}
</script>

<template>
  <div class="flex flex-col gap-4">
    <header class="max-w-2xl">
      <h2 class="text-base font-semibold">{{ t('rules.title') }}</h2>
      <p class="text-sm text-ink-2">{{ t('rules.subtitle') }}</p>
    </header>

    <div
      v-if="proposed"
      class="flex flex-wrap items-center gap-3 rounded-lg border border-accent/40 bg-accent-soft px-4 py-3 text-sm"
      data-testid="proposed-banner"
    >
      <span class="min-w-0 flex-1">{{ t('rules.proposedBanner', { n: proposed }, proposed) }}</span>
      <label class="flex items-center gap-2 text-xs text-ink-2">
        <input v-model="onlyProposed" type="checkbox" class="h-4 w-4 accent-[var(--s-accent)]" />
        {{ t('rules.onlyProposed') }}
      </label>
    </div>

    <p v-if="loader.error.value" class="text-sm text-warn" role="alert">{{ t('common.error') }}</p>
    <div
      v-else-if="!loader.data.value || !info"
      class="h-60 animate-pulse rounded-lg bg-sunken"
      aria-busy="true"
    />
    <section
      v-for="g in groups"
      v-else
      :key="g.type"
      class="overflow-hidden rounded-lg border border-line bg-surface"
      :aria-label="g.name"
    >
      <h3 class="border-b border-line bg-sunken/60 px-4 py-2 text-sm font-semibold">
        {{ g.name }} <span class="text-xs font-normal text-ink-3">· {{ g.type }}</span>
      </h3>
      <ul>
        <li
          v-for="f in g.fields"
          :key="f.code"
          class="flex flex-col gap-2 border-b border-line px-4 py-2.5 last:border-0 sm:flex-row sm:items-start"
          data-testid="rule-field"
        >
          <span class="w-48 shrink-0 text-sm">
            {{ f.name }}
            <span class="num text-xs text-ink-3"
              >{{ f.code }}<span v-if="f.mandatory" :title="t('sensor.mandatory')">*</span></span
            >
            <span class="block text-[0.6875rem]" :class="f.mandatory ? 'text-ink-2' : 'text-ink-3'">{{
              f.mandatory ? t('rules.mandatory') : t('rules.optional')
            }}</span>
          </span>
          <span class="flex min-w-0 flex-1 flex-wrap gap-1.5">
            <button
              v-for="r in f.rules"
              :key="r.id"
              type="button"
              class="inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-left text-xs hover:border-line-strong"
              :class="
                r.proposed
                  ? 'border-dashed border-accent/60 bg-accent-soft/60'
                  : r.enabled
                    ? 'border-line bg-surface'
                    : 'border-line bg-sunken text-ink-3'
              "
              data-testid="rule-chip"
              @click="editing = { type: g.type, field: f.code, rule: r }"
            >
              <span
                class="h-2 w-2 shrink-0 rounded-full"
                :class="r.proposed ? 'bg-accent' : r.enabled ? 'bg-ok' : 'bg-line-strong'"
                aria-hidden="true"
              />
              <span>
                <span class="font-medium">{{ t(`rules.type.${r.type}`) }}</span>
                <template v-if="r.site"> · {{ siteName(r.site) }}</template>
                · <span class="num">{{ ruleText(r.type, r.params, unit(f.code), lc, t) }}</span>
                <span class="block text-[0.625rem] text-ink-3">
                  {{
                    r.proposed
                      ? t('rules.state.proposed')
                      : r.enabled
                        ? t('rules.state.on')
                        : t('rules.state.off')
                  }}
                  · v{{ r.version }}
                </span>
              </span>
              <RouterLink
                v-if="r.suspects"
                :to="`/admin/review?status=suspect`"
                class="rounded-full border border-dashed border-detect px-1.5 text-[0.625rem] text-detect"
                @click.stop
                >{{ t('detections.chipSuspect', { n: r.suspects }, r.suspects) }}</RouterLink
              >
            </button>
            <button
              type="button"
              class="rounded-md border border-dashed border-line px-2 py-1 text-xs text-ink-3 hover:border-line-strong hover:text-ink"
              @click="editing = { type: g.type, field: f.code, rule: null }"
            >
              + {{ t('rules.add') }}
            </button>
          </span>
        </li>
      </ul>
    </section>

    <SidePanel
      :open="editing !== null"
      :title="
        editing
          ? editing.rule
            ? `${t(`rules.type.${editing.rule.type}`)} · ${editing.field}`
            : t('rules.newTitle', { field: editing.field })
          : ''
      "
      :subtitle="
        editing && info ? `${editing.type} · ${info.fields[editing.field]?.name[lc] ?? ''}` : undefined
      "
      @close="editing = null"
    >
      <RuleForm
        v-if="editing && info"
        :key="`${editing.type}|${editing.field}|${editing.rule?.id ?? 'new'}`"
        :system="DEFAULT_SYSTEM"
        :info="info"
        :component-type="editing.type"
        :field="editing.field"
        :rule="editing.rule"
        :taken="taken"
        :siblings="siblings"
        @done="done"
        @cancel="editing = null"
      />
    </SidePanel>
  </div>
</template>
