<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink, RouterView, useRoute } from 'vue-router'
import ProblemsPanel from '@/components/ProblemsPanel.vue'
import { usePolling } from '@/composables/usePolling'
import { setLocale, type Locale } from '@/i18n'
import { useDisplayStore } from '@/stores/display'
import { DEFAULT_SYSTEM, useProblemsStore } from '@/stores/problems'

const { t, locale } = useI18n()
const route = useRoute()
const display = useDisplayStore()
const problems = useProblemsStore()
const menuOpen = ref(false)

onMounted(() => void display.loadSettings())
usePolling(() => problems.refresh(), 30_000)

const systemCode = computed(() => (route.params.code as string | undefined) ?? DEFAULT_SYSTEM)
const otherLocale = computed<Locale>(() => (locale.value === 'id' ? 'en' : 'id'))
</script>

<template>
  <div class="flex min-h-screen flex-col">
    <a href="#main" class="sr-only focus:not-sr-only focus:absolute focus:p-2">{{ t('nav.skip') }}</a>
    <header class="sticky top-0 z-30 border-b border-border bg-bg/95 backdrop-blur">
      <div class="mx-auto flex max-w-7xl items-center gap-3 px-4 py-2.5">
        <RouterLink to="/" class="flex items-center gap-2" @click="menuOpen = false">
          <img src="/favicon.svg" alt="" class="h-6 w-6" />
          <span class="font-semibold">{{ t('app.name') }}</span>
          <span class="hidden text-xs text-muted lg:inline">{{ t('app.subtitle') }}</span>
        </RouterLink>
        <nav class="ml-2 hidden items-center gap-1 sm:flex" :aria-label="t('nav.menu')">
          <RouterLink to="/" class="btn-ghost" exact-active-class="!text-text bg-panel-2">{{
            t('nav.overview')
          }}</RouterLink>
          <RouterLink :to="`/systems/${systemCode}`" class="btn-ghost" active-class="!text-text bg-panel-2">
            {{ t('nav.systemDashboard') }}
          </RouterLink>
        </nav>
        <div class="ml-auto flex items-center gap-2">
          <ProblemsPanel />
          <button
            type="button"
            class="btn-ghost"
            :aria-label="`${t('nav.language')}: ${t('nav.switchTo')}`"
            @click="setLocale(otherLocale)"
          >
            {{ otherLocale.toUpperCase() }}
          </button>
          <button
            type="button"
            class="btn-ghost sm:hidden"
            :aria-expanded="menuOpen"
            aria-controls="mobile-nav"
            @click="menuOpen = !menuOpen"
          >
            ☰ <span class="sr-only">{{ t('nav.menu') }}</span>
          </button>
        </div>
      </div>
      <nav
        v-if="menuOpen"
        id="mobile-nav"
        class="border-t border-border px-4 py-2 sm:hidden"
        :aria-label="t('nav.menu')"
      >
        <RouterLink to="/" class="block py-2" @click="menuOpen = false">{{ t('nav.overview') }}</RouterLink>
        <RouterLink :to="`/systems/${systemCode}`" class="block py-2" @click="menuOpen = false">
          {{ t('nav.systemDashboard') }}
        </RouterLink>
      </nav>
    </header>
    <main id="main" class="mx-auto w-full max-w-7xl flex-1 px-4 py-5">
      <RouterView />
    </main>
    <footer class="border-t border-border px-4 py-3 text-center text-xs text-muted">
      {{ t('app.subtitle') }} · {{ t('app.allTimesUtc') }}
    </footer>
  </div>
</template>
