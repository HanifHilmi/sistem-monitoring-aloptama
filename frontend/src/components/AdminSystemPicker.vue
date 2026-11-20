<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '@/api/client'
import type { SystemInfo } from '@/api/types'
import type { Locale } from '@/i18n'
import { useAdminStore } from '@/stores/admin'
import { useDisplayStore } from '@/stores/display'
import { useLiveStore } from '@/stores/live'
import { UPCOMING_SYSTEMS } from '@/utils/systems'
import Dropdown from './Dropdown.vue'

// Which monitored system the Admin pages change (FR-ADM-001). Systems in SIMOLA can be chosen; the ones still to
// come are listed greyed out, so the place for them is clear before they arrive.
const { t, locale } = useI18n()
const admin = useAdminStore()
const display = useDisplayStore()
const live = useLiveStore()
const open = ref(false)
const systems = ref<SystemInfo[]>([])
const lc = computed(() => locale.value as Locale)

onMounted(async () => {
  try {
    const codes = (await api.systems()).map((s) => s.code)
    systems.value = await Promise.all(codes.map((c) => display.system(c)))
  } catch {
    /* the code is shown instead of the name */
  }
})
const name = (code: string) => display.systems[code]?.name[lc.value] ?? code
const TONE = { ok: 'bg-ok', warn: 'bg-warn', bad: 'bg-bad' } as const
const tone = computed(() => (live.systemCode === admin.system ? live.tone : null))

function choose(code: string, close: () => void) {
  admin.system = code
  close()
}
</script>

<template>
  <Dropdown
    v-model:open="open"
    role="menu"
    :label="t('admin.system.choose')"
    panel-class="w-72 p-1"
    data-testid="admin-system-menu"
  >
    <template #trigger="{ toggle }">
      <button
        type="button"
        class="flex w-full items-center gap-2 rounded-md border border-line bg-surface px-3 py-2 text-left hover:bg-sunken"
        aria-haspopup="menu"
        :aria-expanded="open"
        data-testid="admin-system"
        @click="toggle"
      >
        <span class="min-w-0 flex-1">
          <span class="block text-[0.6875rem] text-ink-3">{{ t('admin.system.label') }}</span>
          <span class="flex items-center gap-1.5 text-sm font-medium text-ink">
            <span v-if="tone" class="h-2 w-2 shrink-0 rounded-full" :class="TONE[tone]" aria-hidden="true" />
            <span class="truncate">{{ name(admin.system) }}</span>
          </span>
        </span>
        <span class="text-[0.625rem] text-ink-3" aria-hidden="true">▾</span>
      </button>
    </template>
    <template #default="{ close }">
      <button
        v-for="s in systems"
        :key="s.code"
        type="button"
        role="menuitemradio"
        :aria-checked="s.code === admin.system"
        class="flex w-full items-center justify-between gap-2 rounded-md px-3 py-2 text-left text-sm hover:bg-sunken"
        :class="s.code === admin.system ? 'bg-sunken font-medium text-ink' : 'text-ink-2'"
        @click="choose(s.code, close)"
      >
        {{ s.name[lc] }}
        <span v-if="s.code === admin.system" class="text-accent" aria-hidden="true">✓</span>
      </button>
      <div
        v-for="u in UPCOMING_SYSTEMS"
        :key="u.code"
        role="menuitem"
        aria-disabled="true"
        class="flex items-center justify-between gap-2 px-3 py-2 text-sm text-ink-3"
        data-testid="admin-system-soon"
      >
        {{ t(`nav.upcoming.${u.key}`) }}
        <span class="rounded bg-sunken px-1.5 py-0.5 text-[0.625rem]">{{ t('nav.comingSoon') }}</span>
      </div>
      <p class="mt-1 border-t border-line px-3 pb-1.5 pt-2 text-xs text-ink-3">
        {{ t('admin.system.note') }}
      </p>
    </template>
  </Dropdown>
</template>
