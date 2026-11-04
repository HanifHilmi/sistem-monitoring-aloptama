import { computed, type WritableComputedRef } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  decodePeriod,
  decodeWindow,
  encodePeriod,
  encodeWindow,
  periodContaining,
  type ChartWindow,
  type Period,
} from '@/utils/time'

/** Shared page period, kept in the URL so links reopen the same view (FR-DSH-002/013). */
export function usePeriodQuery(): WritableComputedRef<Period> {
  const route = useRoute()
  const router = useRouter()
  return computed({
    get: () => decodePeriod(route.query.p, periodContaining('month', new Date())),
    set: (p: Period) => void router.replace({ query: { ...route.query, p: encodePeriod(p) } }),
  })
}

export function useWindowQuery(): WritableComputedRef<ChartWindow> {
  const route = useRoute()
  const router = useRouter()
  return computed({
    get: () => decodeWindow(route.query.w),
    set: (w: ChartWindow) => void router.replace({ query: { ...route.query, w: encodeWindow(w) } }),
  })
}
