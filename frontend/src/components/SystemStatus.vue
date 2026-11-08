<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { useLiveStore } from '@/stores/live'
import { formatUtc } from '@/utils/time'

// A system's live state (FR-DSH-003): each CDP's data flow, the components with valid data now, and the last data
// minute. Shown at the top of the system's menu; the menu button carries the overall colour (systemTone).
const live = useLiveStore()
const { t } = useI18n()
const DOT: Record<string, string> = {
  producing: 'bg-ok',
  not_producing: 'bg-bad',
  unknown: 'bg-ink-3',
}
</script>

<template>
  <div v-if="live.status" class="flex flex-col gap-1 text-xs text-ink-2" data-testid="system-status">
    <p class="flex flex-wrap items-center gap-x-3 gap-y-1">
      <span
        v-for="c in live.status.cdps"
        :key="c.code"
        class="flex items-center gap-1.5"
        :title="`${t(`cdp.flow.${c.data_flow}`)} · ${t(`cdp.reach.${c.reachability}`)}`"
      >
        <span class="h-2 w-2 rounded-full" :class="DOT[c.data_flow] ?? 'bg-ink-3'" aria-hidden="true" />
        <span class="num">{{ c.code }}</span>
        <span class="sr-only">{{ t(`cdp.flow.${c.data_flow}`) }}</span>
      </span>
      <span class="flex items-center gap-1" :title="t('live.componentsTitle')">
        <span class="num">{{ live.componentsValid }}/{{ live.componentsTotal }}</span>
        <span>{{ t('live.components') }}</span>
      </span>
    </p>
    <p class="num text-[0.6875rem] text-ink-3">
      {{ t('live.lastData', { time: formatUtc(live.status.last_data_minute) }) }}
    </p>
  </div>
  <p v-else-if="live.error" class="text-xs text-warn">{{ t('live.unavailable') }}</p>
</template>
