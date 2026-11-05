<script setup lang="ts">
import { computed, reactive, ref, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '@/api/client'
import type { AuditEvent, AuditFilter, AuditPage } from '@/api/types'
import { formatUtc } from '@/utils/time'

// Audit log (FR-AUD-001/002): append-only; filter by date, actor, action and entity; export as CSV.
const { t, te } = useI18n()
const filter = reactive<AuditFilter>({ from: '', to: '', actor: '', action: '', entity_type: '' })
const events = shallowRef<AuditEvent[]>([])
const page = shallowRef<AuditPage | null>(null)
const loading = ref(false)
const error = ref(false)
const open = ref<number | null>(null)

// Dates are whole UTC days: "to" includes that day.
const query = computed<AuditFilter>(() => ({
  from: filter.from ? `${filter.from}T00:00:00Z` : undefined,
  to: filter.to ? new Date(Date.parse(`${filter.to}T00:00:00Z`) + 86_400_000).toISOString() : undefined,
  actor: filter.actor || undefined,
  action: filter.action || undefined,
  entity_type: filter.entity_type || undefined,
}))

async function load(more = false) {
  loading.value = true
  error.value = false
  try {
    const p = await api.audit(query.value, more ? (page.value?.next_before ?? undefined) : undefined)
    events.value = more ? [...events.value, ...p.events] : p.events
    page.value = p
  } catch {
    error.value = true
  } finally {
    loading.value = false
  }
}
watch(query, () => void load(), { immediate: true })

const actionLabel = (a: string) => (te(`audit.action.${a}`) ? t(`audit.action.${a}`) : a)
const ENTITIES = ['user', 'session', 'setting', 'job', 'mandatory', 'component', 'flag', 'audit']
const fieldLabel = (k: string) => (te(`audit.fieldName.${k}`) ? t(`audit.fieldName.${k}`) : k)
function showValue(key: string, v: unknown): string {
  if (v === undefined || v === null || v === '') return '—'
  if (typeof v === 'boolean') return v ? t('audit.yes') : t('audit.no')
  if (key === 'role' && (v === 'viewer' || v === 'admin')) return t(`role.${v}`)
  if (
    (key === 'locked_until' || key.startsWith('in_service') || key === 'start' || key === 'end') &&
    typeof v === 'string'
  )
    return formatUtc(v)
  if (key === 'reason' && typeof v === 'string' && te(`flags.reason.${v}`)) return t(`flags.reason.${v}`)
  if (Array.isArray(v)) return v.join(', ')
  if (key === 'reason' && typeof v === 'string' && te(`audit.reason.${v}`)) return t(`audit.reason.${v}`)
  return typeof v === 'string' ? v : JSON.stringify(v)
}
// Sign-ins and sign-outs need no "· session" after them.
const entityLabel = (e: AuditEvent) =>
  e.entity_type && e.entity_type !== 'session'
    ? `${te(`audit.entity.${e.entity_type}`) ? t(`audit.entity.${e.entity_type}`) : e.entity_type}${e.entity_id ? ` ${e.entity_id}` : ''}`
    : ''

/** "role: viewer → admin" for every field that differs between before and after. */
function changes(e: AuditEvent): { key: string; before: string; after: string }[] {
  const keys = new Set([...Object.keys(e.before ?? {}), ...Object.keys(e.after ?? {})])
  return [...keys]
    .filter((k) => JSON.stringify(e.before?.[k]) !== JSON.stringify(e.after?.[k]))
    .map((k) => ({
      key: fieldLabel(k),
      before: showValue(k, e.before?.[k]),
      after: showValue(k, e.after?.[k]),
    }))
}
const tone = (a: string) => (a.includes('failed') || a.includes('locked') ? 'text-warn' : 'text-ink')
</script>

<template>
  <div class="flex flex-col gap-4">
    <header class="flex flex-wrap items-end justify-between gap-3">
      <div>
        <h2 class="text-base font-semibold">{{ t('admin.section.audit') }}</h2>
        <p class="text-sm text-ink-2">{{ t('audit.subtitle') }}</p>
      </div>
      <a class="btn" :href="api.auditCsvUrl(query)" download>{{ t('audit.csv') }}</a>
    </header>

    <form
      class="grid grid-cols-2 gap-3 rounded-lg border border-line bg-surface p-3 sm:grid-cols-5"
      @submit.prevent
    >
      <label class="flex flex-col gap-1">
        <span class="label">{{ t('audit.from') }}</span>
        <input v-model="filter.from" type="date" class="input py-1.5" />
      </label>
      <label class="flex flex-col gap-1">
        <span class="label">{{ t('audit.to') }}</span>
        <input v-model="filter.to" type="date" class="input py-1.5" />
      </label>
      <label class="flex flex-col gap-1">
        <span class="label">{{ t('audit.actor') }}</span>
        <select v-model="filter.actor" class="input py-1.5">
          <option value="">{{ t('audit.all') }}</option>
          <option v-for="a in page?.actors ?? []" :key="a" :value="a">{{ a }}</option>
        </select>
      </label>
      <label class="flex flex-col gap-1">
        <span class="label">{{ t('audit.actionLabel') }}</span>
        <select v-model="filter.action" class="input py-1.5">
          <option value="">{{ t('audit.all') }}</option>
          <option v-for="a in page?.actions ?? []" :key="a" :value="a">{{ actionLabel(a) }}</option>
        </select>
      </label>
      <label class="col-span-2 flex flex-col gap-1 sm:col-span-1">
        <span class="label">{{ t('audit.entityLabel') }}</span>
        <select v-model="filter.entity_type" class="input py-1.5">
          <option value="">{{ t('audit.all') }}</option>
          <option v-for="e in ENTITIES" :key="e" :value="e">{{ t(`audit.entity.${e}`) }}</option>
        </select>
      </label>
    </form>

    <p v-if="error" class="text-sm text-warn" role="alert">{{ t('common.error') }}</p>
    <div v-else-if="!page" class="h-40 animate-pulse rounded-lg bg-sunken" aria-busy="true" />
    <p
      v-else-if="events.length === 0"
      class="rounded-lg border border-line bg-surface p-6 text-center text-sm text-ink-3"
    >
      {{ t('audit.empty') }}
    </p>
    <ol v-else class="overflow-hidden rounded-lg border border-line bg-surface">
      <li v-for="e in events" :key="e.id" class="border-b border-line last:border-0">
        <button
          type="button"
          class="grid w-full grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-0.5 px-4 py-2.5 text-left hover:bg-sunken sm:grid-cols-[11rem_9rem_minmax(0,1fr)_auto]"
          :aria-expanded="open === e.id"
          @click="open = open === e.id ? null : e.id"
        >
          <span class="num order-2 text-xs text-ink-3 sm:order-none sm:pt-0.5">{{
            formatUtc(e.time, { seconds: true })
          }}</span>
          <span class="order-3 truncate text-xs text-ink-2 sm:order-none sm:pt-0.5 sm:text-sm">{{
            e.actor ?? t('audit.system')
          }}</span>
          <span class="order-1 min-w-0 text-sm sm:order-none">
            <span class="font-medium" :class="tone(e.action)">{{ actionLabel(e.action) }}</span>
            <span v-if="entityLabel(e)" class="text-ink-3"> · {{ entityLabel(e) }}</span>
            <span v-if="changes(e).length && open !== e.id" class="block truncate text-xs text-ink-3">
              {{
                changes(e)
                  .map((c) => `${c.key}: ${c.before} → ${c.after}`)
                  .join(' · ')
              }}
            </span>
          </span>
          <span class="order-4 self-start text-xs text-ink-3 sm:order-none" aria-hidden="true">{{
            open === e.id ? '▴' : '▾'
          }}</span>
        </button>
        <div
          v-if="open === e.id"
          class="flex flex-col gap-2 border-t border-line bg-sunken/50 px-4 py-3 text-xs"
        >
          <table v-if="changes(e).length" class="w-full max-w-2xl">
            <thead class="text-left text-ink-3">
              <tr>
                <th class="py-1 pr-3 font-medium">{{ t('audit.field') }}</th>
                <th class="py-1 pr-3 font-medium">{{ t('audit.before') }}</th>
                <th class="py-1 font-medium">{{ t('audit.after') }}</th>
              </tr>
            </thead>
            <tbody class="num">
              <tr v-for="c in changes(e)" :key="c.key">
                <td class="py-1 pr-3 text-ink-2">{{ c.key }}</td>
                <td class="py-1 pr-3">{{ c.before }}</td>
                <td class="py-1">{{ c.after }}</td>
              </tr>
            </tbody>
          </table>
          <p class="text-ink-3">
            {{ t('audit.source') }}: <span class="num">{{ e.source_ip ?? '—' }}</span> · #{{ e.id }}
          </p>
        </div>
      </li>
    </ol>
    <button
      v-if="page?.next_before"
      type="button"
      class="btn self-center"
      :disabled="loading"
      @click="load(true)"
    >
      {{ t('audit.more') }}
    </button>
    <p class="text-xs text-ink-3">{{ t('audit.appendOnly') }}</p>
  </div>
</template>
