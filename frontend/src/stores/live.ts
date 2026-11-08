import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api } from '@/api/client'
import type { Problem, StatusResponse } from '@/api/types'

export const DEFAULT_SYSTEM = 'WIDN-CAT3'

/** Live status and problems for the app shell (FR-DSH-003/010), refreshed every 30 s. */
export const useLiveStore = defineStore('live', () => {
  const systemCode = ref(DEFAULT_SYSTEM)
  const status = ref<StatusResponse | null>(null)
  const problems = ref<Problem[]>([])
  const error = ref(false)
  const updatedAt = ref<Date | null>(null)

  async function refresh() {
    try {
      const [s, p] = await Promise.all([api.status(systemCode.value), api.problems(systemCode.value)])
      status.value = s
      problems.value = p.problems
      error.value = false
      updatedAt.value = new Date()
    } catch {
      error.value = true
    }
  }

  const componentsValid = computed(() =>
    (status.value?.sites ?? []).reduce(
      (n, s) => n + s.components.filter((c) => c.status === 'valid').length,
      0,
    ),
  )
  const componentsTotal = computed(() =>
    (status.value?.sites ?? []).reduce((n, s) => n + s.components.length, 0),
  )
  const worst = computed(() => problems.value[0]?.severity ?? null)
  /** One colour for the system's menu button: a CDP not producing data, some components not valid, or all well. */
  const tone = computed<'ok' | 'warn' | 'bad' | null>(() => {
    if (error.value) return 'bad'
    if (!status.value) return null
    if (status.value.cdps.some((c) => c.data_flow === 'not_producing')) return 'bad'
    return componentsValid.value < componentsTotal.value ? 'warn' : 'ok'
  })

  function componentStatus(site: string, type: string): string {
    return (
      status.value?.sites.find((s) => s.slug === site)?.components.find((c) => c.type === type)?.status ??
      'unknown'
    )
  }

  return {
    systemCode,
    status,
    problems,
    error,
    updatedAt,
    refresh,
    componentsValid,
    componentsTotal,
    worst,
    tone,
    componentStatus,
  }
})
