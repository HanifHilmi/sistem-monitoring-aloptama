<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { MatrixResponse, MatrixRow } from '@/api/types'
import type { Locale } from '@/i18n'
import { useDisplayStore } from '@/stores/display'
import { int, LEVEL_BG, level, pct } from '@/utils/format'

// A list view of matrix cells: either one row across all periods ("days of RWY 04 ATRH"), or every row of
// a group for one period ("RWY 04 components on 3 Nov"). Large rows suit phones and keyboard users.
const props = defineProps<{
  matrix: MatrixResponse
  rows: { row: MatrixRow; label: string }[]
  col?: number | null
  colLabel: (i: number) => string
}>()
const emit = defineEmits<{ pick: [MatrixRow, number] }>()
const { t, locale } = useI18n()
const lc = computed(() => locale.value as Locale)
const display = useDisplayStore()

const items = computed(() => {
  if (props.col !== null && props.col !== undefined) {
    const col = props.col
    return props.rows.map(({ row, label }) => ({ row, col, label, cell: row.cells[col]! }))
  }
  const only = props.rows[0]
  if (!only) return []
  return only.row.cells.map((cell, col) => ({ row: only.row, col, label: props.colLabel(col), cell }))
})
</script>

<template>
  <ul class="flex flex-col">
    <li v-for="it in items" :key="`${it.row.key}-${it.col}`">
      <button
        type="button"
        class="flex w-full items-center gap-3 border-b border-line px-1 py-2 text-left text-sm hover:bg-sunken disabled:cursor-default disabled:hover:bg-transparent"
        :disabled="it.cell.pct === null"
        @click="emit('pick', it.row, it.col)"
      >
        <span
          class="h-3.5 w-3.5 shrink-0 rounded-[2px]"
          :class="LEVEL_BG[level(it.cell.expected === 0 ? null : it.cell.pct, display.thresholds)]"
        />
        <span class="min-w-0 flex-1 truncate">{{ it.label }}</span>
        <span class="num w-16 text-right">{{
          it.cell.pct === null ? t('board.noCoverage') : pct(it.cell.pct, lc)
        }}</span>
        <span class="num w-24 text-right text-xs whitespace-nowrap text-ink-3">
          {{ it.cell.missing ? t('board.missing', { n: int(it.cell.missing, lc) }) : '' }}
        </span>
      </button>
    </li>
  </ul>
</template>
