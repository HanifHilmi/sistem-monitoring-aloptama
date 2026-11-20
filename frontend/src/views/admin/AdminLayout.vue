<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink, RouterView, useRoute } from 'vue-router'
import AdminSystemPicker from '@/components/AdminSystemPicker.vue'
import type { Locale } from '@/i18n'
import { useAdminStore } from '@/stores/admin'
import { useDisplayStore } from '@/stores/display'

// Admin area (FR-ADM-001). Most sections belong to one monitored system, chosen at the top of the menu and named
// above each of their pages; the last group is for all of SIMOLA. Only AWOS CAT. III is in SIMOLA so far: the
// other systems are listed in the chooser as "coming soon".
const { t, locale } = useI18n()
const route = useRoute()
const admin = useAdminStore()
const display = useDisplayStore()
void display.system(admin.system).catch(() => undefined)

interface Section {
  key: string
  to: string
}
const SYSTEM_GROUPS: { key: string; sections: Section[] }[] = [
  {
    key: 'quality',
    sections: [
      { key: 'review', to: '/admin/review' },
      { key: 'flags', to: '/admin/flags' },
      { key: 'rules', to: '/admin/rules' },
      { key: 'jobs', to: '/admin/jobs' },
    ],
  },
  {
    key: 'station',
    sections: [
      { key: 'registry', to: '/admin/components' },
      { key: 'calibration', to: '/admin/calibration' },
      { key: 'alarms', to: '/admin/alarms' },
      { key: 'mandatory', to: '/admin/mandatory' },
    ],
  },
]
const SHARED: Section[] = [
  { key: 'settings', to: '/admin/settings' },
  { key: 'users', to: '/admin/users' },
  { key: 'audit', to: '/admin/audit' },
  { key: 'health', to: '/internal/health' },
]
const systemSections = SYSTEM_GROUPS.flatMap((g) => g.sections)
const forSystem = computed(() => systemSections.some((s) => route.path.startsWith(s.to)))
const systemName = computed(() => display.systems[admin.system]?.name[locale.value as Locale] ?? admin.system)
const LINK = 'block rounded-md px-2.5 py-1.5 text-sm text-ink-2 hover:bg-sunken hover:text-ink'
const LINK_ACTIVE = '!bg-sunken !text-ink font-medium'
const CHIP = 'whitespace-nowrap rounded-md border border-line px-3 py-1.5 text-sm text-ink-2'

// Phones: the open page's section is brought into view in the scrollable row (it can sit past the right edge).
const row = ref<HTMLElement | null>(null)
async function showOpenSection() {
  await nextTick()
  const r = row.value
  const a = r?.querySelector<HTMLElement>('a[aria-current="page"]')
  if (r && a && r.clientWidth) r.scrollLeft = a.offsetLeft - (r.clientWidth - a.offsetWidth) / 2
}
onMounted(showOpenSection)
watch(() => route.path, showOpenSection)
</script>

<template>
  <div class="flex flex-col gap-4 lg:flex-row lg:items-start lg:gap-6">
    <nav class="shrink-0 lg:sticky lg:top-16 lg:w-60" :aria-label="t('admin.title')">
      <h1 class="mb-2 text-lg font-semibold tracking-tight">{{ t('admin.title') }}</h1>
      <!-- Phones: the system chooser, then the sections as one scrollable row -->
      <div class="flex flex-col gap-2 lg:hidden">
        <AdminSystemPicker />
        <div
          ref="row"
          class="relative -mx-3 flex items-center gap-1 overflow-x-auto px-3 pb-1"
          data-testid="admin-sections-row"
        >
          <RouterLink
            v-for="s in systemSections"
            :key="s.key"
            :to="s.to"
            :class="CHIP"
            active-class="!border-accent !text-ink font-medium"
            >{{ t(`admin.section.${s.key}`) }}</RouterLink
          >
          <span class="mx-1 h-5 w-px shrink-0 bg-line" aria-hidden="true" />
          <RouterLink
            v-for="s in SHARED"
            :key="s.key"
            :to="s.to"
            :class="CHIP"
            active-class="!border-accent !text-ink font-medium"
            >{{ t(`admin.section.${s.key}`) }}</RouterLink
          >
        </div>
      </div>
      <!-- Wide screens: the chosen system's sections in one box under its chooser, then SIMOLA's own -->
      <div class="hidden flex-col gap-4 lg:flex">
        <div
          class="flex flex-col gap-3 rounded-lg border border-line p-1.5"
          data-testid="admin-system-sections"
        >
          <AdminSystemPicker />
          <div v-for="g in SYSTEM_GROUPS" :key="g.key">
            <p class="eyebrow mb-1 px-2.5">{{ t(`admin.group.${g.key}`) }}</p>
            <RouterLink
              v-for="s in g.sections"
              :key="s.key"
              :to="s.to"
              :class="LINK"
              :active-class="LINK_ACTIVE"
              >{{ t(`admin.section.${s.key}`) }}</RouterLink
            >
          </div>
        </div>
        <div class="px-1.5">
          <p class="eyebrow mb-1 px-2.5">{{ t('admin.group.shared') }}</p>
          <RouterLink v-for="s in SHARED" :key="s.key" :to="s.to" :class="LINK" :active-class="LINK_ACTIVE">{{
            t(`admin.section.${s.key}`)
          }}</RouterLink>
        </div>
      </div>
    </nav>
    <section class="min-w-0 flex-1">
      <!-- Which system this page changes, or that it is for all of SIMOLA -->
      <p
        class="mb-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-ink-2"
        data-testid="admin-scope"
      >
        <span
          class="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 font-medium text-ink"
          :class="forSystem ? 'border-accent/50 bg-accent-soft' : 'border-line bg-sunken'"
          >{{ forSystem ? systemName : 'SIMOLA' }}</span
        >
        {{ forSystem ? t('admin.scope.system') : t('admin.scope.shared') }}
      </p>
      <RouterView :key="admin.system" />
    </section>
  </div>
</template>
