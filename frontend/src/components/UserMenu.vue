<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink, useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

// Top bar: "Sign in" for the public; the signed-in user's name with a menu otherwise (FR-AUTH-002).
const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const open = ref(false)
const root = ref<HTMLElement | null>(null)

const initials = computed(() =>
  (auth.me?.display_name || auth.me?.username || '?')
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? '')
    .join(''),
)
const onPointer = (e: PointerEvent) => {
  if (open.value && root.value && !root.value.contains(e.target as Node)) open.value = false
}
onMounted(() => document.addEventListener('pointerdown', onPointer))
onUnmounted(() => document.removeEventListener('pointerdown', onPointer))
watch(
  () => route.fullPath,
  () => (open.value = false),
)

async function signOut() {
  open.value = false
  await auth.logout()
  if (route.meta.role) await router.push('/')
}
</script>

<template>
  <RouterLink
    v-if="!auth.me"
    :to="{ name: 'login', query: route.name === 'login' ? {} : { next: route.fullPath } }"
    class="rounded-md px-2.5 py-1.5 text-sm text-ink-2 hover:bg-sunken hover:text-ink"
    >{{ t('auth.signIn') }}</RouterLink
  >
  <div v-else ref="root" class="relative" @keydown.escape="open = false">
    <button
      type="button"
      class="flex items-center gap-2 rounded-md py-1 pl-1 pr-2 text-sm text-ink-2 hover:bg-sunken hover:text-ink"
      aria-haspopup="menu"
      :aria-expanded="open"
      :aria-label="t('auth.menu', { name: auth.me.display_name })"
      @click="open = !open"
    >
      <span
        class="flex h-6 w-6 items-center justify-center rounded-full bg-accent-soft text-[0.625rem] font-semibold text-accent"
        aria-hidden="true"
        >{{ initials }}</span
      >
      <span class="hidden max-w-36 truncate sm:inline">{{ auth.me.display_name }}</span>
      <span class="text-[0.625rem]" aria-hidden="true">▾</span>
    </button>
    <div
      v-if="open"
      role="menu"
      class="absolute right-0 top-full z-40 mt-1.5 w-64 rounded-lg border border-line bg-surface p-1 shadow-lg"
    >
      <div class="border-b border-line px-3 pb-2.5 pt-2">
        <p class="truncate text-sm font-medium text-ink">{{ auth.me.display_name }}</p>
        <p class="truncate text-xs text-ink-3">{{ auth.me.username }} · {{ t(`role.${auth.me.role}`) }}</p>
      </div>
      <RouterLink
        v-if="auth.isAdmin"
        to="/admin"
        role="menuitem"
        class="mt-1 block rounded-md px-3 py-2 text-sm text-ink-2 hover:bg-sunken hover:text-ink"
        >{{ t('admin.title') }}</RouterLink
      >
      <RouterLink
        to="/internal/health"
        role="menuitem"
        class="block rounded-md px-3 py-2 text-sm text-ink-2 hover:bg-sunken hover:text-ink"
        >{{ t('admin.section.health') }}</RouterLink
      >
      <RouterLink
        :to="{ name: 'password' }"
        role="menuitem"
        class="block rounded-md px-3 py-2 text-sm text-ink-2 hover:bg-sunken hover:text-ink"
        >{{ t('account.title') }}</RouterLink
      >
      <button
        type="button"
        role="menuitem"
        class="mt-1 block w-full rounded-md border-t border-line px-3 py-2 text-left text-sm text-ink-2 hover:bg-sunken hover:text-ink"
        @click="signOut"
      >
        {{ t('auth.signOut') }}
      </button>
    </div>
  </div>
</template>
