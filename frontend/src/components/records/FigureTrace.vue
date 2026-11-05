<script setup lang="ts">
import { computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import { api } from '@/api/client'
import type { TraceEvent } from '@/api/types'
import { useLoader } from '@/composables/useLoader'
import type { Locale } from '@/i18n'
import { useAuthStore } from '@/stores/auth'
import { formatDays, formatRange } from '@/utils/flags'
import { formatUtc } from '@/utils/time'

// Figure change trace (FR-AUD-003): the changes that moved a component's figures in a period, from the audit log:
// flags, detection decisions, mandatory fields of its type, its in-service period, reprocess and recompute jobs.
// Signed-in users only (it names who made each change).
const props = defineProps<{ systemCode: string; scope: string; from: Date; to: Date }>()
const { t, locale } = useI18n()
const lc = computed(() => locale.value as Locale)
const auth = useAuthStore()
const loader = useLoader<TraceEvent[]>(() => api.trace(props.systemCode, props.scope, props.from, props.to))
watch(
  () => `${props.scope}|${props.from.toISOString()}|${props.to.toISOString()}|${auth.canView}`,
  () => auth.canView && loader.load(),
  { immediate: true },
)

const s = (v: unknown) => String(v ?? '')
function describe(e: TraceEvent): string {
  const d = e.detail
  switch (e.action) {
    case 'flag_created':
    case 'flag_updated':
    case 'flag_removed':
      return t(`trace.${e.action}`, {
        id: s(d.flag),
        reason: t(`flags.reason.${s(d.reason)}`),
        range: formatRange(s(d.start), s(d.end), lc.value, true),
      })
    case 'detections_decided':
      return t(`trace.detection_${s(d.status)}`, {
        id: s(d.detection),
        rule: `${t(`rules.type.${s(d.type)}`)} ${s(d.field)}`,
        range: formatRange(s(d.start), s(d.end), lc.value, true),
      })
    case 'mandatory_changed':
      return t('trace.mandatory_changed', {
        type: s(e.entity_id),
        before: (d.before as string[] | undefined)?.join(', ') ?? '—',
        after: (d.after as string[] | undefined)?.join(', ') ?? '—',
      })
    case 'in_service_changed':
      return t('trace.in_service_changed', {
        from: d.in_service_from ? formatUtc(s(d.in_service_from)) : '—',
        to: d.in_service_to ? formatUtc(s(d.in_service_to)) : t('components.open'),
      })
    case 'job_started':
      return t(`trace.job_${s(d.type)}`, { days: formatDays({ from: s(d.from), to: s(d.to) }, lc.value) })
    default:
      return e.action
  }
}
function link(e: TraceEvent): string | null {
  if (!auth.isAdmin) return null
  if (e.entity_type === 'flag') return `/admin/flags?id=${e.entity_id}`
  if (e.entity_type === 'detection') return `/admin/review?status=${s(e.detail.status)}&id=${e.entity_id}`
  if (e.entity_type === 'job') return '/admin/jobs'
  return null
}
</script>

<template>
  <section v-if="auth.canView" :aria-label="t('trace.title')" data-testid="trace">
    <h3 class="eyebrow mb-1.5">{{ t('trace.title') }}</h3>
    <div v-if="!loader.data.value" class="h-12 animate-pulse rounded bg-sunken" aria-busy="true" />
    <p v-else-if="!loader.data.value.length" class="text-xs text-ink-3">{{ t('trace.none') }}</p>
    <ol v-else class="flex flex-col">
      <li v-for="e in loader.data.value" :key="e.id" class="flex gap-3 border-t border-line py-1.5 text-xs">
        <span class="num w-32 shrink-0 text-ink-3">{{ formatUtc(e.time) }}</span>
        <span class="min-w-0 flex-1">
          {{ describe(e) }}
          <RouterLink v-if="link(e)" :to="link(e)!" class="ml-1 text-accent hover:underline">{{
            t('detections.open')
          }}</RouterLink>
          <span class="block text-ink-3">{{ e.actor ?? '—' }}</span>
        </span>
      </li>
    </ol>
    <p class="mt-1 text-[0.6875rem] text-ink-3">{{ t('trace.note') }}</p>
  </section>
</template>
