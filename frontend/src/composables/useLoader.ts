import { ref, shallowRef, type Ref, type ShallowRef } from 'vue'
import { ApiProblem } from '@/api/client'

export interface Loader<T> {
  data: ShallowRef<T | null>
  error: Ref<string | null>
  loading: Ref<boolean>
  updatedAt: Ref<Date | null>
  load: (opts?: { silent?: boolean }) => Promise<void>
}

/** Keeps the last good data on refresh errors, so polling never blanks a view (UX-007). */
export function useLoader<T>(fetcher: () => Promise<T>): Loader<T> {
  const data = shallowRef<T | null>(null)
  const error = ref<string | null>(null)
  const loading = ref(false)
  const updatedAt = ref<Date | null>(null)
  let seq = 0

  async function load(opts: { silent?: boolean } = {}) {
    const mine = ++seq
    if (!opts.silent) loading.value = true
    try {
      const result = await fetcher()
      if (mine !== seq) return // a newer request superseded this one
      data.value = result
      error.value = null
      updatedAt.value = new Date()
    } catch (e) {
      if (mine !== seq) return
      error.value = e instanceof ApiProblem ? e.code : 'network_error'
    } finally {
      if (mine === seq) loading.value = false
    }
  }

  return { data, error, loading, updatedAt, load }
}
