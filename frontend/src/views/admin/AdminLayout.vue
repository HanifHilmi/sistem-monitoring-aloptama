<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { RouterLink, RouterView } from 'vue-router'

// Admin area (FR-ADM-001): one page with the PRD's sections. Sections of later R2 phases are listed as "later"
// so the area's shape is clear from the start (design docs/design/r2.md §3).
const { t } = useI18n()

interface Section {
  key: string
  to?: string
  phase?: string
}
const GROUPS: { key: string; sections: Section[] }[] = [
  {
    key: 'quality',
    sections: [
      { key: 'review', to: '/admin/review' },
      { key: 'flags', to: '/admin/flags' },
      { key: 'rules', to: '/admin/rules' },
    ],
  },
  {
    key: 'station',
    sections: [
      { key: 'registry', to: '/admin/components' },
      { key: 'calibration', phase: 'R2.5' },
      { key: 'mandatory', to: '/admin/mandatory' },
    ],
  },
  {
    key: 'system',
    sections: [
      { key: 'settings', to: '/admin/settings' },
      { key: 'jobs', to: '/admin/jobs' },
      { key: 'users', to: '/admin/users' },
      { key: 'audit', to: '/admin/audit' },
      { key: 'health', to: '/internal/health' },
    ],
  },
]
</script>

<template>
  <div class="flex flex-col gap-4 lg:flex-row lg:items-start lg:gap-6">
    <nav class="shrink-0 lg:sticky lg:top-16 lg:w-56" :aria-label="t('admin.title')">
      <h1 class="mb-2 text-lg font-semibold tracking-tight">{{ t('admin.title') }}</h1>
      <!-- Phones: the available sections as one scrollable row; wide screens: the full list -->
      <div class="-mx-3 flex gap-1 overflow-x-auto px-3 pb-1 lg:hidden">
        <template v-for="g in GROUPS" :key="g.key">
          <RouterLink
            v-for="s in g.sections.filter((x) => x.to)"
            :key="s.key"
            :to="s.to!"
            class="whitespace-nowrap rounded-md border border-line px-3 py-1.5 text-sm text-ink-2"
            active-class="!border-accent !text-ink font-medium"
            >{{ t(`admin.section.${s.key}`) }}</RouterLink
          >
        </template>
      </div>
      <div class="hidden flex-col gap-4 lg:flex">
        <div v-for="g in GROUPS" :key="g.key">
          <p class="eyebrow mb-1 px-2.5">{{ t(`admin.group.${g.key}`) }}</p>
          <template v-for="s in g.sections" :key="s.key">
            <RouterLink
              v-if="s.to"
              :to="s.to"
              class="block rounded-md px-2.5 py-1.5 text-sm text-ink-2 hover:bg-sunken hover:text-ink"
              active-class="!bg-sunken !text-ink font-medium"
              >{{ t(`admin.section.${s.key}`) }}</RouterLink
            >
            <p
              v-else
              class="flex items-center justify-between px-2.5 py-1.5 text-sm text-ink-3"
              aria-disabled="true"
            >
              {{ t(`admin.section.${s.key}`) }}
              <span class="rounded bg-sunken px-1.5 py-0.5 text-[0.625rem]" :title="s.phase">{{
                t('nav.later')
              }}</span>
            </p>
          </template>
        </div>
      </div>
    </nav>
    <section class="min-w-0 flex-1">
      <RouterView />
    </section>
  </div>
</template>
