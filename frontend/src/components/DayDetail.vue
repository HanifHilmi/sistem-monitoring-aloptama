<script setup lang="ts">
import { computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import { api } from '@/api/client'
import type { MinutesResponse } from '@/api/types'
import { useLoader } from '@/composables/useLoader'
import type { Locale } from '@/i18n'
import { int, pct } from '@/utils/format'

// Minute-by-minute explanation of one day for one scope (FR-DSH-009): every lost minute and its cause.
const props = defineProps<{ systemCode: string; scope: string; day: string; siteLink?: string | null }>()
const { t, locale } = useI18n()
const lc = computed(() => locale.value as Locale)

const loader = useLoader<MinutesResponse>(() => api.minutes(props.systemCode, props.day, props.scope))
watch(
  () => `${props.scope}|${props.day}`,
  () => loader.load(),
  { immediate: true },
)

const CODE_CLASS: Record<string, string> = { v: 'bg-full', f: 'bg-warn', n: 'bg-bad', u: 'bg-empty' }
const hours = computed(() => {
  const codes = loader.data.value?.codes ?? ''
  return Array.from({ length: 24 }, (_, h) => codes.slice(h * 60, h * 60 + 60))
})
const p = computed(() => {
  const d = loader.data.value
  return d && d.expected > 0 ? Math.round((d.valid / d.expected) * 10000) / 100 : null
})
const hhmm = (iso: string) => iso.slice(11, 16)
const dayEnd = (iso: string) => (iso.slice(11, 16) === '00:00' ? '24:00' : hhmm(iso))
</script>

<template>
  <div class="flex flex-col gap-4">
    <p v-if="loader.error.value" class="text-sm text-warn" role="alert">
      {{ t('common.error') }}
      <button type="button" class="icon-btn" @click="loader.load()">{{ t('common.retry') }}</button>
    </p>
    <div v-else-if="!loader.data.value" class="h-64 animate-pulse rounded-md bg-sunken" aria-busy="true" />
    <template v-else>
      <dl class="grid grid-cols-3 gap-px overflow-hidden rounded-md border border-line bg-line text-xs">
        <div class="bg-surface p-2">
          <dt class="text-ink-3">{{ t('day.availability') }}</dt>
          <dd class="num text-lg font-semibold">
            {{ pct(p, lc) }}<span class="text-xs text-ink-3"> %</span>
          </dd>
        </div>
        <div class="bg-surface p-2">
          <dt class="text-ink-3">{{ t('day.validMinutes') }}</dt>
          <dd class="num text-lg font-semibold">
            {{ int(loader.data.value.valid, lc)
            }}<span class="text-xs text-ink-3"> / {{ int(loader.data.value.expected, lc) }}</span>
          </dd>
        </div>
        <div class="bg-surface p-2">
          <dt class="text-ink-3">{{ t('day.lostMinutes') }}</dt>
          <dd class="num text-lg font-semibold">
            {{ int(loader.data.value.expected - loader.data.value.valid, lc) }}
          </dd>
        </div>
      </dl>

      <figure>
        <figcaption class="eyebrow mb-1.5">{{ t('day.minuteMap') }}</figcaption>
        <div class="flex flex-col gap-[2px]" role="img" :aria-label="t('day.minuteMapLabel')">
          <div v-for="(row, h) in hours" :key="h" class="flex items-center gap-1.5">
            <span class="num w-6 text-right text-[0.625rem] text-ink-3">{{
              String(h).padStart(2, '0')
            }}</span>
            <span class="grid flex-1 gap-px" style="grid-template-columns: repeat(60, minmax(0, 1fr))">
              <span v-for="(c, m) in row" :key="m" class="h-2.5 rounded-[1px]" :class="CODE_CLASS[c]" />
            </span>
          </div>
        </div>
        <div class="mt-2 flex flex-wrap gap-3 text-[0.6875rem] text-ink-2">
          <span class="flex items-center gap-1"
            ><span class="h-2.5 w-2.5 rounded-[1px] bg-full" />{{ t('day.code.v') }}</span
          >
          <span class="flex items-center gap-1"
            ><span class="h-2.5 w-2.5 rounded-[1px] bg-warn" />{{ t('day.code.f') }}</span
          >
          <span class="flex items-center gap-1"
            ><span class="h-2.5 w-2.5 rounded-[1px] bg-bad" />{{ t('day.code.n') }}</span
          >
          <span class="flex items-center gap-1"
            ><span class="h-2.5 w-2.5 rounded-[1px] border border-line bg-empty" />{{ t('day.code.u') }}</span
          >
        </div>
      </figure>

      <section>
        <h3 class="eyebrow mb-1.5">{{ t('day.intervals') }}</h3>
        <p v-if="!loader.data.value.intervals.length" class="text-xs text-ok">{{ t('day.noIntervals') }}</p>
        <table v-else class="w-full text-xs">
          <thead class="text-left text-ink-3">
            <tr>
              <th class="py-1 font-normal">{{ t('day.from') }}</th>
              <th class="font-normal">{{ t('day.to') }}</th>
              <th class="text-right font-normal">{{ t('day.minutes') }}</th>
              <th class="pl-3 font-normal">{{ t('day.cause') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(iv, i) in loader.data.value.intervals.slice(0, 30)"
              :key="i"
              class="border-t border-line"
            >
              <td class="num py-1">{{ hhmm(iv.start) }}</td>
              <td class="num">{{ dayEnd(iv.end) }}</td>
              <td class="num text-right">{{ iv.minutes }}</td>
              <td class="pl-3">
                <span
                  class="mr-1 inline-block h-2 w-2 rounded-[1px]"
                  :class="iv.cause === 'field_missing' ? 'bg-warn' : 'bg-bad'"
                />
                {{ t(`day.causeName.${iv.cause}`) }}
              </td>
            </tr>
          </tbody>
        </table>
        <p v-if="loader.data.value.intervals.length > 30" class="mt-1 text-[0.6875rem] text-ink-3">
          {{ t('day.more', { n: loader.data.value.intervals.length - 30 }) }}
        </p>
      </section>
      <p class="text-[0.6875rem] text-ink-3">{{ t('common.allUtc') }}</p>
      <RouterLink v-if="siteLink" :to="siteLink" class="text-xs text-accent hover:underline"
        >{{ t('day.openCharts') }} →</RouterLink
      >
    </template>
  </div>
</template>
