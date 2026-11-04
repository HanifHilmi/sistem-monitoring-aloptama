<script setup lang="ts">
import { computed } from 'vue'

// Status vocabulary (UX-002): colour plus icon plus text, never colour alone (UX-005).
const props = defineProps<{ status: string; label: string; compact?: boolean }>()

const STYLE: Record<string, { cls: string; icon: string }> = {
  valid: { cls: 'text-good border-good/40 bg-good/10', icon: '✓' },
  producing: { cls: 'text-good border-good/40 bg-good/10', icon: '✓' },
  reachable: { cls: 'text-good border-good/40 bg-good/10', icon: '✓' },
  field_missing: { cls: 'text-warn border-warn/40 bg-warn/10', icon: '!' },
  degraded: { cls: 'text-warn border-warn/40 bg-warn/10', icon: '!' },
  no_data: { cls: 'text-bad border-bad/40 bg-bad/10', icon: '✕' },
  not_producing: { cls: 'text-bad border-bad/40 bg-bad/10', icon: '✕' },
  unreachable: { cls: 'text-bad border-bad/40 bg-bad/10', icon: '✕' },
  stale: { cls: 'text-neutral border-neutral/40 bg-neutral/10', icon: '◷' },
  not_in_service: { cls: 'text-neutral border-neutral/40 bg-neutral/10', icon: '–' },
  no_coverage: { cls: 'text-neutral border-neutral/40 bg-neutral/10', icon: '–' },
  unknown: { cls: 'text-neutral border-neutral/40 bg-neutral/10', icon: '?' },
}

const style = computed(() => STYLE[props.status] ?? STYLE.unknown!)
</script>

<template>
  <span
    class="inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-xs font-medium whitespace-nowrap"
    :class="style.cls"
  >
    <span aria-hidden="true">{{ style.icon }}</span>
    <span :class="compact ? 'sr-only' : ''">{{ label }}</span>
  </span>
</template>
