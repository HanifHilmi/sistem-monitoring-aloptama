<script setup lang="ts">
import { computed } from 'vue'

// The report's own name: METAR, MET REPORT and TAF plain; SPECI, SPECIAL and a TAF amendment or correction marked.
const props = defineProps<{ kind: string }>()
const special = computed(() => /^(SPECI|SPECIAL|TAF (AMD|COR))$/.test(props.kind))
</script>

<template>
  <span
    class="num inline-flex shrink-0 items-center rounded px-1.5 py-px text-[0.6875rem] font-semibold whitespace-nowrap"
    :class="special ? 'bg-warn/15 text-ink' : 'bg-sunken text-ink-2'"
    data-testid="report-kind"
    >{{ kind }}</span
  >
</template>
