<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useLiveStore } from '@/stores/live'

// The Problems button (FR-DSH-010), always in the top bar. A system's live state sits at the top of its menu
// (SystemStatus); the wall screen has no menus, so there ("compact") the CDPs and valid components show here too.
defineProps<{ compact?: boolean }>()
const emit = defineEmits<{ problems: [] }>()
const live = useLiveStore()
const { t } = useI18n()

const DOT: Record<string, string> = {
  producing: 'bg-ok',
  not_producing: 'bg-bad',
  unknown: 'bg-ink-3',
  reachable: 'bg-ok',
  degraded: 'bg-warn',
  unreachable: 'bg-bad',
}
const problemTone = computed(() =>
  !live.problems.length
    ? 'text-ink-2'
    : live.worst === 'critical' || live.worst === 'major'
      ? 'border-bad/50 bg-bad/10 text-bad'
      : 'border-warn/50 bg-warn/10 text-warn',
)
</script>

<template>
  <div class="flex min-w-0 items-center gap-3 text-xs text-ink-2">
    <template v-if="compact && live.status">
      <span
        v-for="c in live.status.cdps"
        :key="c.code"
        class="hidden items-center gap-1.5 md:flex"
        :title="`${t(`cdp.flow.${c.data_flow}`)} · ${t(`cdp.reach.${c.reachability}`)}`"
      >
        <span class="h-2 w-2 rounded-full" :class="DOT[c.data_flow]" aria-hidden="true" />
        <span class="num">{{ c.code }}</span>
        <span class="sr-only">{{ t(`cdp.flow.${c.data_flow}`) }}</span>
      </span>
      <span class="hidden items-center gap-1 lg:flex" :title="t('live.componentsTitle')">
        <span class="num">{{ live.componentsValid }}/{{ live.componentsTotal }}</span>
        <span>{{ t('live.components') }}</span>
      </span>
    </template>
    <span v-else-if="live.error" class="text-warn">{{ t('live.unavailable') }}</span>
    <button
      type="button"
      class="inline-flex items-center gap-1.5 rounded-md border border-line px-2 py-1 font-medium"
      :class="problemTone"
      :aria-label="t('problems.open')"
      @click="emit('problems')"
    >
      <span aria-hidden="true">{{ live.problems.length ? '●' : '✓' }}</span>
      {{ live.problems.length ? t('problems.count', live.problems.length) : t('problems.none') }}
    </button>
  </div>
</template>
