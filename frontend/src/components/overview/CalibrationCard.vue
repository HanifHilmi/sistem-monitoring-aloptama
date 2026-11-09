<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import { api } from '@/api/client'
import type { SystemSummary } from '@/api/types'
import { useLoader } from '@/composables/useLoader'
import { usePolling } from '@/composables/usePolling'
import type { Locale } from '@/i18n'
import { useAuthStore } from '@/stores/auth'
import { useDisplayStore } from '@/stores/display'
import { int } from '@/utils/format'
import { addCounts, calibrationCounts, type CalibrationCounts } from '@/utils/overview'

// Every sensor by its calibration status (FR-REG-005), as the site pages show it, and the next date one falls due.
const props = defineProps<{ systems: SystemSummary[] }>()
const { t, locale } = useI18n()
const lc = computed(() => locale.value as Locale)
const display = useDisplayStore()
const auth = useAuthStore()

const data = useLoader(async () => {
  const each = await Promise.all(
    props.systems.map(async (s) => {
      const [assets, info] = await Promise.all([api.assets(s.code), display.system(s.code).catch(() => null)])
      return calibrationCounts(assets, info)
    }),
  )
  return each.reduce<CalibrationCounts>(addCounts, { overdue: 0, due_soon: 0, ok: 0, unknown: 0, next: null })
})
usePolling(() => data.load({ silent: !!data.data.value }), 3_600_000)

const tiles = computed(() => {
  const c = data.data.value
  if (!c) return []
  return [
    { key: 'overdue', n: c.overdue, tone: c.overdue ? 'text-bad' : '' },
    { key: 'due_soon', n: c.due_soon, tone: c.due_soon ? 'text-warn' : '' },
    { key: 'ok', n: c.ok, tone: c.ok ? 'text-ok' : '' },
    { key: 'unknown', n: c.unknown, tone: 'text-ink-3' },
  ]
})
const dateFmt = computed(
  () =>
    new Intl.DateTimeFormat(lc.value === 'id' ? 'id-ID' : 'en-GB', {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
      timeZone: 'UTC',
    }),
)
</script>

<template>
  <section
    class="flex flex-col gap-2.5 rounded-lg border border-line bg-surface p-4"
    data-testid="card-calibration"
  >
    <h2 class="text-sm font-semibold">{{ t('calibration.title') }}</h2>
    <p v-if="data.error.value && !data.data.value" class="text-sm text-warn" role="alert">
      {{ t('common.error') }}
      <button type="button" class="icon-btn" @click="data.load()">{{ t('common.retry') }}</button>
    </p>
    <div v-else-if="!data.data.value" class="h-24 animate-pulse rounded bg-sunken" aria-busy="true" />
    <template v-else>
      <div class="grid grid-cols-4 gap-1.5">
        <p v-for="x in tiles" :key="x.key" class="flex flex-col rounded-md bg-sunken px-2 py-1.5">
          <span class="num text-lg font-semibold" :class="x.tone">{{ int(x.n, lc) }}</span>
          <span class="text-[0.6875rem] leading-tight text-ink-3">{{
            t(`calibration.status.${x.key}`)
          }}</span>
        </p>
      </div>
      <p v-if="data.data.value.next" class="text-[0.8125rem] text-ink-2">
        {{
          t(
            'overview.calibrationCard.next',
            {
              date: dateFmt.format(new Date(`${data.data.value.next.date}T00:00:00Z`)),
              n: data.data.value.next.sensors,
              days: int(data.data.value.next.days, lc),
            },
            data.data.value.next.sensors,
          )
        }}
      </p>
      <p v-else class="text-[0.8125rem] text-ink-3">{{ t('overview.calibrationCard.none') }}</p>
      <p class="text-[0.6875rem] text-ink-3">{{ t('calibration.dcp') }}</p>
      <RouterLink
        v-if="auth.isAdmin"
        to="/admin/calibration"
        class="mt-auto text-[0.8125rem] text-accent hover:underline"
        >{{ t('overview.calibrationCard.open') }} →</RouterLink
      >
    </template>
  </section>
</template>
