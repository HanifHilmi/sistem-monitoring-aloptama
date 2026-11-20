import { defineStore } from 'pinia'
import { ref } from 'vue'
import { DEFAULT_SYSTEM } from '@/stores/live'

/**
 * The monitored system the Admin area is changing (FR-ADM-001). Most Admin pages belong to one system (its sensors,
 * rules, flags, calibrations, alarm names, jobs); settings, users, the audit log and system health are for all of
 * SIMOLA. Only AWOS CAT. III is in SIMOLA so far, so the choice stays on it until a second system is added.
 */
export const useAdminStore = defineStore('admin', () => {
  const system = ref(DEFAULT_SYSTEM)
  return { system }
})

/** The chosen system's code, read once when a page opens: the Admin page is drawn again when the choice changes. */
export const useAdminSystem = (): string => useAdminStore().system
