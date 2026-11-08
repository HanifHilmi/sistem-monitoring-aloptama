<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import { useLiveStore } from '@/stores/live'
import Dropdown from './Dropdown.vue'
import SystemStatus from './SystemStatus.vue'

// One system in the top bar. Its name opens a menu: the system's live state, its board, its sites and pages still
// to come. A system not yet in SIMOLA ("soon") is greyed out and its menu says so.
export interface MenuItem {
  to: string
  label: string
  exact?: boolean
}
const props = defineProps<{
  code: string
  label: string
  active: boolean
  items: MenuItem[]
  later: string[]
  soon?: boolean
}>()
const { t } = useI18n()
const live = useLiveStore()
const open = ref(false)
const mine = computed(() => !props.soon && live.systemCode === props.code)
const TONE = { ok: 'bg-ok', warn: 'bg-warn', bad: 'bg-bad' } as const
const tone = computed(() => (mine.value ? live.tone : null))
</script>

<template>
  <Dropdown
    v-model:open="open"
    :role="soon ? 'dialog' : 'menu'"
    :label="label"
    :panel-class="soon ? 'w-64 p-3' : 'w-64 p-1'"
    :data-testid="soon ? 'system-soon' : 'system-menu'"
  >
    <template #trigger="{ toggle }">
      <button
        type="button"
        class="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm hover:bg-sunken"
        :class="
          soon
            ? 'text-ink-3'
            : active
              ? 'bg-sunken font-medium text-ink hover:text-ink'
              : 'text-ink-2 hover:text-ink'
        "
        :aria-haspopup="soon ? 'dialog' : 'menu'"
        :aria-expanded="open"
        @click="toggle"
      >
        <span v-if="tone" class="h-2 w-2 rounded-full" :class="TONE[tone]" aria-hidden="true" />
        {{ label }}
        <span class="text-[0.625rem]" aria-hidden="true">▾</span>
      </button>
    </template>
    <template #default="{ close }">
      <template v-if="soon">
        <p class="flex items-center justify-between gap-2 text-sm font-medium text-ink-2">
          {{ label }}
          <span class="rounded bg-sunken px-1.5 py-0.5 text-[0.625rem] font-normal text-ink-3">{{
            t('nav.comingSoon')
          }}</span>
        </p>
        <p class="mt-1.5 text-xs text-ink-3">{{ t('nav.comingSoonNote', { system: label }) }}</p>
      </template>
      <template v-else>
        <div v-if="mine" class="border-b border-line px-3 pb-2.5 pt-2">
          <SystemStatus />
        </div>
        <RouterLink
          v-for="i in items"
          :key="i.to"
          :to="i.to"
          role="menuitem"
          class="block rounded-md px-3 py-2 text-sm text-ink-2 first-of-type:mt-1 hover:bg-sunken hover:text-ink"
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
    </template>
  </Dropdown>
</template>
