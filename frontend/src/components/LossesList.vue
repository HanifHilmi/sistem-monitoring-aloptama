<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { MatrixRow, SystemInfo } from '@/api/types'
import type { Locale } from '@/i18n'
import { int, pct } from '@/utils/format'

// Where the period's minutes were lost, largest first (components and CDPs).
const props = defineProps<{ rows: MatrixRow[]; info: SystemInfo; limit?: number }>()
const emit = defineEmits<{ pick: [MatrixRow] }>()
const { t, locale } = useI18n()
const lc = computed(() => locale.value as Locale)

const items = computed(() => {
  const list = props.rows
    .filter((r) => (r.kind === 'component' || r.kind === 'cdp') && (r.total.missing ?? 0) > 0)
    .sort((a, b) => (b.total.missing ?? 0) - (a.total.missing ?? 0))
    .slice(0, props.limit ?? 8)
  const max = Math.max(1, ...list.map((r) => r.total.missing ?? 0))
  return list.map((r) => ({ row: r, share: (r.total.missing ?? 0) / max }))
})

function label(r: MatrixRow): string {
  if (r.kind === 'cdp') return r.cdp ?? ''
  const site = props.info.sites.find((s) => s.slug === r.site)
  return `${site?.name[lc.value] ?? r.site} · ${r.type}`
}
</script>

<template>
  <section :aria-label="t('board.losses')">
    <h2 class="eyebrow mb-2">{{ t('board.losses') }}</h2>
    <p v-if="!items.length" class="text-xs text-ink-3">{{ t('board.noLosses') }}</p>
    <ol class="flex flex-col">
      <li v-for="(it, i) in items" :key="it.row.key">
        <button
          type="button"
          class="group flex w-full flex-col gap-1 border-b border-line py-1.5 text-left hover:bg-sunken"
          @click="emit('pick', it.row)"
        >
          <span class="flex items-baseline gap-2 text-xs">
            <span class="num w-4 text-ink-3">{{ i + 1 }}</span>
            <span class="min-w-0 flex-1 truncate group-hover:text-accent">{{ label(it.row) }}</span>
            <span class="num text-ink-2">{{ int(it.row.total.missing, lc) }}</span>
          </span>
          <span class="ml-6 flex items-center gap-2">
            <span class="h-1 flex-1 overflow-hidden rounded-full bg-sunken">
              <span
                class="block h-full rounded-full bg-bad/70"
                :style="{ width: `${Math.max(4, it.share * 100)}%` }"
              />
            </span>
            <span class="num w-12 text-right text-[0.6875rem] text-ink-3">{{
              pct(it.row.total.pct, lc)
            }}</span>
          </span>
        </button>
      </li>
    </ol>
  </section>
</template>
