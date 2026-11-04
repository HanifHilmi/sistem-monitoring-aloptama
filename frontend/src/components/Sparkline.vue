<script setup lang="ts">
import { computed } from 'vue'

// Minimal inline trend line. Gaps (null) break the line. Decorative: values are always shown as text nearby.
const props = withDefaults(
  defineProps<{
    values: (number | null)[]
    width?: number
    height?: number
    min?: number
    max?: number
    /** smallest vertical range drawn, so tiny wobbles stay small (anchored at the top value) */
    minSpan?: number
  }>(),
  { width: 96, height: 22, min: undefined, max: undefined, minSpan: 0 },
)

const paths = computed(() => {
  const vals = props.values
  const nums = vals.filter((v): v is number => v !== null && Number.isFinite(v))
  if (nums.length < 2) return [] as string[]
  const hi = props.max ?? Math.max(...nums)
  const lo = Math.min(props.min ?? Math.min(...nums), hi - props.minSpan)
  const span = hi - lo || 1
  const step = vals.length > 1 ? (props.width - 2) / (vals.length - 1) : 0
  const segs: string[] = []
  let cur = ''
  vals.forEach((v, i) => {
    if (v === null || !Number.isFinite(v)) {
      if (cur) segs.push(cur)
      cur = ''
      return
    }
    const x = 1 + i * step
    const y = 1 + (props.height - 2) * (1 - (v - lo) / span)
    cur += `${cur ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)}`
  })
  if (cur) segs.push(cur)
  return segs
})
</script>

<template>
  <svg
    :width="width"
    :height="height"
    :viewBox="`0 0 ${width} ${height}`"
    aria-hidden="true"
    class="overflow-visible"
  >
    <path
      v-for="(d, i) in paths"
      :key="i"
      :d="d"
      fill="none"
      stroke="currentColor"
      stroke-width="1.5"
      stroke-linejoin="round"
      stroke-linecap="round"
    />
  </svg>
</template>
