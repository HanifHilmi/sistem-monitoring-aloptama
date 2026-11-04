<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

// Right-hand panel on wide screens, bottom sheet on phones. Escape or the backdrop closes it.
const props = defineProps<{ open: boolean; title: string; subtitle?: string }>()
const emit = defineEmits<{ close: [] }>()
const { t } = useI18n()
const closeBtn = ref<HTMLButtonElement | null>(null)

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') emit('close')
}
watch(
  () => props.open,
  async (open) => {
    if (open) {
      document.addEventListener('keydown', onKey)
      await nextTick()
      closeBtn.value?.focus()
    } else {
      document.removeEventListener('keydown', onKey)
    }
  },
  { immediate: true },
)
onBeforeUnmount(() => document.removeEventListener('keydown', onKey))
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="fixed inset-0 z-40 bg-black/30" aria-hidden="true" @click="emit('close')" />
    <section
      v-if="open"
      class="fixed inset-x-0 bottom-0 z-50 flex max-h-[88vh] flex-col rounded-t-xl border border-line bg-surface shadow-2xl sm:inset-y-0 sm:right-0 sm:left-auto sm:max-h-none sm:w-[560px] sm:rounded-none sm:border-y-0 sm:border-r-0"
      role="dialog"
      aria-modal="true"
      :aria-label="title"
    >
      <header class="flex items-start gap-3 border-b border-line px-4 py-3">
        <div class="min-w-0 flex-1">
          <h2 class="line-clamp-2 text-sm font-semibold">{{ title }}</h2>
          <p v-if="subtitle" class="truncate text-xs text-ink-3">{{ subtitle }}</p>
        </div>
        <button
          ref="closeBtn"
          type="button"
          class="icon-btn"
          :aria-label="t('common.close')"
          @click="emit('close')"
        >
          ✕
        </button>
      </header>
      <div class="min-h-0 flex-1 overflow-y-auto px-4 py-3">
        <slot />
      </div>
    </section>
  </Teleport>
</template>
