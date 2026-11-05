<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import type { WindSummary } from '@/api/types'
import type { Locale } from '@/i18n'
import { int, num } from '@/utils/format'
import { formatUtc } from '@/utils/time'
import { compassPoint, duration } from '@/utils/weather'

// Gusts as events (unbroken minutes with a gust): how many, the strongest and when, then each event.
const props = defineProps<{ wind: WindSummary }>()
const { t, locale } = useI18n()
const lc = computed(() => locale.value as Locale)
const g = computed(() => props.wind.gust)
const events = computed(() => [...(g.value.events ?? [])].reverse()) // newest first
const showAll = ref(false)
const shown = computed(() => (showAll.value ? events.value : events.value.slice(0, 5)))
const dir = (d: number | null) => (d === null ? '—' : `${num(d, lc.value, 0)}° ${compassPoint(d)}`)
</script>

<template>
  <section class="border-t border-line px-3 py-2.5" :aria-label="t('gust.title')">
    <h4 class="text-xs font-semibold">{{ t('gust.title') }}</h4>
    <p v-if="!g.event_count" class="mt-1 text-xs text-ink-3">{{ t('gust.none') }}</p>
    <template v-else>
      <dl class="mt-1.5 grid grid-cols-2 gap-2 text-xs sm:max-w-md">
        <div class="rounded-md bg-sunken px-2.5 py-1.5">
          <dt class="text-[0.6875rem] text-ink-3">{{ t('gust.events') }}</dt>
          <dd class="num text-base font-semibold">{{ int(g.event_count, lc) }}</dd>
          <dd class="text-[0.6875rem] text-ink-3">
            {{ t('gust.total', { d: duration(g.minutes ?? 0, t) }) }}
          </dd>
        </div>
        <div v-if="g.strongest" class="rounded-md bg-sunken px-2.5 py-1.5">
          <dt class="text-[0.6875rem] text-ink-3">{{ t('gust.strongest') }}</dt>
          <dd class="num text-base font-semibold">
            {{
              t('gust.speedFrom', { kt: num(g.strongest.max_kt, lc, 0), dir: dir(g.strongest.direction_deg) })
            }}
          </dd>
          <dd class="num text-[0.6875rem] text-ink-3">{{ formatUtc(g.strongest.start) }}</dd>
        </div>
      </dl>
      <table class="num mt-2 w-full text-xs sm:max-w-md">
        <thead class="text-[0.625rem] text-ink-3">
          <tr>
            <th class="py-1 text-left font-normal">{{ t('gust.when') }}</th>
            <th class="text-right font-normal">{{ t('gust.lasted') }}</th>
            <th class="text-right font-normal">{{ t('gust.max') }}</th>
            <th class="text-right font-normal">{{ t('gust.from') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="e in shown" :key="e.start" class="border-t border-line">
            <td class="py-1">{{ formatUtc(e.start) }}</td>
            <td class="text-right">{{ duration(e.minutes, t) }}</td>
            <td class="text-right font-medium">{{ num(e.max_kt, lc, 0) }} kt</td>
            <td class="text-right">{{ dir(e.direction_deg) }}</td>
          </tr>
        </tbody>
      </table>
      <button
        v-if="events.length > 5"
        type="button"
        class="icon-btn mt-1.5 text-xs"
        @click="showAll = !showAll"
      >
        {{ showAll ? t('gust.fewer') : t('gust.all', { n: int(events.length, lc) }) }}
      </button>
    </template>
  </section>
</template>
