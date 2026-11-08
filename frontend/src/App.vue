<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink, RouterView, useRoute } from 'vue-router'
import { api } from '@/api/client'
import LiveStrip from '@/components/LiveStrip.vue'
import ProblemsDrawer from '@/components/ProblemsDrawer.vue'
import SystemMenu, { type MenuItem } from '@/components/SystemMenu.vue'
import SystemStatus from '@/components/SystemStatus.vue'
import UserMenu from '@/components/UserMenu.vue'
import { usePolling } from '@/composables/usePolling'
import { setLocale, type Locale } from '@/i18n'
import { useAuthStore } from '@/stores/auth'
import { useDisplayStore } from '@/stores/display'
import { DEFAULT_SYSTEM, useLiveStore } from '@/stores/live'
import { boardPath, sitePath } from '@/utils/paths'
import { applyTheme, savedTheme, type ThemeChoice } from '@/utils/theme'
import type { SystemInfo } from '@/api/types'

const { t, locale } = useI18n()
const route = useRoute()
const display = useDisplayStore()
const auth = useAuthStore()
const live = useLiveStore()
const problemsOpen = ref(false)
const menuOpen = ref(false)
const systems = ref<SystemInfo[]>([])

onMounted(async () => {
  void display.loadSettings()
  try {
    const codes = (await api.systems()).map((s) => s.code)
    systems.value = await Promise.all(codes.map((c) => display.system(c)))
  } catch {
    /* shown by views */
  }
})
// Live status follows the system on screen (the Dashboard and wall screen show the default system's).
const routeCode = computed(() => (typeof route.params.code === 'string' ? route.params.code : DEFAULT_SYSTEM))
watch(routeCode, (c) => {
  if (live.systemCode === c) return
  live.systemCode = c
  void live.refresh()
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
// "AWOS CAT. III WIDN" -> "AWOS CAT. III": the airport is the same for every system.
const shortName = (s: SystemInfo) => s.name[lc.value].replace(new RegExp(`\\s*${s.icao ?? '$^'}\\s*$`), '')
const menus = computed(() =>
  systems.value.map((s) => ({
    code: s.code,
    label: shortName(s),
    items: [
      { to: boardPath(s.code), label: t('nav.system'), exact: true },
      ...s.sites.map((x) => ({ to: sitePath(s.code, x.slug), label: x.name[lc.value] })),
      { to: `/systems/${s.code}/reports`, label: t('nav.reports') },
      // The alarm viewer is for signed-in users (OPEN-13).
      ...(auth.canView ? [{ to: `/systems/${s.code}/alarms`, label: t('nav.alarms') }] : []),
    ] as MenuItem[],
    later: [] as string[],
  })),
)
// Systems SIMOLA will monitor later: greyed out in the menu, with a "coming soon" note.
const upcoming = computed(() => [
  { code: 'soon-cat1', label: t('nav.upcoming.cat1') },
  { code: 'soon-aws-digi', label: t('nav.upcoming.awsDigi') },
  { code: 'soon-aws-arg', label: t('nav.upcoming.awsArg') },
])
</script>

<template>
  <div class="flex min-h-screen flex-col">
    <a href="#main" class="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:bg-surface focus:p-2">{{
      t('nav.skip')
    }}</a>
    <header class="sticky top-0 z-30 border-b border-line bg-surface">
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
        <nav v-if="!wall" class="ml-3 hidden items-center gap-1 lg:flex" :aria-label="t('nav.menu')">
          <RouterLink
            to="/"
            class="rounded-md px-2.5 py-1.5 text-sm text-ink-2 hover:bg-sunken hover:text-ink"
            exact-active-class="!bg-sunken !text-ink font-medium"
            >{{ t('nav.dashboard') }}</RouterLink
          >
          <SystemMenu
            v-for="m in menus"
            :key="m.code"
            :code="m.code"
            :label="m.label"
            :active="route.params.code === m.code"
            :items="m.items"
            :later="m.later"
          />
          <SystemMenu
            v-for="u in upcoming"
            :key="u.code"
            :code="u.code"
            :label="u.label"
            :active="false"
            :items="[]"
            :later="[]"
            soon
          />
          <RouterLink
            v-if="auth.isAdmin"
            to="/admin"
            class="rounded-md px-2.5 py-1.5 text-sm text-ink-2 hover:bg-sunken hover:text-ink"
            active-class="!bg-sunken !text-ink font-medium"
            >{{ t('admin.title') }}</RouterLink
          >
        </nav>

        <div class="ml-auto flex items-center gap-2">
          <LiveStrip :compact="wall" @problems="problemsOpen = true" />
          <template v-if="!wall">
            <UserMenu />
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
        class="border-t border-line px-3 pb-2 pt-1 lg:hidden"
        :aria-label="t('nav.menu')"
      >
        <RouterLink to="/" class="block py-2 text-sm" @click="menuOpen = false">{{
          t('nav.dashboard')
        }}</RouterLink>
        <div v-for="m in menus" :key="m.code" class="border-t border-line py-1">
          <p class="eyebrow pb-1 pt-2">{{ m.label }}</p>
          <div v-if="live.systemCode === m.code" class="pb-1.5 pl-3"><SystemStatus /></div>
          <RouterLink
            v-for="i in m.items"
            :key="i.to"
            :to="i.to"
            class="block py-2 pl-3 text-sm"
            @click="menuOpen = false"
            >{{ i.label }}</RouterLink
          >
          <p v-for="l in m.later" :key="l" class="py-2 pl-3 text-sm text-ink-3">
            {{ l }} <span class="text-[0.625rem]">· {{ t('nav.later') }}</span>
          </p>
        </div>
        <div class="border-t border-line py-1">
          <p
            v-for="u in upcoming"
            :key="u.code"
            class="flex items-center justify-between py-2 text-sm text-ink-3"
            data-testid="system-soon"
          >
            {{ u.label }}
            <span class="rounded bg-sunken px-1.5 py-0.5 text-[0.625rem]">{{ t('nav.comingSoon') }}</span>
          </p>
        </div>
        <RouterLink
          v-if="auth.isAdmin"
          to="/admin"
          class="block border-t border-line py-2.5 text-sm"
          @click="menuOpen = false"
          >{{ t('admin.title') }}</RouterLink
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
