<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import Dropdown from './Dropdown.vue'

// One system in the top bar: its name opens a menu with the system board, its sites and pages still to come.
export interface MenuItem {
  to: string
  label: string
  exact?: boolean
}
defineProps<{ label: string; active: boolean; items: MenuItem[]; later: string[] }>()
const { t } = useI18n()
const open = ref(false)
</script>

<template>
  <Dropdown v-model:open="open" :label="label" panel-class="w-60 p-1">
    <template #trigger="{ toggle }">
      <button
        type="button"
        class="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm hover:bg-sunken hover:text-ink"
        :class="active ? 'bg-sunken font-medium text-ink' : 'text-ink-2'"
        aria-haspopup="menu"
        :aria-expanded="open"
        @click="toggle"
      >
        {{ label }}
        <span class="text-[0.625rem]" aria-hidden="true">▾</span>
      </button>
    </template>
    <template #default="{ close }">
      <RouterLink
        v-for="i in items"
        :key="i.to"
        :to="i.to"
        role="menuitem"
        class="block rounded-md px-3 py-2 text-sm text-ink-2 hover:bg-sunken hover:text-ink"
        :exact-active-class="i.exact ? '!bg-sunken !text-ink font-medium' : ''"
        :active-class="i.exact ? '' : '!bg-sunken !text-ink font-medium'"
        @click="close()"
      >
        {{ i.label }}
      </RouterLink>
      <div
        v-for="l in later"
        :key="l"
        role="menuitem"
        aria-disabled="true"
        class="mt-1 flex items-center justify-between border-t border-line px-3 pb-1.5 pt-2.5 text-sm text-ink-3"
      >
        {{ l }}
        <span class="rounded bg-sunken px-1.5 py-0.5 text-[0.625rem]">{{ t('nav.later') }}</span>
      </div>
    </template>
  </Dropdown>
</template>
