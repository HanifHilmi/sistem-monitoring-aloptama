<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import type { SystemInfo } from '@/api/types'
import SensorBlock from '@/components/SensorBlock.vue'
import StatusPill from '@/components/StatusPill.vue'
import WindowBar from '@/components/WindowBar.vue'
import { usePolling } from '@/composables/usePolling'
import { useWindowQuery } from '@/composables/useUrlState'
import type { Locale } from '@/i18n'
import { useDisplayStore } from '@/stores/display'
import { useLiveStore } from '@/stores/live'
import { formatUtc, windowFromPreset } from '@/utils/time'

const props = defineProps<{ slug: string }>()
const { t, locale } = useI18n()
const lc = computed(() => locale.value as Locale)
const display = useDisplayStore()
const live = useLiveStore()
const chartWindow = useWindowQuery()
const info = ref<SystemInfo | null>(null)
onMounted(async () => (info.value = await display.system(live.systemCode)))

const site = computed(() => info.value?.sites.find((s) => s.slug === props.slug) ?? null)
const liveSite = computed(() => live.status?.sites.find((s) => s.slug === props.slug) ?? null)
const dcp = computed(() => site.value?.components.find((c) => c.is_dcp) ?? null)

// Rolling windows move with time; refresh every 60 s (FR-DSH-011).
const refreshKey = ref(0)
usePolling(() => {
  if (chartWindow.value.preset !== 'custom') chartWindow.value = windowFromPreset(chartWindow.value.preset)
  refreshKey.value++
}, 60_000)
</script>

<template>
  <div class="flex flex-col gap-4">
    <p v-if="info && !site" class="text-bad" role="alert">{{ t('site.notFound') }}</p>
    <template v-if="site">
      <header class="flex flex-wrap items-end justify-between gap-3">
        <div>
          <RouterLink to="/" class="eyebrow hover:text-accent">← {{ t('board.title') }}</RouterLink>
          <h1 class="text-lg font-semibold">{{ site.name[lc] }}</h1>
          <p class="flex flex-wrap items-center gap-x-3 gap-y-1 text-[0.6875rem] text-ink-3">
            <span class="num">{{ t('live.lastData', { time: formatUtc(liveSite?.last_data_minute) }) }}</span>
            <span v-if="liveSite" class="num">{{
              t('site.componentsValid', { n: liveSite.components_online, total: liveSite.components_total })
            }}</span>
            <span v-if="dcp" class="flex items-center gap-1"
              >DCP <StatusPill :status="live.componentStatus(slug, dcp.type)"
            /></span>
          </p>
        </div>
        <WindowBar v-model="chartWindow" />
      </header>

      <div class="grid items-start gap-3 xl:grid-cols-2">
        <SensorBlock
          v-for="c in site.components.filter((x) => !x.is_dcp)"
          :key="c.type"
          :system-code="live.systemCode"
          :site-slug="slug"
          :component="c"
          :fields="info!.fields"
          :window="chartWindow"
          :status="live.componentStatus(slug, c.type)"
          :refresh-key="refreshKey"
        />
      </div>
      <p class="text-[0.6875rem] text-ink-3">{{ t('sensor.footnote') }}</p>
    </template>
  </div>
</template>
