import { onMounted, onUnmounted } from 'vue'

/** Run `fn` now and every `intervalMs`; paused while the tab is hidden (FR-DSH-011). */
export function usePolling(fn: () => unknown, intervalMs: number): { trigger: () => void } {
  let timer: ReturnType<typeof setInterval> | undefined
  const run = () => {
    if (document.visibilityState === 'visible') void fn()
  }
  const onVisibility = () => {
    if (document.visibilityState === 'visible') void fn()
  }
  onMounted(() => {
    void fn()
    timer = setInterval(run, intervalMs)
    document.addEventListener('visibilitychange', onVisibility)
  })
  onUnmounted(() => {
    if (timer) clearInterval(timer)
    document.removeEventListener('visibilitychange', onVisibility)
  })
  return { trigger: () => void fn() }
}
