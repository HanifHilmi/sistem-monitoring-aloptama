<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '@/api/client'
import { useLoader } from '@/composables/useLoader'
import { usePolling } from '@/composables/usePolling'
import type { Locale } from '@/i18n'
import { int, num } from '@/utils/format'
import { formatUtc } from '@/utils/time'

// Viewer-level diagnostics (FR-ADM-004). Protected by Cloudflare Access until accounts exist (R2).
/** A file reader of one CDP: alarms (R3.1) or reports (R3.2). */
interface FileSource {
  cdp: string | null
  available: boolean
  lag_min: number | null
  last_record_time: string | null
  parse_warnings: number
  path: string | null
  last_error: string | null
}
interface Health {
  version: string
  environment: string
  probe_method: string
  workers: { worker: string; version: string; leader: boolean; last_beat: string }[]
  database: { size_bytes: number }
  backups: { started_at: string; ok: boolean | null; size_bytes: number | null; message: string | null }[]
  jobs: {
    id: number
    type: string
    status: string
    progress: number
    message: string | null
    created_at: string
  }[]
  systems: {
    code: string
    ingestion: {
      cdp: string | null
      available: boolean
      lag_min: number | null
      last_record_time: string | null
      parse_warnings: number
      oldest_file_date: string | null
      path: string | null
      last_error: string | null
    }[]
    /** the alarm (R3.1) and report (R3.2) file readers; absent on an older API */
    alarm_files?: FileSource[]
    report_files?: FileSource[]
    cdps: {
      code: string
      data_flow: string
      reachability: string
      rtt_ms: number | null
      address: string | null
    }[]
  }[]
}

const { t, locale } = useI18n()
const lc = computed(() => locale.value as Locale)
const loader = useLoader<Health>(async () => (await api.internalHealth()) as unknown as Health)
usePolling(() => loader.load({ silent: loader.data.value !== null }), 30_000)
const mb = (b: number | null | undefined) => (b == null ? '—' : `${num(b / 1_048_576, lc.value)} MB`)
</script>

<template>
  <div class="flex flex-col gap-4">
    <header>
      <h1 class="text-lg font-semibold">{{ t('health.title') }}</h1>
      <p class="text-[0.6875rem] text-ink-3">{{ t('health.restricted') }}</p>
    </header>
    <p v-if="loader.error.value" class="text-sm text-warn" role="alert">{{ t('common.error') }}</p>
    <template v-if="loader.data.value">
      <dl
        class="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-line bg-line sm:grid-cols-4"
      >
        <div class="bg-surface p-3">
          <dt class="eyebrow">{{ t('health.version') }}</dt>
          <dd class="num mt-1 truncate text-sm">{{ loader.data.value.version }}</dd>
        </div>
        <div class="bg-surface p-3">
          <dt class="eyebrow">{{ t('health.environment') }}</dt>
          <dd class="mt-1 text-sm">{{ loader.data.value.environment }}</dd>
        </div>
        <div class="bg-surface p-3">
          <dt class="eyebrow">{{ t('health.database') }}</dt>
          <dd class="num mt-1 text-sm">{{ mb(loader.data.value.database.size_bytes) }}</dd>
        </div>
        <div class="bg-surface p-3">
          <dt class="eyebrow">{{ t('health.probeMethod') }}</dt>
          <dd class="num mt-1 text-sm">{{ loader.data.value.probe_method }}</dd>
        </div>
      </dl>

      <section
        v-for="s in loader.data.value.systems"
        :key="s.code"
        class="overflow-x-auto rounded-lg border border-line bg-surface"
      >
        <h2 class="eyebrow border-b border-line px-3 py-2">{{ s.code }} · {{ t('health.ingestion') }}</h2>
        <table class="w-full min-w-[640px] text-xs">
          <thead class="text-left text-[0.625rem] text-ink-3">
            <tr>
              <th class="px-3 py-1 font-normal">{{ t('health.source') }}</th>
              <th class="font-normal">{{ t('health.available') }}</th>
              <th class="font-normal">{{ t('health.lag') }}</th>
              <th class="font-normal">{{ t('health.lastRecord') }}</th>
              <th class="font-normal">{{ t('health.parseWarnings') }}</th>
              <th class="font-normal">{{ t('health.oldestFile') }}</th>
              <th class="font-normal">{{ t('health.path') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="i in s.ingestion" :key="i.cdp ?? ''" class="border-t border-line">
              <td class="num px-3 py-1.5">{{ i.cdp }}</td>
              <td :class="i.available ? 'text-ok' : 'text-bad'">
                {{ i.available ? t('health.yes') : t('health.no') }}
              </td>
              <td class="num">{{ i.lag_min === null ? '—' : `${num(i.lag_min, lc)} min` }}</td>
              <td class="num">{{ formatUtc(i.last_record_time) }}</td>
              <td class="num">{{ int(i.parse_warnings, lc) }}</td>
              <td class="num">{{ i.oldest_file_date ?? '—' }}</td>
              <td class="num text-ink-3">{{ i.path ?? '—' }}</td>
            </tr>
            <tr v-for="i in s.ingestion.filter((x) => x.last_error)" :key="`e-${i.cdp}`">
              <td colspan="7" class="px-3 pb-1.5 text-bad">{{ i.cdp }}: {{ i.last_error }}</td>
            </tr>
          </tbody>
        </table>
        <template
          v-for="f in [
            { key: 'alarm', rows: s.alarm_files ?? [], title: 'health.alarmFiles', last: 'health.lastAlarm' },
            {
              key: 'report',
              rows: s.report_files ?? [],
              title: 'health.reportFiles',
              last: 'health.lastReport',
            },
          ].filter((x) => x.rows.length)"
          :key="f.key"
        >
          <h3 class="eyebrow border-t border-line px-3 py-2">{{ t(f.title) }}</h3>
          <table class="w-full min-w-[640px] text-xs" :data-testid="`health-${f.key}-files`">
            <thead class="text-left text-[0.625rem] text-ink-3">
              <tr>
                <th class="px-3 py-1 font-normal">{{ t('health.source') }}</th>
                <th class="font-normal">{{ t('health.available') }}</th>
                <th class="font-normal">{{ t('health.lag') }}</th>
                <th class="font-normal">{{ t(f.last) }}</th>
                <th class="font-normal">{{ t('health.parseWarnings') }}</th>
                <th class="font-normal">{{ t('health.path') }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="i in f.rows" :key="i.cdp ?? ''" class="border-t border-line">
                <td class="num px-3 py-1.5">{{ i.cdp }}</td>
                <td :class="i.available ? 'text-ok' : 'text-bad'">
                  {{ i.available ? t('health.yes') : t('health.no') }}
                </td>
                <td class="num">{{ i.lag_min === null ? '—' : `${num(i.lag_min, lc)} min` }}</td>
                <td class="num">{{ formatUtc(i.last_record_time) }}</td>
                <td class="num">{{ int(i.parse_warnings, lc) }}</td>
                <td class="num text-ink-3">{{ i.path ?? '—' }}</td>
              </tr>
              <tr v-for="i in f.rows.filter((x) => x.last_error)" :key="`e-${i.cdp}`">
                <td colspan="6" class="px-3 pb-1.5 text-bad">{{ i.cdp }}: {{ i.last_error }}</td>
              </tr>
            </tbody>
          </table>
        </template>
        <h3 class="eyebrow border-t border-line px-3 py-2">{{ t('health.cdps') }}</h3>
        <ul class="num px-3 pb-3 text-xs">
          <li v-for="c in s.cdps" :key="c.code">
            {{ c.code }} · {{ c.address ?? '—' }} · {{ t(`cdp.flow.${c.data_flow}`) }} ·
            {{ t(`cdp.reach.${c.reachability}`) }}
            <span v-if="c.rtt_ms !== null" class="text-ink-3">· {{ num(c.rtt_ms, lc) }} ms</span>
          </li>
        </ul>
      </section>

      <div class="grid gap-4 md:grid-cols-3">
        <section class="rounded-lg border border-line bg-surface p-3">
          <h2 class="eyebrow mb-2">{{ t('health.workers') }}</h2>
          <ul class="text-xs">
            <li v-for="w in loader.data.value.workers" :key="w.worker" class="num">
              {{ w.worker }} · {{ w.leader ? t('health.leader') : '—' }} ·
              {{ formatUtc(w.last_beat, { seconds: true }) }}
            </li>
          </ul>
        </section>
        <section class="rounded-lg border border-line bg-surface p-3">
          <h2 class="eyebrow mb-2">{{ t('health.backups') }}</h2>
          <p v-if="!loader.data.value.backups.length" class="text-xs text-ink-3">
            {{ t('health.noBackups') }}
          </p>
          <ul class="text-xs">
            <li
              v-for="b in loader.data.value.backups"
              :key="b.started_at"
              :class="b.ok ? '' : 'text-bad'"
              class="num"
            >
              {{ formatUtc(b.started_at) }} · {{ b.ok ? '✓' : '✕' }} · {{ mb(b.size_bytes) }}
            </li>
          </ul>
        </section>
        <section class="rounded-lg border border-line bg-surface p-3">
          <h2 class="eyebrow mb-2">{{ t('health.jobs') }}</h2>
          <p v-if="!loader.data.value.jobs.length" class="text-xs text-ink-3">{{ t('health.noJobs') }}</p>
          <ul class="flex flex-col gap-1 text-xs">
            <li v-for="j in loader.data.value.jobs" :key="j.id">
              <span class="num">#{{ j.id }}</span> {{ j.type }} · {{ j.status }} ·
              {{ Math.round(j.progress * 100) }} %
              <span v-if="j.message" class="block truncate text-[0.6875rem] text-ink-3">{{ j.message }}</span>
            </li>
          </ul>
        </section>
      </div>
    </template>
  </div>
</template>
