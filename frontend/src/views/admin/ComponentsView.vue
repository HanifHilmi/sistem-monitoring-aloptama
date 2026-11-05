<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { api } from '@/api/client'
import { CALIBRATION_STATUSES, type Assets, type CalibrationStatus, type ComponentRow } from '@/api/types'
import ComponentPanel, { type PanelTab } from '@/components/records/ComponentPanel.vue'
import CalibrationChip from '@/components/records/CalibrationChip.vue'
import PlaceForm from '@/components/records/PlaceForm.vue'
import SidePanel from '@/components/SidePanel.vue'
import { useLoader } from '@/composables/useLoader'
import type { Locale } from '@/i18n'
import { DEFAULT_SYSTEM } from '@/stores/live'
import { formatUtc } from '@/utils/time'

// Registry and records (FR-REG-004/005/006): the station, each site and each sensor with its record, calibration
// status and in-service period. The list can be filtered by calibration status (FR-REG-005.1).
const { t, locale } = useI18n()
const lc = computed(() => locale.value as Locale)
const route = useRoute()
const loader = useLoader<ComponentRow[]>(() => api.components(DEFAULT_SYSTEM))
const assets = useLoader<Assets>(() => api.assets(DEFAULT_SYSTEM))
void loader.load()
void assets.load()
function reload() {
  void loader.load({ silent: true })
  void assets.load({ silent: true })
}

const filter = ref<CalibrationStatus | ''>(
  CALIBRATION_STATUSES.includes(route.query.calibration as CalibrationStatus)
    ? (route.query.calibration as CalibrationStatus)
    : '',
)
const counts = computed(() => {
  const out = Object.fromEntries(CALIBRATION_STATUSES.map((s) => [s, 0])) as Record<CalibrationStatus, number>
  for (const c of loader.data.value ?? []) if (!c.is_dcp) out[c.calibration.status]++
  return out
})
const sites = computed(() => {
  const by = new Map<string, { site: string; name: ComponentRow['site_name']; rows: ComponentRow[] }>()
  for (const c of loader.data.value ?? []) {
    if (filter.value && (c.is_dcp || c.calibration.status !== filter.value)) continue
    const g = by.get(c.site) ?? { site: c.site, name: c.site_name, rows: [] }
    g.rows.push(c)
    by.set(c.site, g)
  }
  return [...by.values()]
})
const siteMeta = (slug: string) => assets.data.value?.sites.find((s) => s.slug === slug)?.meta
const coords = (lat: number | null | undefined, lon: number | null | undefined) =>
  lat !== null && lat !== undefined && lon !== null && lon !== undefined
    ? `${lat.toFixed(4)}, ${lon.toFixed(4)}`
    : null
const now = Date.now()
function serviceText(c: ComponentRow): { text: string; tone: string } {
  if (c.in_service_from && Date.parse(c.in_service_from) > now)
    return { text: t('components.notYet', { time: formatUtc(c.in_service_from) }), tone: 'text-warn' }
  if (c.in_service_to && Date.parse(c.in_service_to) <= now)
    return { text: t('components.out', { time: formatUtc(c.in_service_to) }), tone: 'text-ink-3' }
  if (c.in_service_from || c.in_service_to)
    return {
      text: t('components.inSince', {
        from: c.in_service_from ? formatUtc(c.in_service_from) : '—',
        to: c.in_service_to ? formatUtc(c.in_service_to) : t('components.open'),
      }),
      tone: 'text-ink-2',
    }
  return { text: '', tone: '' }
}
const model = (c: ComponentRow) => [c.meta.manufacturer, c.meta.model].filter(Boolean).join(' ')

// ---- panels -----------------------------------------------------------------------------------------
const open = ref<{ id: number; tab: PanelTab } | null>(null)
const openRow = computed(() => loader.data.value?.find((c) => c.id === open.value?.id) ?? null)
const place = ref<{ kind: 'station' } | { kind: 'site'; slug: string } | null>(null)
const placeTitle = computed(() => {
  const p = place.value
  if (!p) return ''
  if (p.kind === 'station') return t('records.station.title')
  return loader.data.value?.find((c) => c.site === p.slug)?.site_name[lc.value] ?? p.slug
})
</script>

<template>
  <div class="flex flex-col gap-4">
    <header class="max-w-2xl">
      <h2 class="text-base font-semibold">{{ t('records.title') }}</h2>
      <p class="text-sm text-ink-2">{{ t('records.subtitle') }}</p>
    </header>

    <!-- station -->
    <section
      v-if="assets.data.value"
      class="flex flex-wrap items-start gap-x-6 gap-y-2 rounded-lg border border-line bg-surface px-4 py-3"
      :aria-label="t('records.station.title')"
      data-testid="station"
    >
      <div class="min-w-0 flex-1">
        <p class="eyebrow">{{ t('records.station.title') }}</p>
        <p class="text-sm font-semibold">
          {{ assets.data.value.station.name[lc] }}
          <span class="num font-normal text-ink-3">· {{ assets.data.value.station.icao }}</span>
        </p>
        <p class="text-xs text-ink-2">{{ assets.data.value.station.airport_name }}</p>
      </div>
      <dl class="num grid grid-cols-[auto_auto] gap-x-3 gap-y-0.5 text-xs">
        <dt class="text-ink-3">{{ t('records.place.coords') }}</dt>
        <dd>{{ coords(assets.data.value.station.lat, assets.data.value.station.lon) ?? '—' }}</dd>
        <dt class="text-ink-3">{{ t('records.place.elevation_m') }}</dt>
        <dd>{{ assets.data.value.station.elevation_m ?? '—' }}</dd>
        <dt class="text-ink-3">{{ t('records.station.wmo_number') }}</dt>
        <dd>{{ assets.data.value.station.wmo_number ?? '—' }}</dd>
        <dt class="text-ink-3">{{ t('records.place.procurement_year') }}</dt>
        <dd>{{ assets.data.value.station.procurement_year ?? '—' }}</dd>
      </dl>
      <button type="button" class="btn py-1 text-xs" @click="place = { kind: 'station' }">
        {{ t('flags.edit') }}
      </button>
    </section>

    <div class="flex flex-wrap items-center gap-2">
      <span class="label">{{ t('calibration.filter') }}</span>
      <div class="seg" role="group" :aria-label="t('calibration.filter')">
        <button type="button" :aria-pressed="filter === ''" @click="filter = ''">
          {{ t('calibration.all') }}
        </button>
        <button
          v-for="s in CALIBRATION_STATUSES"
          :key="s"
          type="button"
          :aria-pressed="filter === s"
          @click="filter = s"
        >
          {{ t(`calibration.status.${s}`) }} <span class="num text-ink-3">{{ counts[s] }}</span>
        </button>
      </div>
    </div>

    <p v-if="loader.error.value" class="text-sm text-warn" role="alert">{{ t('common.error') }}</p>
    <div v-else-if="!loader.data.value" class="h-60 animate-pulse rounded-lg bg-sunken" aria-busy="true" />
    <p
      v-else-if="!sites.length"
      class="rounded-lg border border-dashed border-line px-4 py-8 text-center text-sm text-ink-3"
    >
      {{ t('calibration.noneWithStatus') }}
    </p>
    <section
      v-for="g in sites"
      v-else
      :key="g.site"
      class="overflow-hidden rounded-lg border border-line bg-surface"
      :aria-label="g.name[lc]"
    >
      <header class="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line bg-sunken/60 px-4 py-2">
        <h3 class="text-sm font-semibold">{{ g.name[lc] }}</h3>
        <span v-if="siteMeta(g.site)" class="num text-xs text-ink-3">
          {{ coords(siteMeta(g.site)!.lat, siteMeta(g.site)!.lon) ?? '' }}
          <template v-if="siteMeta(g.site)!.elevation_m !== null">
            · {{ t('records.place.elevationShort', { m: siteMeta(g.site)!.elevation_m }) }}</template
          >
        </span>
        <button
          type="button"
          class="ml-auto text-xs text-accent hover:underline"
          @click="place = { kind: 'site', slug: g.site }"
        >
          {{ t('flags.edit') }}
        </button>
      </header>
      <ul>
        <li
          v-for="c in g.rows"
          :key="c.id"
          class="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-line px-4 py-2.5 last:border-0"
          data-testid="component-row"
        >
          <span class="min-w-0 flex-1 text-sm">
            {{ c.name[lc] }} <span class="text-xs text-ink-3">· {{ c.type }}</span>
            <span class="num block text-xs text-ink-2">
              {{ model(c) || '—' }}
              <template v-if="c.meta.serial_number">
                · {{ t('records.sn', { sn: c.meta.serial_number }) }}</template
              >
            </span>
            <span v-if="serviceText(c).text" class="block text-xs" :class="serviceText(c).tone">{{
              serviceText(c).text
            }}</span>
          </span>
          <CalibrationChip v-if="!c.is_dcp" :calibration="c.calibration" />
          <span v-else class="text-xs text-ink-3" :title="t('components.dcpHint')">{{
            t('components.dcp')
          }}</span>
          <button type="button" class="btn py-1 text-xs" @click="open = { id: c.id, tab: 'details' }">
            {{ t('records.open') }}
          </button>
        </li>
      </ul>
    </section>

    <SidePanel
      :open="openRow !== null"
      :title="openRow ? openRow.name[lc] : ''"
      :subtitle="openRow ? `${openRow.site_name[lc]} · ${openRow.type}` : undefined"
      @close="open = null"
    >
      <ComponentPanel
        v-if="openRow && open"
        :key="openRow.id"
        :component="openRow"
        :tab="open.tab"
        @changed="reload"
      />
    </SidePanel>
    <SidePanel :open="place !== null" :title="placeTitle" @close="place = null">
      <PlaceForm
        v-if="place?.kind === 'station' && assets.data.value"
        kind="station"
        :system="DEFAULT_SYSTEM"
        :value="assets.data.value.station"
        @done="((place = null), reload())"
        @cancel="place = null"
      />
      <PlaceForm
        v-else-if="place?.kind === 'site' && siteMeta(place.slug)"
        :key="place.slug"
        kind="site"
        :system="DEFAULT_SYSTEM"
        :slug="place.slug"
        :value="siteMeta(place.slug)!"
        @done="((place = null), reload())"
        @cancel="place = null"
      />
    </SidePanel>
  </div>
</template>
