<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { ApiProblem } from '@/api/client'
import { useAuthStore } from '@/stores/auth'

// Change own password (FR-AUTH-003). After an Admin reset, this page comes first, before anything else.
const MIN = 12
const { t } = useI18n()
const router = useRouter()
const auth = useAuthStore()
const current = ref('')
const next = ref('')
const repeat = ref('')
const busy = ref(false)
const error = ref<string | null>(null)
const done = ref(false)
const forced = computed(() => auth.me?.must_change_password === true)

type State = 'ok' | 'bad' | 'pending'
const RULES = ['short', 'username', 'same', 'repeat'] as const
const rules = computed<Record<(typeof RULES)[number], State>>(() => {
  const n = next.value
  const judge = (ready: boolean, ok: boolean): State => (!ready ? 'pending' : ok ? 'ok' : 'bad')
  return {
    short: judge(n.length > 0, n.length >= MIN),
    username: judge(n.length > 0, !auth.me || !n.toLowerCase().includes(auth.me.username.toLowerCase())),
    same: judge(n.length > 0 && current.value.length > 0, n !== current.value),
    repeat: judge(repeat.value.length > 0, repeat.value === n),
  }
})
const ready = computed(() => RULES.every((r) => rules.value[r] === 'ok'))

async function submit() {
  if (!ready.value || busy.value) return
  busy.value = true
  error.value = null
  try {
    await auth.changePassword(current.value, next.value)
    current.value = next.value = repeat.value = ''
    done.value = true
  } catch (e) {
    error.value = e instanceof ApiProblem ? e.code : 'network_error'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="mx-auto flex max-w-sm flex-col gap-5 pt-6 sm:pt-14">
    <header class="flex flex-col gap-1">
      <h1 class="text-xl font-semibold tracking-tight">{{ t('account.title') }}</h1>
      <p class="text-sm text-ink-2">{{ forced ? t('account.forced') : t('account.subtitle') }}</p>
    </header>

    <div v-if="done" class="flex flex-col gap-3 rounded-lg border border-line bg-surface p-5" role="status">
      <p class="text-sm">{{ t('account.changed') }}</p>
      <button type="button" class="btn-primary self-start" @click="router.push('/')">
        {{ t('account.continue') }}
      </button>
    </div>
    <form
      v-else
      class="flex flex-col gap-4 rounded-lg border border-line bg-surface p-5"
      novalidate
      @submit.prevent="submit"
    >
      <p
        v-if="error"
        class="rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-sm text-ink"
        role="alert"
      >
        {{ t(`account.error.${error === 'wrong_password' || error === 'weak_password' ? error : 'other'}`) }}
      </p>
      <label class="flex flex-col gap-1.5">
        <span class="label">{{ forced ? t('account.temporary') : t('account.current') }}</span>
        <input v-model="current" class="input" type="password" autocomplete="current-password" required />
      </label>
      <label class="flex flex-col gap-1.5">
        <span class="label">{{ t('account.new') }}</span>
        <input v-model="next" class="input" type="password" autocomplete="new-password" required />
      </label>
      <label class="flex flex-col gap-1.5">
        <span class="label">{{ t('account.repeat') }}</span>
        <input v-model="repeat" class="input" type="password" autocomplete="new-password" required />
      </label>
      <ul class="flex flex-col gap-1 text-xs" aria-live="polite">
        <li
          v-for="rule in RULES"
          :key="rule"
          class="flex gap-1.5"
          :class="{
            'text-ink-3': rules[rule] === 'pending',
            'text-ink-2': rules[rule] === 'ok',
            'text-bad': rules[rule] === 'bad',
          }"
        >
          <span aria-hidden="true" class="w-3 text-center" :class="rules[rule] === 'ok' ? 'text-ok' : ''">{{
            rules[rule] === 'ok' ? '✓' : rules[rule] === 'bad' ? '✕' : '•'
          }}</span>
          {{ t(`account.rule.${rule}`, { n: MIN }) }}
        </li>
      </ul>
      <button type="submit" class="btn-primary py-2" :disabled="!ready || busy">
        {{ t('account.save') }}
      </button>
    </form>
  </div>
</template>
