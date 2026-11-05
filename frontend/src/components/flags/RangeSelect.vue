<script setup lang="ts">
import { computed, ref } from 'vue'

// Drag across a time axis to pick a range (Admins flagging data). Lies over the plot area of a chart: the host
// places it with the chart's own padding. Times snap to whole minutes; the end is exclusive.
const props = defineProps<{ from: number; to: number; label: string }>()
const model = defineModel<[number, number] | null>({ required: true })
const el = ref<HTMLElement | null>(null)
let anchor: number | null = null

function at(e: PointerEvent): number {
  const r = el.value!.getBoundingClientRect()
  const x = Math.min(Math.max(e.clientX - r.left, 0), r.width)
  const t = props.from + (x / Math.max(1, r.width)) * (props.to - props.from)
  return Math.min(props.to, Math.max(props.from, Math.round(t / 60_000) * 60_000))
}
function down(e: PointerEvent) {
  anchor = at(e)
  el.value?.setPointerCapture(e.pointerId)
  model.value = null
}
function move(e: PointerEvent) {
  if (anchor === null) return
  const t = at(e)
  model.value = t === anchor ? null : [Math.min(anchor, t), Math.max(anchor, t)]
}
function up() {
  anchor = null
}
const box = computed(() => {
  if (!model.value) return null
  const span = Math.max(1, props.to - props.from)
  return {
    left: `${((model.value[0] - props.from) / span) * 100}%`,
    width: `${((model.value[1] - model.value[0]) / span) * 100}%`,
  }
})
</script>

<template>
  <div
    ref="el"
    class="absolute cursor-crosshair touch-none select-none"
    role="application"
    :aria-label="label"
    @pointerdown.prevent="down"
    @pointermove="move"
    @pointerup="up"
    @pointercancel="up"
  >
    <span v-if="box" class="absolute inset-y-0 border-x-2 border-flag bg-flag/20" :style="box" />
  </div>
</template>
