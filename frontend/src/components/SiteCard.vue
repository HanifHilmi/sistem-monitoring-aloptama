<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import type { Availability, SiteInfo, StatusResponse } from '@/api/types'
import type { Locale } from '@/i18n'
import { useDisplayStore } from '@/stores/display'
import { formatInt, formatPct, LEVEL_TEXT, levelFor } from '@/utils/format'
import StatusChip from './StatusChip.vue'

const props = defineProps<{
  systemCode: string
  site: SiteInfo
  availability: Availability | null
  live: StatusResponse['sites'][number] | null
}>()
const { t, locale } = useI18n()
const display = useDisplayStore()
const lc = computed(() => locale.value as Locale)
const name = computed(() => props.site.name[lc.value])
</script>

<template>
  <RouterLink
    :to="`/systems/${systemCode}/sites/${site.slug}`"
    class="panel block transition-colors hover:border-accent"
    :aria-label="t('site.open', { site: name })"
  >
    <div class="flex items-baseline justify-between gap-2">
      <h3 class="font-semibold">{{ name }}</h3>
      <span
        class="text-xl font-bold tabular-nums"
        :class="LEVEL_TEXT[levelFor(availability?.pct, display.thresholds)]"
        :title="
          availability
            ? t('common.validOfExpected', {
                valid: formatInt(availability.valid, lc),
                expected: formatInt(availability.expected, lc),
              })
            : undefined
        "
      >
        {{ formatPct(availability?.pct, lc) }}
      </span>
    </div>
    <p class="mb-2 text-xs text-muted">
      {{ t('site.availability') }}
      <template v-if="live">
        · {{ t('site.componentsValid', { n: live.components_online, total: live.components_total }) }}
      </template>
    </p>
    <ul class="flex flex-wrap gap-1">
      <li v-for="c in site.components" :key="c.type">
        <StatusChip
          :status="live?.components.find((x) => x.type === c.type)?.status ?? 'unknown'"
          :label="c.type"
        />
      </li>
    </ul>
  </RouterLink>
</template>
