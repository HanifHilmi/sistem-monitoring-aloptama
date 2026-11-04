import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api/client'
import type { SystemInfo } from '@/api/types'

/** Display settings and the registry, shared by all views. */
export const useDisplayStore = defineStore('display', () => {
  const thresholds = ref({ good: 99, warning: 95 })
  const systems = ref<Record<string, SystemInfo>>({})
  let loaded = false

  async function loadSettings() {
    if (loaded) return
    try {
      const s = await api.displaySettings()
      thresholds.value = s.color_thresholds
      loaded = true
    } catch {
      /* keep defaults; views still work */
    }
  }

  async function system(code: string): Promise<SystemInfo> {
    const cached = systems.value[code]
    if (cached) return cached
    const info = await api.system(code)
    systems.value = { ...systems.value, [code]: info }
    return info
  }

  return { thresholds, systems, loadSettings, system }
})
