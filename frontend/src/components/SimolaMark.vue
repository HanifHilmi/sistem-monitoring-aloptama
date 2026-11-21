<script setup lang="ts">
// The SIMOLA mark for small places such as the top bar (docs/brand/simola-mark-mono.svg): the letter S lit up in a
// 5 × 7 grid of status cells, the way the board shows availability minute by minute, in the current text colour.
// Decorative: put the name next to it in text.
const S = ['.###.', '#...#', '#....', '.###.', '....#', '#...#', '.###.']
const lit = S.flatMap((row, r) =>
  [...row].flatMap((kind, c) => (kind === '#' ? [{ key: `${r}-${c}`, r, c }] : [])),
)
</script>

<template>
  <svg viewBox="12 4 40 56" aria-hidden="true" focusable="false">
    <rect
      v-for="x in lit"
      :key="x.key"
      :x="(13.5 + 7.7 * x.c).toFixed(2)"
      :y="(5.8 + 7.7 * x.r).toFixed(2)"
      width="6.2"
      height="6.2"
      rx="1.6"
      fill="currentColor"
    />
  </svg>
</template>
