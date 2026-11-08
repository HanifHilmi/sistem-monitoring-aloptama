<script setup lang="ts">
import { nextTick, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'

// A panel that opens under its trigger. The panel is drawn at the top level of the page (fixed, above everything
// else), so no card, chart or blurred top bar can cover it. It closes on a click outside, Escape, tabbing out of
// it, and when the page changes.
defineOptions({ inheritAttrs: false })
const props = withDefaults(
  defineProps<{ align?: 'left' | 'right'; role?: 'menu' | 'dialog'; label?: string; panelClass?: string }>(),
  { align: 'left', role: 'menu', label: undefined, panelClass: '' },
)
const open = defineModel<boolean>('open', { default: false })
const route = useRoute()
const anchor = ref<HTMLElement | null>(null)
const panel = ref<HTMLElement | null>(null)
const style = ref<Record<string, string>>({ visibility: 'hidden' })
const GAP = 6
const EDGE = 8

function place() {
  const a = anchor.value?.getBoundingClientRect()
  const p = panel.value
  if (!a || !p) return
  const w = p.offsetWidth
  const wanted = props.align === 'right' ? a.right - w : a.left
  const left = Math.max(EDGE, Math.min(wanted, window.innerWidth - w - EDGE))
  style.value = { top: `${a.bottom + GAP}px`, left: `${left}px` }
}
function close(focusTrigger = false) {
  open.value = false
  if (focusTrigger) anchor.value?.querySelector<HTMLElement>('button, a')?.focus()
}
function onPointer(e: PointerEvent) {
  const target = e.target as Node
  if (!anchor.value?.contains(target) && !panel.value?.contains(target)) close()
}
function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') close(true)
}
function onFocusOut(e: FocusEvent) {
  const to = e.relatedTarget as Node | null
  if (to && !panel.value?.contains(to) && !anchor.value?.contains(to)) close()
}
function listen(on: boolean) {
  if (on) {
    document.addEventListener('pointerdown', onPointer)
    document.addEventListener('keydown', onKey)
    window.addEventListener('resize', place)
    window.addEventListener('scroll', place, true)
  } else {
    document.removeEventListener('pointerdown', onPointer)
    document.removeEventListener('keydown', onKey)
    window.removeEventListener('resize', place)
    window.removeEventListener('scroll', place, true)
  }
}
watch(open, async (v) => {
  listen(v)
  if (!v) {
    style.value = { visibility: 'hidden' }
    return
  }
  await nextTick()
  place()
})
watch(
  () => route.fullPath,
  () => close(),
)
onUnmounted(() => listen(false))

/** Opens or closes; opened from the keyboard, the first item in the panel takes the focus. */
async function toggle(e?: MouseEvent) {
  open.value = !open.value
  if (open.value && e?.detail === 0) {
    await nextTick()
    panel.value?.querySelector<HTMLElement>('a[href], button:not([disabled]), [tabindex="0"]')?.focus()
  }
}
</script>

<template>
  <div ref="anchor" class="relative" v-bind="$attrs">
    <slot name="trigger" :open="open" :toggle="toggle" />
  </div>
  <Teleport to="body">
    <div
      v-if="open"
      ref="panel"
      :role="role"
      :aria-label="label"
      class="fixed z-50 rounded-lg border border-line bg-surface shadow-lg"
      :class="panelClass"
      :style="style"
      @focusout="onFocusOut"
    >
      <slot :close="close" />
    </div>
  </Teleport>
</template>
