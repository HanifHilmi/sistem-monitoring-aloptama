<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { api, ApiProblem } from '@/api/client'
import type { Role, TemporaryPassword, UserRow } from '@/api/types'
import SidePanel from '@/components/SidePanel.vue'
import { useLoader } from '@/composables/useLoader'
import { useAuthStore } from '@/stores/auth'
import { formatUtc } from '@/utils/time'

// Accounts (FR-AUTH-007): list, create, change role, deactivate (never delete), reset password.
const { t } = useI18n()
const auth = useAuthStore()
const loader = useLoader<UserRow[]>(() => api.users())
void loader.load()

const USERNAME = /^[a-z0-9][a-z0-9._-]{2,31}$/
const panel = ref<null | { mode: 'new' } | { mode: 'edit'; user: UserRow }>(null)
const form = reactive({ username: '', display_name: '', email: '', role: 'viewer' as Role, active: true })
const busy = ref(false)
const error = ref<string | null>(null)
const issued = ref<TemporaryPassword | null>(null)
const confirmReset = ref(false)
const copied = ref(false)

const sorted = computed(() =>
  [...(loader.data.value ?? [])].sort(
    (a, b) => Number(b.active) - Number(a.active) || a.display_name.localeCompare(b.display_name),
  ),
)
const locked = (u: UserRow) => u.locked_until !== null && Date.parse(u.locked_until) > Date.now()

function openNew() {
  Object.assign(form, { username: '', display_name: '', email: '', role: 'viewer', active: true })
  reset()
  panel.value = { mode: 'new' }
}
function openEdit(user: UserRow) {
  Object.assign(form, {
    username: user.username,
    display_name: user.display_name,
    email: user.email ?? '',
    role: user.role,
    active: user.active,
  })
  reset()
  panel.value = { mode: 'edit', user }
}
function reset() {
  error.value = null
  issued.value = null
  confirmReset.value = false
  copied.value = false
}
const valid = computed(
  () =>
    form.display_name.trim().length > 0 &&
    (panel.value?.mode !== 'new' || USERNAME.test(form.username)) &&
    (!form.email || /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(form.email)),
)

async function run(action: () => Promise<void>) {
  busy.value = true
  error.value = null
  try {
    await action()
    await loader.load({ silent: true })
  } catch (e) {
    error.value = e instanceof ApiProblem ? e.code : 'network_error'
  } finally {
    busy.value = false
  }
}
const save = () =>
  run(async () => {
    const p = panel.value
    if (!p) return
    const email = form.email.trim() || null
    if (p.mode === 'new') {
      issued.value = await api.createUser({
        username: form.username,
        display_name: form.display_name.trim(),
        email,
        role: form.role,
      })
    } else {
      const user = await api.updateUser(p.user.id, {
        display_name: form.display_name.trim(),
        email,
        role: form.role,
        active: form.active,
      })
      panel.value = { mode: 'edit', user }
      if (user.id === auth.me?.id) await auth.load(true)
    }
  })
const resetPassword = () =>
  run(async () => {
    if (panel.value?.mode !== 'edit') return
    issued.value = await api.resetPassword(panel.value.user.id)
    confirmReset.value = false
  })
async function copy() {
  if (!issued.value) return
  try {
    await navigator.clipboard.writeText(issued.value.temporary_password)
    copied.value = true
  } catch {
    /* the password is visible to copy by hand */
  }
}
const errorText = (code: string) =>
  ['username_taken', 'last_admin', 'own_account'].includes(code)
    ? t(`users.error.${code}`)
    : t('common.error')
</script>

<template>
  <div class="flex flex-col gap-4">
    <header class="flex flex-wrap items-end justify-between gap-3">
      <div>
        <h2 class="text-base font-semibold">{{ t('admin.section.users') }}</h2>
        <p class="text-sm text-ink-2">{{ t('users.subtitle') }}</p>
      </div>
      <button type="button" class="btn-primary" @click="openNew">{{ t('users.new') }}</button>
    </header>

    <p v-if="loader.error.value" class="text-sm text-warn" role="alert">{{ t('common.error') }}</p>
    <div v-else-if="!loader.data.value" class="h-40 animate-pulse rounded-lg bg-sunken" aria-busy="true" />
    <div v-else class="overflow-hidden rounded-lg border border-line bg-surface">
      <table class="w-full text-sm">
        <thead class="hidden border-b border-line text-left text-xs text-ink-3 sm:table-header-group">
          <tr>
            <th class="px-4 py-2 font-medium">{{ t('users.name') }}</th>
            <th class="px-4 py-2 font-medium">{{ t('users.role') }}</th>
            <th class="px-4 py-2 font-medium">{{ t('users.status') }}</th>
            <th class="px-4 py-2 font-medium">{{ t('users.lastLogin') }}</th>
            <th class="px-4 py-2">
              <span class="sr-only">{{ t('users.edit') }}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="u in sorted"
            :key="u.id"
            class="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line px-4 py-3 last:border-0 sm:table-row sm:px-0 sm:py-0"
            :class="u.active ? '' : 'text-ink-3'"
          >
            <td class="w-full sm:w-auto sm:px-4 sm:py-2.5">
              <span class="font-medium" :class="u.active ? 'text-ink' : ''">{{ u.display_name }}</span>
              <span v-if="u.id === auth.me?.id" class="ml-1.5 text-xs text-ink-3"
                >({{ t('users.you') }})</span
              >
              <span class="block text-xs text-ink-3"
                >{{ u.username }}{{ u.email ? ` · ${u.email}` : '' }}</span
              >
            </td>
            <td class="sm:px-4 sm:py-2.5">
              <span
                class="rounded px-1.5 py-0.5 text-xs"
                :class="u.role === 'admin' ? 'bg-accent-soft text-accent' : 'bg-sunken text-ink-2'"
                >{{ t(`role.${u.role}`) }}</span
              >
            </td>
            <td class="text-xs sm:px-4 sm:py-2.5">
              <span v-if="!u.active">{{ t('users.inactive') }}</span>
              <span v-else-if="locked(u)" class="text-warn">{{
                t('users.locked', { time: formatUtc(u.locked_until) })
              }}</span>
              <span v-else-if="u.password_temporary" class="text-ink-2">{{ t('users.temporary') }}</span>
              <span v-else class="text-ink-2">{{ t('users.active') }}</span>
            </td>
            <td class="text-xs text-ink-3 sm:px-4 sm:py-2.5">
              <span class="sm:hidden">{{ t('users.lastLogin') }}: </span
              ><span class="num">{{ u.last_login_at ? formatUtc(u.last_login_at) : t('users.never') }}</span>
            </td>
            <td class="ml-auto sm:px-4 sm:py-2.5 sm:text-right">
              <button type="button" class="btn py-1 text-xs" @click="openEdit(u)">
                {{ t('users.edit') }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <SidePanel
      :open="panel !== null"
      :title="panel?.mode === 'new' ? t('users.new') : t('users.editTitle', { name: form.display_name })"
      :subtitle="panel?.mode === 'edit' ? panel.user.username : undefined"
      @close="panel = null"
    >
      <div class="flex flex-col gap-4 py-1">
        <div
          v-if="issued"
          class="flex flex-col gap-2 rounded-lg border border-accent/40 bg-accent-soft p-4"
          role="status"
        >
          <p class="text-sm font-medium text-ink">
            {{ t('users.issued', { name: issued.user.display_name }) }}
          </p>
          <div class="flex items-center gap-2">
            <code class="num flex-1 rounded-md border border-line bg-surface px-3 py-2 text-sm select-all">{{
              issued.temporary_password
            }}</code>
            <button type="button" class="btn" @click="copy">
              {{ copied ? t('users.copied') : t('users.copy') }}
            </button>
          </div>
          <p class="text-xs text-ink-2">{{ t('users.issuedNote') }}</p>
          <button type="button" class="btn self-start" @click="panel = null">{{ t('common.close') }}</button>
        </div>

        <form v-else class="flex flex-col gap-4" novalidate @submit.prevent="save">
          <p v-if="error" class="rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-sm" role="alert">
            {{ errorText(error) }}
          </p>
          <label v-if="panel?.mode === 'new'" class="flex flex-col gap-1.5">
            <span class="label">{{ t('users.username') }}</span>
            <input
              v-model="form.username"
              class="input"
              autocapitalize="none"
              spellcheck="false"
              :aria-invalid="form.username !== '' && !USERNAME.test(form.username)"
            />
            <span class="text-xs text-ink-3">{{ t('users.usernameHint') }}</span>
          </label>
          <label class="flex flex-col gap-1.5">
            <span class="label">{{ t('users.displayName') }}</span>
            <input v-model="form.display_name" class="input" />
          </label>
          <label class="flex flex-col gap-1.5">
            <span class="label"
              >{{ t('users.email') }}
              <span class="font-normal text-ink-3">· {{ t('users.optional') }}</span></span
            >
            <input v-model="form.email" class="input" type="email" autocomplete="off" />
          </label>
          <fieldset class="flex flex-col gap-2">
            <legend class="label mb-1.5">{{ t('users.role') }}</legend>
            <label
              v-for="r in ['viewer', 'admin'] as Role[]"
              :key="r"
              class="flex cursor-pointer gap-3 rounded-md border px-3 py-2.5"
              :class="form.role === r ? 'border-accent bg-accent-soft' : 'border-line'"
            >
              <input
                v-model="form.role"
                type="radio"
                name="role"
                :value="r"
                class="mt-0.5 accent-[var(--s-accent)]"
              />
              <span>
                <span class="block text-sm font-medium">{{ t(`role.${r}`) }}</span>
                <span class="block text-xs text-ink-2">{{ t(`users.roleHint.${r}`) }}</span>
              </span>
            </label>
          </fieldset>
          <label v-if="panel?.mode === 'edit'" class="flex items-start gap-3">
            <input v-model="form.active" type="checkbox" class="mt-0.5 accent-[var(--s-accent)]" />
            <span>
              <span class="block text-sm">{{ t('users.activeLabel') }}</span>
              <span class="block text-xs text-ink-3">{{ t('users.activeHint') }}</span>
            </span>
          </label>
          <div class="flex flex-wrap gap-2 border-t border-line pt-4">
            <button type="submit" class="btn-primary" :disabled="!valid || busy">
              {{ panel?.mode === 'new' ? t('users.create') : t('users.save') }}
            </button>
            <button type="button" class="btn" @click="panel = null">{{ t('users.cancel') }}</button>
          </div>
          <div v-if="panel?.mode === 'edit'" class="flex flex-col gap-2 border-t border-line pt-4">
            <p class="label">{{ t('users.resetTitle') }}</p>
            <p class="text-xs text-ink-3">{{ t('users.resetHint') }}</p>
            <div v-if="confirmReset" class="flex flex-wrap items-center gap-2">
              <span class="text-sm">{{ t('users.resetConfirm', { name: form.display_name }) }}</span>
              <button type="button" class="btn-danger" :disabled="busy" @click="resetPassword">
                {{ t('users.resetYes') }}
              </button>
              <button type="button" class="btn" @click="confirmReset = false">{{ t('users.cancel') }}</button>
            </div>
            <button v-else type="button" class="btn self-start" @click="confirmReset = true">
              {{ t('users.reset') }}
            </button>
          </div>
        </form>
      </div>
    </SidePanel>
  </div>
</template>
