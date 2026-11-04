<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { api } from '@/api/client'
import { useLoader } from '@/composables/useLoader'
import { usePolling } from '@/composables/usePolling'
import type { Locale } from '@/i18n'
import { formatInt, formatNumber } from '@/utils/format'
import { formatUtc } from '@/utils/time'

// Viewer-level diagnostics (FR-ADM-004). Protected by Cloudflare Access until accounts exist (R2).
interface Health {
  version: string
  environment: string
  probe_method: string
  workers: { worker: string; version: string; leader: boolean; last_beat: string }[]
  database: { size_bytes: number }
  backups: {
    started_at: string
    finished_at: string | null
    ok: boolean | null
    size_bytes: number | null
    message: string | null
  }[]
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
    cdps: { code: string; reachability: string; rtt_ms: number | null; address: string | null }[]
  }[]
}

const { t, locale } = useI18n()
const lc = computed(() => locale.value as Locale)
const loader = useLoader<Health>(async () => (await api.internalHealth()) as unknown as Health)
usePolling(() => loader.load({ silent: loader.data.value !== null }), 30_000)
const mb = (b: number | null | undefined) => (b == null ? '—' : `${formatNumber(b / 1_048_576, lc.value)} MB`)
</script>

<template>
  <div class="space-y-4">
    <h1 class="text-xl font-semibold">{{ t('health.title') }}</h1>
    <p class="text-xs text-muted">{{ t('health.restricted') }}</p>
    <p v-if="loader.error.value" class="text-sm text-warn" role="alert">{{ t('common.error') }}</p>
    <template v-if="loader.data.value">
      <dl class="grid gap-3 sm:grid-cols-4">
        <div class="panel">
          <dt class="label">{{ t('health.version') }}</dt>
          <dd class="font-mono text-sm">{{ loader.data.value.version }}</dd>
        </div>
        <div class="panel">
          <dt class="label">{{ t('health.environment') }}</dt>
          <dd class="text-sm">{{ loader.data.value.environment }}</dd>
        </div>
        <div class="panel">
          <dt class="label">{{ t('health.database') }}</dt>
          <dd class="text-sm">{{ mb(loader.data.value.database.size_bytes) }}</dd>
        </div>
        <div class="panel">
          <dt class="label">{{ t('health.probeMethod') }}</dt>
          <dd class="font-mono text-sm">{{ loader.data.value.probe_method }}</dd>
        </div>
      </dl>

      <section v-for="s in loader.data.value.systems" :key="s.code" class="panel overflow-x-auto">
        <h2 class="label mb-2">{{ s.code }} · {{ t('health.ingestion') }}</h2>
        <table class="w-full min-w-[640px] text-left text-sm">
          <thead class="text-xs text-muted">
            <tr>
              <th class="py-1">{{ t('health.source') }}</th>
              <th>{{ t('health.available') }}</th>
              <th>{{ t('health.lag') }}</th>
              <th>{{ t('health.lastRecord') }}</th>
              <th>{{ t('health.parseWarnings') }}</th>
              <th>{{ t('health.oldestFile') }}</th>
              <th>{{ t('health.path') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="i in s.ingestion" :key="i.cdp ?? ''" class="border-t border-border">
              <td class="py-1 font-mono">{{ i.cdp }}</td>
              <td :class="i.available ? 'text-good' : 'text-bad'">
                {{ i.available ? t('health.yes') : t('health.no') }}
              </td>
              <td>{{ i.lag_min === null ? '—' : `${formatNumber(i.lag_min, lc)} min` }}</td>
              <td>{{ formatUtc(i.last_record_time) }}</td>
              <td>{{ formatInt(i.parse_warnings, lc) }}</td>
              <td>{{ i.oldest_file_date ?? '—' }}</td>
              <td class="font-mono text-xs">{{ i.path ?? '—' }}</td>
            </tr>
            <tr v-for="i in s.ingestion.filter((x) => x.last_error)" :key="`e-${i.cdp}`">
              <td colspan="7" class="pb-1 text-xs text-bad">{{ i.cdp }}: {{ i.last_error }}</td>
            </tr>
          </tbody>
        </table>
        <h3 class="label mt-4 mb-2">{{ t('health.cdps') }}</h3>
        <ul class="text-sm">
          <li v-for="c in s.cdps" :key="c.code" class="font-mono">
            {{ c.code }} · {{ c.address ?? '—' }} · {{ c.reachability }}
            <span v-if="c.rtt_ms !== null">· {{ formatNumber(c.rtt_ms, lc) }} ms</span>
          </li>
        </ul>
      </section>

      <section class="panel">
        <h2 class="label mb-2">{{ t('health.workers') }}</h2>
        <ul class="text-sm">
          <li v-for="w in loader.data.value.workers" :key="w.worker">
            <span class="font-mono">{{ w.worker }}</span> · {{ w.version }} ·
            {{ w.leader ? t('health.leader') : '—' }} · {{ t('health.lastBeat') }}
            {{ formatUtc(w.last_beat, { seconds: true }) }}
          </li>
        </ul>
      </section>

      <section class="panel">
        <h2 class="label mb-2">{{ t('health.backups') }}</h2>
        <p v-if="!loader.data.value.backups.length" class="text-sm text-muted">{{ t('health.noBackups') }}</p>
        <ul class="text-sm">
          <li v-for="b in loader.data.value.backups" :key="b.started_at" :class="b.ok ? '' : 'text-bad'">
            {{ formatUtc(b.started_at) }} · {{ b.ok ? '✓' : '✕' }} · {{ mb(b.size_bytes) }}
            <span v-if="b.message" class="text-muted">· {{ b.message }}</span>
          </li>
        </ul>
      </section>

      <section class="panel overflow-x-auto">
        <h2 class="label mb-2">{{ t('health.jobs') }}</h2>
        <p v-if="!loader.data.value.jobs.length" class="text-sm text-muted">{{ t('health.noJobs') }}</p>
        <ul class="text-sm">
          <li v-for="j in loader.data.value.jobs" :key="j.id">
            #{{ j.id }} {{ j.type }} · {{ j.status }} · {{ Math.round(j.progress * 100) }} %
            <span class="text-muted">· {{ formatUtc(j.created_at) }}</span>
            <span v-if="j.message" class="block text-xs text-muted">{{ j.message }}</span>
          </li>
        </ul>
      </section>
    </template>
  </div>
</template>
