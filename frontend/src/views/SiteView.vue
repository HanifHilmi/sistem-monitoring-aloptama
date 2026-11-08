<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import { api } from '@/api/client'
import type { ActiveAlarm, Assets, ComponentInfo, FlagRow, SystemInfo } from '@/api/types'
import SiteAlarmChip from '@/components/alarms/SiteAlarmChip.vue'
import FlagForm from '@/components/flags/FlagForm.vue'
import SensorBlock from '@/components/SensorBlock.vue'
import SidePanel from '@/components/SidePanel.vue'
import StatusPill from '@/components/StatusPill.vue'
import WindowBar from '@/components/WindowBar.vue'
import { usePolling } from '@/composables/usePolling'
import { useWindowQuery } from '@/composables/useUrlState'
import type { Locale } from '@/i18n'
import { useAuthStore } from '@/stores/auth'
import { useDisplayStore } from '@/stores/display'
import { DEFAULT_SYSTEM, useLiveStore } from '@/stores/live'
import { boardPath } from '@/utils/paths'
import { formatUtc, windowFromPreset } from '@/utils/time'

const props = withDefaults(defineProps<{ code?: string; slug: string }>(), { code: DEFAULT_SYSTEM })
const { t, locale } = useI18n()
const lc = computed(() => locale.value as Locale)
const display = useDisplayStore()
const live = useLiveStore()
const chartWindow = useWindowQuery()
const info = ref<SystemInfo | null>(null)
onMounted(async () => (info.value = await display.system(props.code)))

const site = computed(() => info.value?.sites.find((s) => s.slug === props.slug) ?? null)
// Records and calibration status (R2.5): serial and part numbers only reach signed-in users.
const assets = ref<Assets | null>(null)
onMounted(async () => {
  try {
    assets.value = await api.assets(props.code)
  } catch {
    /* the page works without them */
  }
})
const siteMeta = computed(() => assets.value?.sites.find((s) => s.slug === props.slug)?.meta ?? null)
const record = (type: string) =>
  assets.value?.components.find((c) => c.site === props.slug && c.type === type)
const liveSite = computed(() => live.status?.sites.find((s) => s.slug === props.slug) ?? null)

// Active AWOS alarms at this site (FR-ALM-003, signed-in users only).
const auth = useAuthStore()
const alarms = ref<ActiveAlarm[] | null>(null)
const alarmsAt = ref(Date.now())
async function loadAlarms() {
  if (!auth.canView) return
  const slug = props.slug
  try {
    const found = (await api.activeAlarms(props.code, `site:${slug}`)).active
    if (slug !== props.slug) return // the page moved to another site meanwhile
    alarms.value = found
    alarmsAt.value = Date.now()
  } catch {
    /* the page works without them */
  }
}
// The page stays mounted when moving between sites: never show the previous site's alarms.
watch(
  () => props.slug,
  () => {
    alarms.value = null
    void loadAlarms()
  },
)
const dcp = computed(() => site.value?.components.find((c) => c.is_dcp) ?? null)

// Rolling windows move with time; refresh every 60 s (FR-DSH-011).
const refreshKey = ref(0)
usePolling(() => {
  if (chartWindow.value.preset !== 'custom') chartWindow.value = windowFromPreset(chartWindow.value.preset)
  refreshKey.value++
  void loadAlarms()
}, 60_000)

// ---- flagging from a chart (R2.3, Admins) ----------------------------------------------------------
const flagPanel = ref<
  | { kind: 'new'; component: ComponentInfo; start: string; end: string }
  | { kind: 'edit'; flag: FlagRow }
  | null
>(null)
const flagTitle = computed(() => {
  const p = flagPanel.value
  if (!p) return ''
  return p.kind === 'new' ? t('flags.form.titleNew') : t('flags.form.titleEdit', { id: p.flag.id })
})
async function editFlag(id: number) {
  const flag = (await api.adminFlags(props.code, true)).find((f) => f.id === id)
  if (flag) flagPanel.value = { kind: 'edit', flag }
}
function flagDone() {
  flagPanel.value = null
  refreshKey.value++
}
</script>

<template>
  <div class="flex flex-col gap-4">
    <p v-if="info && !site" class="text-bad" role="alert">{{ t('site.notFound') }}</p>
    <template v-if="site">
      <header class="flex flex-wrap items-end justify-between gap-3">
        <div>
          <RouterLink :to="boardPath(code)" class="eyebrow hover:text-accent"
            >← {{ t('board.title') }}</RouterLink
          >
          <h1 class="text-lg font-semibold">{{ site.name[lc] }}</h1>
          <div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-[0.6875rem] text-ink-3">
            <span class="num">{{ t('live.lastData', { time: formatUtc(liveSite?.last_data_minute) }) }}</span>
            <span v-if="liveSite" class="num">{{
              t('site.componentsValid', { n: liveSite.components_online, total: liveSite.components_total })
            }}</span>
            <span v-if="dcp" class="flex items-center gap-1"
              >DCP <StatusPill :status="live.componentStatus(slug, dcp.type)"
            /></span>
            <SiteAlarmChip
              v-if="alarms?.length"
              :alarms="alarms"
              :info="info"
              :code="code"
              :slug="slug"
              :now="alarmsAt"
            />
            <span v-if="siteMeta && siteMeta.lat !== null && siteMeta.lon !== null" class="num">
              {{ siteMeta.lat.toFixed(4) }}, {{ siteMeta.lon.toFixed(4) }}
              <template v-if="siteMeta.elevation_m !== null">
                · {{ t('records.place.elevationShort', { m: siteMeta.elevation_m }) }}</template
              >
            </span>
          </div>
        </div>
        <WindowBar v-model="chartWindow" />
      </header>

      <div class="grid items-start gap-3 xl:grid-cols-2">
        <SensorBlock
          v-for="c in site.components.filter((x) => !x.is_dcp)"
          :key="c.type"
          :system-code="code"
          :site-slug="slug"
          :component="c"
          :fields="info!.fields"
          :window="chartWindow"
          :status="live.componentStatus(slug, c.type)"
          :refresh-key="refreshKey"
          :record="record(c.type)"
          @flag="(r) => (flagPanel = { kind: 'new', component: c, ...r })"
          @edit-flag="editFlag"
        />
      </div>
      <p class="text-[0.6875rem] text-ink-3">{{ t('sensor.footnote') }}</p>
    </template>

    <SidePanel
      :open="flagPanel !== null"
      :title="flagTitle"
      :subtitle="site?.name[lc]"
      @close="flagPanel = null"
    >
      <FlagForm
        v-if="flagPanel?.kind === 'new'"
        :key="`${flagPanel.component.type}${flagPanel.start}`"
        :system="code"
        :initial="{
          components: [{ site: slug, type: flagPanel.component.type }],
          start: flagPanel.start,
          end: flagPanel.end,
        }"
        @done="flagDone"
        @cancel="flagPanel = null"
      />
      <FlagForm
        v-else-if="flagPanel?.kind === 'edit'"
        :key="flagPanel.flag.id"
        :system="code"
        :flag="flagPanel.flag"
        @done="flagDone"
        @cancel="flagPanel = null"
      />
    </SidePanel>
  </div>
</template>
