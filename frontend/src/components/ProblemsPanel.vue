<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import type { Problem } from '@/api/types'
import { useProblemsStore } from '@/stores/problems'
import { formatUtc } from '@/utils/time'

const store = useProblemsStore()
const { t } = useI18n()
const open = ref(false)

const worst = computed(() => store.problems[0]?.severity)
const badgeClass = computed(() => {
  if (!store.problems.length) return 'border-good/40 text-good'
  if (worst.value === 'critical' || worst.value === 'major') return 'border-bad/60 bg-bad/15 text-bad'
  return 'border-warn/50 bg-warn/10 text-warn'
})

const SEVERITY_ICON: Record<string, string> = { critical: '⛔', major: '✕', minor: '!', info: 'i' }

function message(p: Problem): string {
  const params: Record<string, string | number> = {}
  for (const [k, v] of Object.entries(p.params)) {
    if (v !== null && v !== undefined) params[k === 'lag_min' ? 'lag' : k] = v
  }
  return t(`problems.code.${p.code}`, params)
}
</script>

<template>
  <div>
    <button
      type="button"
      class="inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-sm font-medium"
      :class="badgeClass"
      :aria-expanded="open"
      aria-controls="problems-panel"
      @click="open = !open"
    >
      <span aria-hidden="true">{{ store.problems.length ? '!' : '✓' }}</span>
      {{ store.problems.length ? t('problems.count', store.problems.length) : t('problems.title') }}
    </button>

    <div v-if="open" class="fixed inset-0 z-40 bg-black/50" aria-hidden="true" @click="open = false" />
    <aside
      v-if="open"
      id="problems-panel"
      class="fixed top-0 right-0 z-50 flex h-full w-full max-w-md flex-col border-l border-border bg-bg"
      role="dialog"
      aria-modal="true"
      :aria-label="t('problems.title')"
    >
      <header class="flex items-center justify-between border-b border-border p-4">
        <h2 class="text-lg font-semibold">{{ t('problems.title') }}</h2>
        <button type="button" class="btn-ghost" @click="open = false">{{ t('common.close') }}</button>
      </header>
      <div class="flex-1 overflow-y-auto p-4">
        <p v-if="store.error" class="mb-3 text-sm text-warn" role="alert">{{ t('common.error') }}</p>
        <p v-if="!store.problems.length" class="text-sm text-good">✓ {{ t('problems.none') }}</p>
        <ul class="space-y-2">
          <li v-for="(p, i) in store.problems" :key="i" class="panel flex gap-3 p-3">
            <span
              aria-hidden="true"
              class="mt-0.5 text-sm"
              :class="p.severity === 'minor' || p.severity === 'info' ? 'text-warn' : 'text-bad'"
            >
              {{ SEVERITY_ICON[p.severity] }}
            </span>
            <div class="min-w-0 flex-1">
              <p class="text-xs text-muted">{{ t(`problems.severity.${p.severity}`) }}</p>
              <RouterLink :to="p.link" class="text-sm font-medium hover:underline" @click="open = false">
                {{ message(p) }}
              </RouterLink>
              <p v-if="p.params.since" class="text-xs text-muted">
                {{ t('problems.since', { time: formatUtc(String(p.params.since)) }) }}
              </p>
            </div>
          </li>
        </ul>
      </div>
      <footer v-if="store.updatedAt" class="border-t border-border p-3 text-xs text-muted">
        {{ t('common.asOf', { time: formatUtc(store.updatedAt) }) }}
      </footer>
    </aside>
  </div>
</template>
