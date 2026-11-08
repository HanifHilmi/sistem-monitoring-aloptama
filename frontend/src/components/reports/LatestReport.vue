<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ReportEntry, ReportType } from '@/api/types'
import { since } from '@/utils/alarms'
import { formatUtc } from '@/utils/time'
import ReportKind from './ReportKind.vue'
import ReportText from './ReportText.vue'

// The newest report of one type, large and copyable, with the few before it (FR-RPT-001). METAR and MET REPORT
// come every half hour: when the newest is older than 40 minutes, the card says so.
const props = defineProps<{ type: ReportType; reports: ReportEntry[]; now: number }>()
const { t } = useI18n()
const newest = computed(() => props.reports[0] ?? null)
const earlier = computed(() => props.reports.slice(1))
const open = ref<number | null>(null)
const STALE_MIN = 40
const stale = computed(
  () =>
    props.type !== 'taf' &&
    !!newest.value &&
    props.now - Date.parse(newest.value.logged_at) > STALE_MIN * 60_000,
)
const clock = (iso: string) => iso.slice(11, 19)
</script>

<template>
  <section
    class="rounded-lg border border-line bg-surface"
    :aria-label="t(`reports.type.${type}`)"
    :data-testid="`latest-${type}`"
  >
    <header class="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line px-4 py-2.5">
      <h2 class="text-sm font-semibold">{{ t(`reports.type.${type}`) }}</h2>
      <template v-if="newest">
        <ReportKind :kind="newest.kind" />
        <span class="num text-xs text-ink-2" :title="formatUtc(newest.logged_at, { seconds: true })">
          {{ t('reports.logged', { time: formatUtc(newest.logged_at, { seconds: true }) }) }} ·
          {{ t('reports.ago', { age: since(newest.logged_at, now, t) }) }}
        </span>
        <span class="num ml-auto text-[0.6875rem] text-ink-3">{{ newest.cdps.join(' + ') }}</span>
      </template>
    </header>
    <div class="px-4 py-3">
      <p v-if="!newest" class="text-sm text-ink-3">{{ t('reports.none') }}</p>
      <template v-else>
        <p v-if="stale" class="mb-2 text-xs text-warn" role="status">
          ⚠ {{ t('reports.stale', { age: since(newest.logged_at, now, t) }) }}
        </p>
        <ReportText :entry="newest" large />
      </template>
    </div>
    <div v-if="earlier.length" class="border-t border-line px-4 pb-2 pt-1.5">
      <h3 class="eyebrow mb-1">{{ t('reports.earlier') }}</h3>
      <ul class="flex flex-col">
        <li v-for="e in earlier" :key="e.id" class="border-b border-line/60 last:border-0">
          <button
            type="button"
            class="flex w-full items-start gap-2 py-1.5 text-left hover:text-ink"
            :aria-expanded="open === e.id"
            @click="open = open === e.id ? null : e.id"
          >
            <span class="num w-16 shrink-0 text-xs text-ink-3">{{ clock(e.logged_at) }}</span>
            <ReportKind :kind="e.kind" />
            <span
              v-if="open !== e.id"
              class="num min-w-0 flex-1 truncate text-xs text-ink-2"
              :title="e.text"
              >{{ e.text.replace(/\n/g, ' ') }}</span
            >
          </button>
          <div v-if="open === e.id" class="pb-2 pl-[4.5rem]"><ReportText :entry="e" /></div>
        </li>
      </ul>
    </div>
  </section>
</template>
