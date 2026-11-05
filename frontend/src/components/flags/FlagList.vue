<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { Flag, SystemInfo } from '@/api/types'
import type { Locale } from '@/i18n'
import { formatDuration, formatRange } from '@/utils/flags'
import { formatUtc } from '@/utils/time'

// Flags touching a chart window or a day (FR-DQ-007): reason and time for everyone; note and author only reach
// signed-in users (the API leaves them out for the public). Admins get an Edit button.
const props = defineProps<{
  flags: Flag[]
  info?: SystemInfo | null
  canEdit?: boolean
  /** list the flagged components too (when the list is not about one component) */
  withComponents?: boolean
}>()
const emit = defineEmits<{ edit: [id: number] }>()
const { t, locale } = useI18n()
const lc = computed(() => locale.value as Locale)

const compName = (site: string, type: string) => {
  const s = props.info?.sites.find((x) => x.slug === site)
  const c = s?.components.find((x) => x.type === type)
  return s && c ? `${s.name[lc.value]} · ${c.name[lc.value]}` : `${site} · ${type}`
}
const minutes = (f: Flag) => (Date.parse(f.end) - Date.parse(f.start)) / 60_000
</script>

<template>
  <ul class="flex flex-col gap-2" data-testid="flag-list">
    <li v-for="f in flags" :key="f.id" class="flex items-start gap-2 text-xs">
      <span
        class="flag-hatch mt-0.5 h-3 w-3 shrink-0 rounded-[2px] border border-flag/60"
        aria-hidden="true"
      />
      <span class="min-w-0 flex-1 leading-snug">
        <span class="font-medium text-ink">{{ t(`flags.reason.${f.reason}`) }}</span>
        <span class="num text-ink-2">
          · {{ formatRange(f.start, f.end, lc) }} UTC · {{ formatDuration(minutes(f), t) }}</span
        >
        <span v-if="withComponents" class="block text-ink-2">{{
          f.components.map((c) => compName(c.site, c.type)).join('; ')
        }}</span>
        <span v-if="f.note" class="block text-ink-2">{{ f.note }}</span>
        <span v-if="f.created_by" class="block text-ink-3">
          {{ t('flags.by', { name: f.created_by, time: formatUtc(f.created_at) }) }} · #{{ f.id }}
        </span>
      </span>
      <button
        v-if="canEdit"
        type="button"
        class="shrink-0 text-accent hover:underline"
        :aria-label="`${t('flags.edit')} #${f.id}`"
        @click="emit('edit', f.id)"
      >
        {{ t('flags.edit') }}
      </button>
    </li>
  </ul>
</template>
