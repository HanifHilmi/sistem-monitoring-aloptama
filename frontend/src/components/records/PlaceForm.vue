<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { api, ApiProblem } from '@/api/client'
import type { SiteMeta, StationMeta } from '@/api/types'

// The station's or a site's record (FR-REG-004): coordinates, elevation and descriptive fields, validated as the
// PRD says (latitude −90..90, longitude −180..180, years not in the future). Names and codes stay in the registry.
const props = defineProps<
  | { kind: 'station'; system: string; value: StationMeta }
  | { kind: 'site'; system: string; slug: string; value: SiteMeta }
>()
const emit = defineEmits<{ done: []; cancel: [] }>()
const { t } = useI18n()

const STATION_TEXT = ['airport_name', 'wmo_number', 'notes'] as const
const NUMBERS =
  props.kind === 'station'
    ? (['lat', 'lon', 'elevation_m', 'procurement_year'] as const)
    : (['lat', 'lon', 'elevation_m', 'threshold_elevation_m'] as const)
const form = reactive<Record<string, string>>({})
for (const k of NUMBERS) form[k] = String((props.value as unknown as Record<string, unknown>)[k] ?? '')
if (props.kind === 'station') for (const k of STATION_TEXT) form[k] = String(props.value[k] ?? '')
else form.description = props.value.description ?? ''

const num = (k: string) => (form[k]!.trim() === '' ? null : Number(form[k]!.replace(',', '.')))
const issue = computed(() => {
  const lat = num('lat')
  const lon = num('lon')
  if (lat !== null && !(lat >= -90 && lat <= 90)) return 'invalid_lat'
  if (lon !== null && !(lon >= -180 && lon <= 180)) return 'invalid_lon'
  for (const k of NUMBERS) if (num(k) !== null && Number.isNaN(num(k))) return 'invalid_number'
  const year = props.kind === 'station' ? num('procurement_year') : null
  if (year !== null && (!Number.isInteger(year) || year > new Date().getUTCFullYear()))
    return 'year_in_future'
  if (props.kind === 'station' && form.wmo_number!.trim() && !/^\d{5}$/.test(form.wmo_number!.trim()))
    return 'invalid_wmo'
  return null
})
const busy = ref(false)
const error = ref<string | null>(null)
async function save() {
  if (issue.value || busy.value) return
  busy.value = true
  error.value = null
  try {
    const numbers = Object.fromEntries(NUMBERS.map((k) => [k, num(k)]))
    if (props.kind === 'station')
      await api.saveStation(props.system, {
        icao: props.value.icao,
        ...numbers,
        ...Object.fromEntries(STATION_TEXT.map((k) => [k, form[k]!.trim() || null])),
      } as Omit<StationMeta, 'name'>)
    else
      await api.saveSiteMeta(props.system, props.slug, {
        ...numbers,
        description: form.description!.trim() || null,
      } as SiteMeta)
    emit('done')
  } catch (e) {
    error.value = e instanceof ApiProblem ? e.code : 'network_error'
  } finally {
    busy.value = false
  }
}
const errorText = (code: string) =>
  t(`records.error.${code}`) === `records.error.${code}` ? t('common.error') : t(`records.error.${code}`)
</script>

<template>
  <form class="flex flex-col gap-3 py-1" novalidate data-testid="place-form" @submit.prevent="save">
    <p v-if="error" class="rounded-md border border-bad/40 bg-bad/10 px-3 py-2 text-sm" role="alert">
      {{ errorText(error) }}
    </p>
    <template v-if="kind === 'station'">
      <label class="flex flex-col gap-1.5">
        <span class="label">{{ t('records.station.airport_name') }}</span>
        <input v-model="form.airport_name" type="text" maxlength="120" class="input py-1.5" />
      </label>
      <label class="flex flex-col gap-1.5">
        <span class="label">{{ t('records.station.wmo_number') }}</span>
        <input
          v-model="form.wmo_number"
          type="text"
          maxlength="10"
          inputmode="numeric"
          class="input num py-1.5"
        />
      </label>
    </template>
    <div class="grid gap-3 sm:grid-cols-2">
      <label v-for="k in NUMBERS" :key="k" class="flex flex-col gap-1.5">
        <span class="label">{{ t(`records.place.${k}`) }}</span>
        <input v-model="form[k]" type="text" inputmode="decimal" class="input num py-1.5" />
      </label>
    </div>
    <label class="flex flex-col gap-1.5">
      <span class="label">{{
        kind === 'station' ? t('records.meta.notes') : t('records.place.description')
      }}</span>
      <textarea v-if="kind === 'station'" v-model="form.notes" rows="2" maxlength="500" class="input" />
      <textarea v-else v-model="form.description" rows="2" maxlength="500" class="input" />
    </label>
    <p v-if="issue" class="text-xs text-bad">{{ errorText(issue) }}</p>
    <div class="flex gap-2 border-t border-line pt-3">
      <button type="submit" class="btn-primary" :disabled="!!issue || busy">{{ t('records.save') }}</button>
      <button type="button" class="btn" @click="emit('cancel')">{{ t('flags.form.cancel') }}</button>
    </div>
  </form>
</template>
