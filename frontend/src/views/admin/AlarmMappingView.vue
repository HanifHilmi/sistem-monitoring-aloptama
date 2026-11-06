<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { api, ApiProblem } from '@/api/client'
import type { AlarmName, AlarmPlace, SystemInfo } from '@/api/types'
import AlarmTypeBadge from '@/components/alarms/AlarmTypeBadge.vue'
import { useLoader } from '@/composables/useLoader'
import type { Locale } from '@/i18n'
import { useDisplayStore } from '@/stores/display'
import { DEFAULT_SYSTEM } from '@/stores/live'
import { formatUtc } from '@/utils/time'

// Alarm mapping (FR-ING-008, E12): which site and sensor each AWOS alarm name belongs to. Seeded from the name
// (DCPA = Runway 04, DCPB = Middle, DCPC = Runway 22); a new name arrives "not assigned". A change applies to the
// whole history at once and is audited.
const { t, locale } = useI18n()
const lc = computed(() => locale.value as Locale)
const display = useDisplayStore()
const info = ref<SystemInfo | null>(null)
onMounted(async () => (info.value = await display.system(DEFAULT_SYSTEM)))
const loader = useLoader<AlarmName[]>(() => api.alarmNames(DEFAULT_SYSTEM))
void loader.load()

const encode = (p: AlarmPlace) =>
  p.kind === 'component'
    ? `component:${p.site}:${p.component}`
    : p.kind === 'site'
      ? `site:${p.site}`
      : p.kind
function decode(v: string): AlarmPlace {
  const [kind, site, component] = v.split(':')
  if (kind === 'component') return { kind, site: site!, component: component! }
  if (kind === 'site') return { kind, site: site!, component: null }
  return { kind: kind as 'station' | 'unmapped', site: null, component: null }
}
const options = computed(() => {
  const groups: { label: string; items: { value: string; label: string }[] }[] = [
    {
      label: t('alarms.mapping.general'),
      items: [
        { value: 'unmapped', label: t('alarms.place.unmapped') },
        { value: 'station', label: t('alarms.place.station') },
      ],
    },
  ]
  for (const s of info.value?.sites ?? [])
    groups.push({
      label: s.name[lc.value],
      items: [
        { value: `site:${s.slug}`, label: t('alarms.mapping.wholeSite', { site: s.name[lc.value] }) },
        ...s.components.map((c) => ({
          value: `component:${s.slug}:${c.type}`,
          label: `${s.name[lc.value]} · ${c.name[lc.value]}`,
        })),
      ],
    })
  return groups
})

const filter = ref<'all' | 'unmapped'>('all')
const rows = computed(() =>
  (loader.data.value ?? []).filter((n) => filter.value === 'all' || n.place.kind === 'unmapped'),
)
const unmapped = computed(() => (loader.data.value ?? []).filter((n) => n.place.kind === 'unmapped').length)

const draft = reactive<Record<string, string>>({})
const busy = ref<string | null>(null)
const errors = reactive<Record<string, string>>({})
const saved = ref<string | null>(null)
const value = (n: AlarmName) => draft[n.name] ?? encode(n.place)
async function save(n: AlarmName) {
  busy.value = n.name
  delete errors[n.name]
  try {
    await api.saveAlarmName(DEFAULT_SYSTEM, n.name, decode(value(n)))
    delete draft[n.name]
    saved.value = n.name
    await loader.load({ silent: true })
  } catch (e) {
    errors[n.name] = e instanceof ApiProblem ? e.code : 'network_error'
  } finally {
    busy.value = null
  }
}
</script>

<template>
  <div class="flex flex-col gap-4">
    <header class="max-w-2xl">
      <h2 class="text-base font-semibold">{{ t('alarms.mapping.title') }}</h2>
      <p class="text-sm text-ink-2">{{ t('alarms.mapping.subtitle') }}</p>
    </header>

    <div class="seg self-start" role="group" :aria-label="t('alarms.mapping.title')">
      <button type="button" :aria-pressed="filter === 'all'" @click="filter = 'all'">
        {{ t('alarms.filter.all') }} <span class="num text-ink-3">{{ loader.data.value?.length ?? '' }}</span>
      </button>
      <button type="button" :aria-pressed="filter === 'unmapped'" @click="filter = 'unmapped'">
        {{ t('alarms.place.unmapped') }} <span class="num text-ink-3">{{ unmapped }}</span>
      </button>
    </div>

    <p v-if="loader.error.value" class="text-sm text-warn" role="alert">{{ t('common.error') }}</p>
    <div v-else-if="!loader.data.value" class="h-60 animate-pulse rounded-lg bg-sunken" aria-busy="true" />
    <ul v-else class="overflow-hidden rounded-lg border border-line bg-surface">
      <li
        v-for="n in rows"
        :key="n.name"
        class="grid grid-cols-1 gap-x-4 gap-y-2 border-b border-line px-4 py-3 last:border-0 md:grid-cols-[minmax(0,1fr)_17rem]"
        :class="n.place.kind === 'unmapped' ? 'bg-warn/5' : ''"
        data-testid="alarm-name"
      >
        <div class="min-w-0">
          <p class="flex flex-wrap items-center gap-2">
            <AlarmTypeBadge :type="n.type" />
            <span class="num text-sm font-medium break-all">{{ n.name }}</span>
          </p>
          <p class="mt-0.5 text-sm text-ink-2">{{ n.message }}</p>
          <p class="num text-[0.6875rem] text-ink-3">
            {{ t('alarms.mapping.seen', { n: n.events, time: formatUtc(n.last_seen) }, n.events) }}
            ·
            {{
              n.source === 'admin'
                ? t('alarms.mapping.byAdmin', { who: n.updated_by, time: formatUtc(n.updated_at) })
                : t('alarms.mapping.bySeed')
            }}
          </p>
        </div>
        <div class="flex flex-col gap-1.5">
          <label class="sr-only" :for="`place-${n.name}`">{{ t('alarms.filter.place') }}</label>
          <select
            :id="`place-${n.name}`"
            class="input py-1.5 text-sm"
            :value="value(n)"
            @change="draft[n.name] = ($event.target as HTMLSelectElement).value"
          >
            <optgroup v-for="g in options" :key="g.label" :label="g.label">
              <option v-for="o in g.items" :key="o.value" :value="o.value">{{ o.label }}</option>
            </optgroup>
          </select>
          <div class="flex items-center gap-2 text-xs">
            <button
              v-if="draft[n.name] !== undefined && draft[n.name] !== encode(n.place)"
              type="button"
              class="btn-primary py-1 text-xs"
              :disabled="busy === n.name"
              @click="save(n)"
            >
              {{ t('records.save') }}
            </button>
            <span v-if="saved === n.name && draft[n.name] === undefined" class="text-ok"
              >✓ {{ t('alarms.mapping.saved') }}</span
            >
            <span v-if="errors[n.name]" class="text-bad" role="alert">{{ t('common.error') }}</span>
          </div>
        </div>
      </li>
    </ul>
    <p class="text-xs text-ink-3">{{ t('alarms.mapping.note') }}</p>
  </div>
</template>
