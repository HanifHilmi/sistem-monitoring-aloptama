import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api, ApiProblem } from '@/api/client'
import type { Me, Role } from '@/api/types'

/** The signed-in user (FR-AUTH-001/002). The server enforces every permission; this only shapes the UI. */
export const useAuthStore = defineStore('auth', () => {
  const me = ref<Me | null>(null)
  let loading: Promise<void> | null = null

  /** Asks the server once who is signed in; anonymous (or an API without accounts) leaves `me` empty. */
  function load(force = false): Promise<void> {
    if (loading && !force) return loading
    loading = api
      .me()
      .then((m) => {
        me.value = m
      })
      .catch(() => {
        me.value = null
      })
    return loading
  }

  async function login(username: string, password: string): Promise<Me> {
    const m = await api.login(username, password)
    me.value = m
    loading = Promise.resolve()
    return m
  }

  async function logout() {
    try {
      await api.logout()
    } catch (e) {
      if (!(e instanceof ApiProblem)) throw e
    } finally {
      me.value = null
      loading = Promise.resolve()
    }
  }

  async function changePassword(current: string, next: string) {
    me.value = await api.changePassword(current, next)
  }

  const role = computed<Role | null>(() => me.value?.role ?? null)
  const isAdmin = computed(() => role.value === 'admin')
  /** Viewer-level content: any signed-in user. */
  const canView = computed(() => role.value !== null)

  return { me, role, isAdmin, canView, load, login, logout, changePassword }
})
