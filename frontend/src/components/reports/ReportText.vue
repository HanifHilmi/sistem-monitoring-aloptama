<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ReportEntry } from '@/api/types'

// One report exactly as issued (FR-RPT-001, never decoded: FR-RPT-004), in monospace with a Copy button. The AWOS's
// own notes (why a SPECI was issued, the runway in use) are shown beside it, not mixed into the text.
const props = withDefaults(
  defineProps<{ entry: ReportEntry; large?: boolean; highlight?: string; notes?: boolean }>(),
  { large: false, highlight: '', notes: true },
)
const { t } = useI18n()
const copied = ref(false)
async function copy() {
  try {
    await navigator.clipboard.writeText(props.entry.text)
    copied.value = true
    setTimeout(() => (copied.value = false), 1500)
  } catch {
    /* the text can still be selected by hand */
  }
}
/** The text cut at each match of the search, so matches can be marked. */
const parts = computed(() => {
  const q = props.highlight.trim()
  if (!q) return [{ text: props.entry.text, hit: false }]
  const re = new RegExp(`(${q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi')
  return props.entry.text
    .split(re)
    .filter((x) => x !== '')
    .map((x) => ({ text: x, hit: x.toLowerCase() === q.toLowerCase() }))
})
</script>

<template>
  <div class="flex flex-col gap-1.5">
    <div class="flex items-start gap-2">
      <div class="min-w-0 flex-1">
        <p v-if="entry.bulletin" class="num text-[0.6875rem] text-ink-3">{{ entry.bulletin }}</p>
        <pre
          class="num whitespace-pre-wrap break-words text-ink"
          :class="large ? 'text-[0.9375rem] leading-relaxed' : 'text-xs leading-snug'"
          data-testid="report-text"
        ><template v-for="(p, i) in parts" :key="i"><mark v-if="p.hit" class="rounded-sm bg-accent/25 text-ink">{{ p.text }}</mark><template v-else>{{ p.text }}</template></template></pre>
      </div>
      <button
        type="button"
        class="shrink-0 rounded-md border border-line px-1.5 py-0.5 text-[0.6875rem] text-ink-2 hover:bg-sunken hover:text-ink"
        :class="copied ? '!border-ok/50 !text-ok' : ''"
        :aria-label="`${t('reports.copy')}: ${entry.kind} ${entry.logged_at.slice(11, 16)}`"
        @click="copy"
      >
        {{ copied ? `✓ ${t('reports.copied')}` : t('reports.copy') }}
      </button>
    </div>
    <p v-if="notes && (entry.notes.length || entry.runway)" class="flex flex-wrap gap-1.5 text-[0.6875rem]">
      <span
        v-for="n in entry.notes"
        :key="n"
        class="rounded border border-warn/40 bg-warn/10 px-1.5 py-px text-ink-2"
        :title="t('reports.note')"
        >{{ n }}</span
      >
      <span
        v-if="entry.runway"
        class="num rounded border border-line px-1.5 py-px text-ink-3"
        :title="t('reports.runwayTitle')"
        >{{ t('reports.runway', { rwy: entry.runway }) }}</span
      >
    </p>
  </div>
</template>
