<script setup lang="ts">
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { ApiProblem } from '@/api/client'
import { useAuthStore } from '@/stores/auth'

// Sign in (FR-AUTH-001/002/004). Accounts are created by an Admin; there is no self-registration.
const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const username = ref('')
const password = ref('')
const show = ref(false)
const busy = ref(false)
const error = ref<string | null>(null)

// Only paths inside SIMOLA are followed after sign-in.
const next = () => {
  const n = typeof route.query.next === 'string' ? route.query.next : '/'
  return n.startsWith('/') && !n.startsWith('//') ? n : '/'
}

async function submit() {
  if (busy.value) return
  busy.value = true
  error.value = null
  try {
    const me = await auth.login(username.value.trim(), password.value)
    password.value = ''
    await router.replace(me.must_change_password ? { name: 'password' } : next())
  } catch (e) {
    // The same message for an unknown user and a wrong password (FR-AUTH-004).
    error.value =
      e instanceof ApiProblem
        ? e.code === 'account_locked' || e.code === 'too_many_attempts'
          ? 'locked'
          : e.code === 'csrf_failed'
            ? 'expired'
            : 'invalid'
        : 'network'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="mx-auto flex max-w-sm flex-col gap-5 pt-6 sm:pt-14">
    <header class="flex flex-col gap-1">
      <h1 class="text-xl font-semibold tracking-tight">{{ t('auth.title') }}</h1>
      <p class="text-sm text-ink-2">{{ t('auth.subtitle') }}</p>
    </header>

    <form
      class="flex flex-col gap-4 rounded-lg border border-line bg-surface p-5"
      novalidate
      @submit.prevent="submit"
    >
      <p
        v-if="error"
        class="rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-ink"
        role="alert"
      >
        {{ t(`auth.error.${error}`) }}
      </p>
      <label class="flex flex-col gap-1.5">
        <span class="label">{{ t('auth.username') }}</span>
        <input
          v-model="username"
          class="input"
          name="username"
          autocomplete="username"
          autocapitalize="none"
          spellcheck="false"
          required
          autofocus
        />
      </label>
      <div class="flex flex-col gap-1.5">
        <div class="flex items-center justify-between">
          <label for="login-password" class="label">{{ t('auth.password') }}</label>
          <button
            type="button"
            class="text-xs text-accent hover:underline"
            :aria-pressed="show"
            @click="show = !show"
          >
            {{ show ? t('auth.hide') : t('auth.show') }}
          </button>
        </div>
        <input
          id="login-password"
          v-model="password"
          class="input"
          name="password"
          :type="show ? 'text' : 'password'"
          autocomplete="current-password"
          required
        />
      </div>
      <button type="submit" class="btn-primary py-2" :disabled="busy || !username || !password">
        {{ busy ? t('auth.signingIn') : t('auth.signIn') }}
      </button>
    </form>

    <p class="text-xs text-ink-3">{{ t('auth.help') }}</p>
  </div>
</template>
