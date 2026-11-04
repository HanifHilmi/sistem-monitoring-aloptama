// Chart colours come from the CSS design tokens (UX-001), never hard-coded in components.

export function token(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(`--color-${name}`).trim() || '#888'
}

export function seriesColors(): string[] {
  return [1, 2, 3, 4, 5].map((i) => token(`series-${i}`))
}

export function baseChartOptions() {
  const muted = token('muted')
  const border = token('border')
  return {
    useUTC: true,
    textStyle: { color: token('text'), fontFamily: getComputedStyle(document.body).fontFamily },
    tooltip: {
      backgroundColor: token('panel-2'),
      borderColor: border,
      textStyle: { color: token('text') },
    },
    axisLine: { lineStyle: { color: border } },
    axisLabel: { color: muted },
    splitLine: { lineStyle: { color: border, opacity: 0.5 } },
  }
}
