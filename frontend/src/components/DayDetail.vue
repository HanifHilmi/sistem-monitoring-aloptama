<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { RouterLink } from 'vue-router'
import { api } from '@/api/client'
import type { Detection, FieldInfo, Flag, FlagRow, MinutesResponse } from '@/api/types'
import { useLoader } from '@/composables/useLoader'
import type { Locale } from '@/i18n'
import { useAuthStore } from '@/stores/auth'
import { formatDuration, formatRange } from '@/utils/flags'
import { int, pct } from '@/utils/format'
import DetectionList from './detections/DetectionList.vue'
import FlagForm from './flags/FlagForm.vue'
import FlagList from './flags/FlagList.vue'
import FigureTrace from './records/FigureTrace.vue'

// Minute-by-minute explanation of one day for one scope (FR-DSH-009): every lost minute and its cause. For a
// component, flagged minutes and the day's flags are shown (FR-DQ-007), and Admins can flag minutes right here.
const props = defineProps<{
  systemCode: string
  scope: string
  day: string
  siteLink?: string | null
  /** the system's fields (units for detections) */
  fields?: Record<string, FieldInfo>
}>()
/** a flag was saved or removed here: the figures around it change */
const emit = defineEmits<{ changed: [] }>()
const { t, locale } = useI18n()
const lc = computed(() => locale.value as Locale)
const auth = useAuthStore()

const loader = useLoader<MinutesResponse>(() => api.minutes(props.systemCode, props.day, props.scope))
const dayStart = computed(() => Date.parse(`${props.day}T00:00:00Z`))
const parts = computed(() => props.scope.split(':'))
/** DCP is never flagged; SLA and CDP scopes are not about one component. */
const flaggable = computed(() => parts.value[0] === 'component' && parts.value[2] !== 'DCP')
const flagLoader = useLoader<Flag[]>(() =>
  api.flags(props.systemCode, new Date(dayStart.value), new Date(dayStart.value + 86_400_000), props.scope),
)
const flags = computed(() => (flaggable.value ? (flagLoader.data.value ?? []) : []))
const detLoader = useLoader<Detection[]>(() =>
  api.detections(
    props.systemCode,
    new Date(dayStart.value),
    new Date(dayStart.value + 86_400_000),
    props.scope,
  ),
)
const detections = computed(() => (flaggable.value ? (detLoader.data.value ?? []) : []))
function reload() {
  void loader.load()
  if (flaggable.value) {
    void flagLoader.load()
    void detLoader.load()
  }
}
watch(
  () => `${props.scope}|${props.day}`,
  () => {
    mode.value = 'map'
    selecting.value = false
    sel.value = null
    reload()
  },
)

const CODE_CLASS: Record<string, string> = {
  v: 'bg-full',
  f: 'bg-warn',
  n: 'bg-bad',
  g: 'bg-flag',
  d: 'bg-detect',
  s: 'cell-suspect',
  u: 'bg-empty',
}
const LEGEND = ['v', 's', 'f', 'n', 'g', 'd', 'u']
const codes = computed(() => loader.data.value?.codes ?? '')
const hours = computed(() => Array.from({ length: 24 }, (_, h) => codes.value.slice(h * 60, h * 60 + 60)))
// Flags and detections only exist for components; suspects only reach signed-in users.
const legend = computed(() =>
  LEGEND.filter((c) => !'gds'.includes(c) || (flaggable.value && (c !== 's' || auth.canView))),
)
const p = computed(() => {
  const d = loader.data.value
  return d && d.expected > 0 ? Math.round((d.valid / d.expected) * 10000) / 100 : null
})
const hhmm = (iso: string) => iso.slice(11, 16)
const dayEnd = (iso: string) => (iso.slice(11, 16) === '00:00' ? '24:00' : hhmm(iso))
const pad = (n: number) => String(n).padStart(2, '0')

/** The flag behind each flagged minute, for the hover text. */
const minuteFlag = computed(() => {
  const out = new Map<number, Flag | { id: number; reason: Flag['reason'] }>()
  for (const iv of loader.data.value?.intervals ?? []) {
    const ref = iv.flags?.[0]
    if (iv.cause !== 'flagged' || !ref) continue
    const full = flags.value.find((f) => f.id === ref.id) ?? ref
    const a = (Date.parse(iv.start) - dayStart.value) / 60_000
    for (let i = a; i < a + iv.minutes; i++) out.set(i, full)
  }
  return out
})
/** The detection behind each confirmed-bad or suspect minute. */
const minuteDetection = computed(() => {
  const out = new Map<number, Detection>()
  for (const d of detections.value) {
    if (d.status === 'rejected') continue
    const a = Math.max(0, (Date.parse(d.start) - dayStart.value) / 60_000)
    const b = Math.min(1440, (Date.parse(d.end) - dayStart.value) / 60_000)
    for (let i = a; i < b; i++) if (!out.has(i) || d.status === 'confirmed') out.set(i, d)
  }
  return out
})
function minuteTitle(h: number, m: number, c: string) {
  const i = h * 60 + m
  const base = `${pad(h)}:${pad(m)} · ${t(`day.code.${c}`)}`
  const f = c === 'g' ? minuteFlag.value.get(i) : undefined
  if (f) return `${base}: ${t(`flags.reason.${f.reason}`)} (#${f.id})`
  const d = c === 'd' || c === 's' ? minuteDetection.value.get(i) : undefined
  return d ? `${base}: ${t(`rules.type.${d.type}`)} · ${d.field} (#${d.id})` : base
}

// ---- flagging minutes (Admins) ----------------------------------------------------------------------
const selecting = ref(false)
const sel = ref<[number, number] | null>(null)
let anchor = -1
let dragging = false
let waitingForEnd = false
function down(i: number) {
  if (!selecting.value) return
  if (waitingForEnd && sel.value) {
    sel.value = [Math.min(anchor, i), Math.max(anchor, i)]
    waitingForEnd = false
    return
  }
  anchor = i
  sel.value = [i, i]
  dragging = true
}
function enter(i: number) {
  if (dragging) sel.value = [Math.min(anchor, i), Math.max(anchor, i)]
}
function up() {
  if (!dragging) return
  dragging = false
  waitingForEnd = !!sel.value && sel.value[0] === sel.value[1]
}
const inSel = (i: number) => !!sel.value && i >= sel.value[0] && i <= sel.value[1]
const iso = (ms: number) => new Date(ms).toISOString()
const selRange = computed(() =>
  sel.value
    ? {
        start: iso(dayStart.value + sel.value[0] * 60_000),
        end: iso(dayStart.value + (sel.value[1] + 1) * 60_000),
      }
    : null,
)
function cancelSelect() {
  selecting.value = false
  sel.value = null
  waitingForEnd = false
}

// ---- inline form ----------------------------------------------------------------------------------
const mode = ref<'map' | { kind: 'new'; start: string; end: string } | { kind: 'edit'; flag: FlagRow }>('map')
function startForm() {
  if (!selRange.value) return
  mode.value = { kind: 'new', ...selRange.value }
  cancelSelect()
}
async function editFlag(id: number) {
  const flag = (await api.adminFlags(props.systemCode, false)).find((f) => f.id === id)
  if (flag) mode.value = { kind: 'edit', flag }
}
function formDone() {
  mode.value = 'map'
  reload()
  emit('changed')
}
reload()
</script>

<template>
  <div v-if="mode !== 'map'" class="flex flex-col gap-3">
    <button type="button" class="self-start text-xs text-accent hover:underline" @click="mode = 'map'">
      ← {{ t('day.backToMinutes') }}
    </button>
    <h3 class="text-sm font-semibold">
      {{ mode.kind === 'new' ? t('flags.form.titleNew') : t('flags.form.titleEdit', { id: mode.flag.id }) }}
    </h3>
    <FlagForm
      v-if="mode.kind === 'new'"
      :system="systemCode"
      :initial="{ components: [{ site: parts[1]!, type: parts[2]! }], start: mode.start, end: mode.end }"
      @done="formDone"
      @cancel="mode = 'map'"
    />
    <FlagForm v-else :system="systemCode" :flag="mode.flag" @done="formDone" @cancel="mode = 'map'" />
  </div>

  <div v-else class="flex flex-col gap-4">
    <p v-if="loader.error.value" class="text-sm text-warn" role="alert">
      {{ t('common.error') }}
      <button type="button" class="icon-btn" @click="loader.load()">{{ t('common.retry') }}</button>
    </p>
    <div v-else-if="!loader.data.value" class="h-64 animate-pulse rounded-md bg-sunken" aria-busy="true" />
    <template v-else>
      <dl class="grid grid-cols-3 gap-px overflow-hidden rounded-md border border-line bg-line text-xs">
        <div class="bg-surface p-2">
          <dt class="text-ink-3">{{ t('day.availability') }}</dt>
          <dd class="num text-lg font-semibold">
            {{ pct(p, lc) }}<span class="text-xs text-ink-3"> %</span>
          </dd>
        </div>
        <div class="bg-surface p-2">
          <dt class="text-ink-3">{{ t('day.validMinutes') }}</dt>
          <dd class="num text-lg font-semibold">
            {{ int(loader.data.value.valid, lc)
            }}<span class="text-xs text-ink-3"> / {{ int(loader.data.value.expected, lc) }}</span>
          </dd>
        </div>
        <div class="bg-surface p-2">
          <dt class="text-ink-3">{{ t('day.lostMinutes') }}</dt>
          <dd class="num text-lg font-semibold">
            {{ int(loader.data.value.expected - loader.data.value.valid, lc) }}
          </dd>
        </div>
      </dl>

      <figure>
        <figcaption class="mb-1.5 flex min-h-7 flex-wrap items-center gap-2">
          <span class="eyebrow mr-auto">{{ t('day.minuteMap') }}</span>
          <template v-if="flaggable && auth.isAdmin">
            <template v-if="selecting">
              <span v-if="!selRange" class="text-xs text-ink-2">{{ t('day.selectHint') }}</span>
              <span v-else class="num text-xs font-medium text-flag" role="status"
                >{{ formatRange(selRange.start, selRange.end, lc) }} UTC ·
                {{ formatDuration(sel![1] - sel![0] + 1, t) }}</span
              >
              <button
                v-if="selRange"
                type="button"
                class="btn-primary px-2.5 py-1 text-xs"
                @click="startForm"
              >
                {{ t('flags.onChart.continue') }}
              </button>
              <button type="button" class="btn px-2.5 py-1 text-xs" @click="cancelSelect">
                {{ t('flags.onChart.cancel') }}
              </button>
            </template>
            <button v-else type="button" class="btn px-2.5 py-1 text-xs" @click="selecting = true">
              <span class="flag-hatch h-2.5 w-2.5 rounded-[1px] border border-flag" aria-hidden="true" />
              {{ t('day.selectMinutes') }}
            </button>
          </template>
        </figcaption>
        <div
          class="flex flex-col gap-[2px]"
          :class="selecting ? 'cursor-crosshair touch-none select-none' : ''"
          :role="selecting ? 'application' : 'img'"
          :aria-label="selecting ? t('day.selectHint') : t('day.minuteMapLabel')"
          @pointerup="up"
          @pointerleave="up"
        >
          <div v-for="(row, h) in hours" :key="h" class="flex items-center gap-1.5">
            <span class="num w-6 text-right text-[0.625rem] text-ink-3">{{ pad(h) }}</span>
            <span class="grid flex-1 gap-px" style="grid-template-columns: repeat(60, minmax(0, 1fr))">
              <span
                v-for="(c, m) in row"
                :key="m"
                class="h-2.5 rounded-[1px]"
                :class="[CODE_CLASS[c], inSel(h * 60 + m) ? 'ring-2 ring-flag ring-offset-0' : '']"
                :title="minuteTitle(h, m, c)"
                @pointerdown.prevent="down(h * 60 + m)"
                @pointerenter="enter(h * 60 + m)"
              />
            </span>
          </div>
        </div>
        <div class="mt-2 flex flex-wrap gap-3 text-[0.6875rem] text-ink-2">
          <span v-for="c in legend" :key="c" class="flex items-center gap-1"
            ><span
              class="h-2.5 w-2.5 rounded-[1px]"
              :class="[CODE_CLASS[c], c === 'u' ? 'border border-line' : '']"
            />{{ t(`day.code.${c}`) }}</span
          >
        </div>
      </figure>

      <section v-if="flags.length" :aria-label="t('day.flagsTitle')">
        <h3 class="eyebrow mb-1.5">{{ t('day.flagsTitle') }}</h3>
        <FlagList :flags="flags" :can-edit="auth.isAdmin" @edit="editFlag" />
      </section>

      <section v-if="detections.length" :aria-label="t('day.detectionsTitle')">
        <h3 class="eyebrow mb-1.5">{{ t('day.detectionsTitle') }}</h3>
        <DetectionList :detections="detections" :fields="fields ?? {}" :can-review="auth.isAdmin" />
      </section>

      <section>
        <h3 class="eyebrow mb-1.5">{{ t('day.intervals') }}</h3>
        <p v-if="!loader.data.value.intervals.length" class="text-xs text-ok">{{ t('day.noIntervals') }}</p>
        <table v-else class="w-full text-xs">
          <thead class="text-left text-ink-3">
            <tr>
              <th class="py-1 font-normal">{{ t('day.from') }}</th>
              <th class="font-normal">{{ t('day.to') }}</th>
              <th class="text-right font-normal">{{ t('day.minutes') }}</th>
              <th class="pl-3 font-normal">{{ t('day.cause') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(iv, i) in loader.data.value.intervals.slice(0, 30)"
              :key="i"
              class="border-t border-line"
            >
              <td class="num py-1">{{ hhmm(iv.start) }}</td>
              <td class="num">{{ dayEnd(iv.end) }}</td>
              <td class="num text-right">{{ iv.minutes }}</td>
              <td class="pl-3">
                <span
                  class="mr-1 inline-block h-2 w-2 rounded-[1px]"
                  :class="
                    iv.cause === 'field_missing'
                      ? 'bg-warn'
                      : iv.cause === 'flagged'
                        ? 'bg-flag'
                        : iv.cause === 'detection'
                          ? 'bg-detect'
                          : 'bg-bad'
                  "
                />
                {{ t(`day.causeName.${iv.cause}`) }}
                <template v-for="d in iv.detections ?? []" :key="d.id">
                  · {{ t(`rules.type.${d.type}`) }} {{ d.field }}
                  <RouterLink
                    v-if="auth.isAdmin"
                    :to="`/admin/review?status=confirmed&id=${d.id}`"
                    class="num text-accent hover:underline"
                    >#{{ d.id }}</RouterLink
                  >
                </template>
                <template v-for="f in iv.flags ?? []" :key="f.id">
                  · {{ t(`flags.reason.${f.reason}`) }}
                  <RouterLink
                    v-if="auth.isAdmin"
                    :to="`/admin/flags?id=${f.id}`"
                    class="num text-accent hover:underline"
                    >#{{ f.id }}</RouterLink
                  >
                </template>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-if="loader.data.value.intervals.length > 30" class="mt-1 text-[0.6875rem] text-ink-3">
          {{ t('day.more', { n: loader.data.value.intervals.length - 30 }) }}
        </p>
      </section>
      <FigureTrace
        v-if="flaggable"
        :system-code="systemCode"
        :scope="scope"
        :from="new Date(dayStart)"
        :to="new Date(dayStart + 86_400_000)"
      />
      <p class="text-[0.6875rem] text-ink-3">{{ t('common.allUtc') }}</p>
      <RouterLink v-if="siteLink" :to="siteLink" class="text-xs text-accent hover:underline"
        >{{ t('day.openCharts') }} →</RouterLink
      >
    </template>
  </div>
</template>
