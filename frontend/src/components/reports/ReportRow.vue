<script setup lang="ts">
import type { ReportEntry } from '@/api/types'
import ReportKind from './ReportKind.vue'
import ReportText from './ReportText.vue'

// One report in the day's archive or the search results: when it was logged, its name, the text, the CDPs.
defineProps<{ entry: ReportEntry; withDate?: boolean; highlight?: string }>()
</script>

<template>
  <li
    class="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 border-b border-line px-3 py-2.5 last:border-0 md:grid-cols-[6.5rem_minmax(0,1fr)_7rem]"
    data-testid="report-row"
  >
    <p class="flex flex-col gap-1">
      <span class="num text-xs text-ink-2"
        ><span v-if="withDate" class="block text-ink-3">{{ entry.logged_at.slice(0, 10) }}</span
        >{{ entry.logged_at.slice(11, 19) }}</span
      >
      <ReportKind :kind="entry.kind" class="self-start" />
    </p>
    <ReportText :entry="entry" :highlight="highlight" />
    <p class="num col-start-2 text-[0.6875rem] text-ink-3 md:col-start-auto md:text-right">
      {{ entry.cdps.join(' + ') }}
    </p>
  </li>
</template>
