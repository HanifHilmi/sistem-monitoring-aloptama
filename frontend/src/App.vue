<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink, RouterView, useRoute } from 'vue-router'
import LiveStrip from '@/components/LiveStrip.vue'
import ProblemsDrawer from '@/components/ProblemsDrawer.vue'
import { usePolling } from '@/composables/usePolling'
import { setLocale, type Locale } from '@/i18n'
import { useDisplayStore } from '@/stores/display'
import { useLiveStore } from '@/stores/live'
import { applyTheme, savedTheme, type ThemeChoice } from '@/utils/theme'
import type { SystemInfo } from '@/api/types'

const { t, locale } = useI18n()
const route = useRoute()
const display = useDisplayStore()
const live = useLiveStore()
const problemsOpen = ref(false)
const menuOpen = ref(false)
const info = ref<SystemInfo | null>(null)

onMounted(async () => {
  void display.loadSettings()
  try {
    info.value = await display.system(live.systemCode)
  } catch {
    /* shown by views */
  }
})
usePolling(() => live.refresh(), 30_000)

const wall = computed(() => route.meta.wall === true)
watch(wall, (w) => document.documentElement.classList.toggle('wall', w), { immediate: true })

const theme = ref<ThemeChoice>(savedTheme())
applyTheme(theme.value)
const THEMES: ThemeChoice[] = ['system', 'light', 'dark']
function cycleTheme() {
  theme.value = THEMES[(THEMES.indexOf(theme.value) + 1) % THEMES.length]!
  applyTheme(theme.value)
}
const otherLocale = computed<Locale>(() => (locale.value === 'id' ? 'en' : 'id'))
const lc = computed(() => locale.value as Locale)
const nav = computed(() => [
  { to: '/', label: t('nav.board'), exact: true },
  ...(info.value?.sites ?? []).map((s) => ({
    to: `/sites/${s.slug}`,
    label: s.name[lc.value],
    exact: false,
  })),
])
</script>

<template>
  <div class="flex min-h-screen flex-col">
    <a href="#main" class="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:bg-surface focus:p-2">{{
      t('nav.skip')
    }}</a>
    <header class="sticky top-0 z-30 border-b border-line bg-surface/95 backdrop-blur">
      <div
        class="mx-auto flex h-12 items-center gap-3 px-3 sm:px-5"
        :class="wall ? 'max-w-none' : 'max-w-[100rem]'"
      >
        <RouterLink to="/" class="flex shrink-0 items-center gap-2" @click="menuOpen = false">
          <svg viewBox="0 0 24 24" class="h-5 w-5 text-accent" aria-hidden="true">
            <rect x="2" y="13" width="4" height="8" rx="1" fill="currentColor" opacity=".45" />
            <rect x="8" y="9" width="4" height="12" rx="1" fill="currentColor" opacity=".7" />
            <rect x="14" y="5" width="4" height="16" rx="1" fill="currentColor" />
            <rect x="20" y="2" width="2" height="19" rx="1" fill="currentColor" opacity=".35" />
          </svg>
          <span class="text-sm font-semibold tracking-tight">SIMOLA</span>
        </RouterLink>
        <span class="hidden h-5 w-px bg-line md:block" aria-hidden="true" />
        <span class="hidden truncate text-xs text-ink-2 md:block">{{ info?.name[lc] }}</span>

        <nav v-if="!wall" class="ml-2 hidden items-center gap-0.5 lg:flex" :aria-label="t('nav.menu')">
          <RouterLink
            v-for="n in nav"
            :key="n.to"
            :to="n.to"
            class="rounded-md px-2.5 py-1.5 text-xs text-ink-2 hover:bg-sunken hover:text-ink"
            :exact-active-class="n.exact ? '!bg-sunken !text-ink font-medium' : ''"
            :active-class="n.exact ? '' : '!bg-sunken !text-ink font-medium'"
          >
            {{ n.label }}
          </RouterLink>
        </nav>

        <div class="ml-auto flex items-center gap-2">
          <LiveStrip :compact="wall" @problems="problemsOpen = true" />
          <template v-if="!wall">
            <button
              type="button"
              class="icon-btn"
              :aria-label="`${t('nav.theme')}: ${t(`nav.themeName.${theme}`)}`"
              :title="t(`nav.themeName.${theme}`)"
              @click="cycleTheme"
            >
              <span aria-hidden="true">{{ theme === 'dark' ? '☾' : theme === 'light' ? '☀' : '◐' }}</span>
            </button>
            <button
              type="button"
              class="icon-btn num"
              :aria-label="`${t('nav.language')}: ${t('nav.switchTo')}`"
              @click="setLocale(otherLocale)"
            >
              {{ otherLocale.toUpperCase() }}
            </button>
            <button
              type="button"
              class="icon-btn lg:hidden"
              :aria-expanded="menuOpen"
              aria-controls="mobile-nav"
              :aria-label="t('nav.menu')"
              @click="menuOpen = !menuOpen"
            >
              ☰
            </button>
          </template>
        </div>
      </div>
      <nav
        v-if="menuOpen && !wall"
        id="mobile-nav"
        class="border-t border-line px-3 py-1 lg:hidden"
        :aria-label="t('nav.menu')"
      >
        <RouterLink
          v-for="n in nav"
          :key="n.to"
          :to="n.to"
          class="block py-2 text-sm"
          @click="menuOpen = false"
          >{{ n.label }}</RouterLink
        >
      </nav>
    </header>

    <main
      id="main"
      class="mx-auto w-full flex-1 px-3 sm:px-5"
      :class="wall ? 'max-w-none py-3' : 'max-w-[100rem] py-4 sm:py-5'"
    >
      <RouterView />
    </main>
    <footer v-if="!wall" class="border-t border-line px-5 py-2.5 text-center text-[0.6875rem] text-ink-3">
      {{ t('app.footer') }}
    </footer>
    <ProblemsDrawer :open="problemsOpen" @close="problemsOpen = false" />
  </div>
</template>
