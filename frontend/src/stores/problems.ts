import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api/client'
import type { Problem } from '@/api/types'

export const DEFAULT_SYSTEM = 'WIDN-CAT3'

/** Problems panel data (FR-DSH-010), refreshed by the app shell every 30 s. */
export const useProblemsStore = defineStore('problems', () => {
  const systemCode = ref(DEFAULT_SYSTEM)
  const problems = ref<Problem[]>([])
  const error = ref(false)
  const updatedAt = ref<Date | null>(null)

  async function refresh() {
    try {
      const res = await api.problems(systemCode.value)
      problems.value = res.problems
      error.value = false
      updatedAt.value = new Date()
    } catch {
      error.value = true
    }
  }

  return { systemCode, problems, error, updatedAt, refresh }
})
