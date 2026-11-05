<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { api, MAX_OUTAGE_DAYS } from '@/api/client'
import type { Outage, OutageCause, OutagesResponse, SystemInfo } from '@/api/types'
import { useLoader } from '@/composables/useLoader'
import type { Locale } from '@/i18n'
import { int } from '@/utils/format'

// Why a scope lost minutes in a period (FR-KPI-009): minutes per cause, then the longest intervals. The causes
// add up to the same lost minutes as the matrix and the KPIs. Selecting an interval opens its day.
const props = defineProps<{
  systemCode: string
  scope: string
  from: Date
  to: Date
  info: SystemInfo
}>()
const emit = defineEmits<{ pick: [Outage] }>()
const { t, locale } = useI18n()
const lc = computed(() => locale.value as Locale)

const FIRST = 8
const STEP = 20
const tooLong = computed(() => props.to.getTime() - props.from.getTime() > MAX_OUTAGE_DAYS * 86_400_000)
const loader = useLoader<OutagesResponse>(() =>
  api.outages(props.systemCode, props.from, props.to, props.scope),
)
const shownCount = ref(FIRST)
watch(
  () => `${props.scope}|${props.from.toISOString()}|${props.to.toISOString()}`,
  () => {
    shownCount.value = FIRST
    if (!tooLong.value) void loader.load()
  },
  { immediate: true },
)

const CAUSE_BG: Record<OutageCause, string> = {
  cdp_no_data: 'bg-bad',
  no_record: 'bg-bad/55',
  field_missing: 'bg-warn',
  flagged: 'bg-flag',
  detection: 'bg-detect',
}
const data = computed(() => loader.data.value)
const lost = computed(() => data.value?.availability.missing ?? 0)
const causes = computed(() =>
  (Object.entries(data.value?.by_cause ?? {}) as [OutageCause, number][])
    .filter(([, n]) => n > 0)
    .sort((a, b) => b[1] - a[1])
    .map(([cause, minutes]) => ({ cause, minutes, share: minutes / Math.max(1, lost.value) })),
)
const shown = computed(() => data.value?.intervals.slice(0, shownCount.value) ?? [])
const remaining = computed(() => (data.value?.intervals.length ?? 0) - shown.value.length)

// ---- labels --------------------------------------------------------------------------------------
const kind = computed(() => props.scope.split(':')[0])
const scopeSize = computed(() => {
  if (kind.value === 'ola') return props.info.sites.reduce((n, s) => n + s.components.length, 0)
  if (kind.value === 'site')
    return props.info.sites.find((s) => s.slug === props.scope.slice(5))?.components.length ?? 0
  return 1
})
const siteName = (slug: string) => props.info.sites.find((s) => s.slug === slug)?.name[lc.value] ?? slug
const compName = (slug: string, type: string) =>
  props.info.sites.find((s) => s.slug === slug)?.components.find((c) => c.type === type)?.name[lc.value] ??
  type

/** Which components an interval hit; empty when the panel title already says it (one component, SLA, a CDP). */
function where(iv: Outage): string {
  const members = iv.components ?? []
  if (kind.value === 'component' || !members.length) return ''
  if (members.length === scopeSize.value && members.length > 1)
    return t('outages.allComponents', { n: members.length })
  if (members.length === 1) {
    const m = members[0]!
    const name = compName(m.site, m.component)
    return kind.value === 'site' ? name : `${siteName(m.site)} · ${name}`
  }
  const sites = new Set(members.map((m) => m.site))
  const n = t('outages.components', { n: members.length })
  return kind.value === 'ola' && sites.size === 1 ? `${siteName([...sites][0]!)} · ${n}` : n
}

function what(iv: Outage): string {
  const name = t(`outages.cause.${iv.cause}`)
  if (iv.cause === 'detection' && iv.detections?.length)
    return `${name} · ${iv.detections.map((d) => `${t(`rules.type.${d.type}`)} ${d.field}`).join(', ')}`
  if (iv.cause === 'flagged' && iv.flags?.length)
    return `${name} · ${[...new Set(iv.flags.map((f) => t(`flags.reason.${f.reason}`)))].join(', ')}`
  if (iv.cause !== 'field_missing') return name
  const members = iv.components ?? []
  const fields = [...new Set(members.flatMap((m) => m.fields ?? []))]
  if (!fields.length) return `${name} · ${t('outages.allFields')}` // a DCP: every field was missing
  return `${name} · ${fields.join(', ')}`
}

function duration(minutes: number): string {
  const d = Math.floor(minutes / 1440)
  const h = Math.floor((minutes % 1440) / 60)
  const m = minutes % 60
  if (d) return t('outages.durDays', { d, h })
  if (h) return t('outages.durHours', { h, m })
  return t('outages.durMinutes', { m })
}

const dayFmt = computed(
  () =>
    new Intl.DateTimeFormat(lc.value === 'id' ? 'id-ID' : 'en-GB', {
      day: 'numeric',
      month: 'short',
      timeZone: 'UTC',
    }),
)
const hhmm = (iso: string) => iso.slice(11, 16)
function range(iv: Outage): string {
  const start = new Date(iv.start)
  const end = new Date(iv.end)
  const last = new Date(end.getTime() - 60_000)
  const from = `${dayFmt.value.format(start)} ${hhmm(iv.start)}`
  if (iv.ongoing) return `${from} – ${t('outages.ongoing')}`
  if (start.toISOString().slice(0, 10) === last.toISOString().slice(0, 10)) {
    const to = hhmm(iv.end) === '00:00' ? '24:00' : hhmm(iv.end)
    return `${from}–${to}`
  }
  return `${from} – ${dayFmt.value.format(end)} ${hhmm(iv.end)}`
}
</script>

<template>
  <section :aria-label="t('outages.title')" data-testid="outages">
    <h3 class="eyebrow mb-1.5">{{ t('outages.title') }}</h3>
    <p v-if="tooLong" class="text-xs text-ink-3">{{ t('outages.tooLong', { days: MAX_OUTAGE_DAYS }) }}</p>
    <p v-else-if="loader.error.value" class="text-sm text-warn" role="alert">
      {{ t('common.error') }}
      <button type="button" class="icon-btn" @click="loader.load()">{{ t('common.retry') }}</button>
    </p>
    <div v-else-if="!data" class="h-24 animate-pulse rounded-md bg-sunken" aria-busy="true" />
    <p v-else-if="!lost" class="text-xs text-ok">{{ t('outages.none') }}</p>
    <template v-else>
      <div
        class="flex h-2 gap-px overflow-hidden rounded-full bg-sunken"
        role="img"
        :aria-label="causes.map((c) => `${t(`outages.cause.${c.cause}`)}: ${c.minutes}`).join(', ')"
      >
        <span
          v-for="c in causes"
          :key="c.cause"
          class="h-full"
          :class="CAUSE_BG[c.cause]"
          :style="{ width: `${Math.max(1, c.share * 100)}%` }"
        />
      </div>
      <ul class="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-[0.6875rem] text-ink-2">
        <li v-for="c in causes" :key="c.cause" class="flex items-center gap-1.5" data-testid="outage-cause">
          <span class="h-2.5 w-2.5 rounded-[2px]" :class="CAUSE_BG[c.cause]" />
          {{ t(`outages.cause.${c.cause}`) }}
          <span class="num text-ink">{{ t('outages.minutes', { n: int(c.minutes, lc) }) }}</span>
        </li>
      </ul>
      <p class="mt-1 text-[0.6875rem] text-ink-3" data-testid="outage-summary">
        {{
          t(
            'outages.summary',
            { minutes: int(lost, lc), n: int(data.intervals_total, lc) },
            data.intervals_total,
          )
        }}
      </p>

      <ol class="mt-2 flex flex-col">
        <li v-for="(iv, i) in shown" :key="`${iv.start}|${iv.end}|${iv.cause}`">
          <button
            type="button"
            class="group flex w-full items-start gap-2 border-b border-line px-1 py-1.5 text-left hover:bg-sunken"
            :aria-label="`${what(iv)}, ${range(iv)}, ${duration(iv.minutes)}. ${t('outages.open')}`"
            data-testid="outage"
            @click="emit('pick', iv)"
          >
            <span class="num w-4 shrink-0 pt-px text-[0.6875rem] text-ink-3">{{ i + 1 }}</span>
            <span class="mt-1 h-2.5 w-2.5 shrink-0 rounded-[2px]" :class="CAUSE_BG[iv.cause]" />
            <span class="flex min-w-0 flex-1 flex-col gap-0.5">
              <span class="truncate text-xs group-hover:text-accent">{{ what(iv) }}</span>
              <span class="flex min-w-0 gap-1 text-[0.6875rem] text-ink-3">
                <span class="num shrink-0">{{ range(iv) }}</span>
                <span v-if="where(iv)" class="truncate">· {{ where(iv) }}</span>
              </span>
            </span>
            <span class="num shrink-0 text-right text-xs font-medium">{{ duration(iv.minutes) }}</span>
          </button>
        </li>
      </ol>
      <button
        v-if="remaining > 0"
        type="button"
        class="mt-2 text-xs text-accent hover:underline"
        @click="shownCount += STEP"
      >
        {{ t('outages.more', { n: Math.min(STEP, remaining) }) }}
      </button>
      <p v-if="data.truncated && remaining <= 0" class="mt-1 text-[0.6875rem] text-ink-3">
        {{ t('outages.truncated', { shown: data.intervals.length, total: data.intervals_total }) }}
      </p>
      <p class="mt-2 text-[0.6875rem] text-ink-3">{{ t('outages.note') }}</p>
    </template>
  </section>
</template>
