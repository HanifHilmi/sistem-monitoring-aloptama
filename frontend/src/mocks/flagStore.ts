// Sample manual flags (R2.3) for dev:sample and CI. Kept apart from the routes so the loss model in data.ts can
// read them without a circular import. State lives in this tab's sessionStorage, like the other sample data.
import type { FlagReason } from '@/api/types'

export interface StoredFlag {
  id: number
  components: { site: string; type: string }[]
  start: string
  end: string
  reason: FlagReason
  note: string
  created_by: string
  created_at: string
  updated_by: string | null
  updated_at: string | null
  removed_by: string | null
  removed_at: string | null
}
interface State {
  flags: StoredFlag[]
}

const KEY = 'simola.mock.flags'
const H = 3_600_000
const iso = (ms: number) => new Date(ms).toISOString()

function seed(now: number): State {
  const flag = (
    id: number,
    components: [string, string][],
    start: string,
    end: string,
    reason: FlagReason,
    note: string,
    by: string,
    extra: Partial<StoredFlag> = {},
  ): StoredFlag => ({
    id,
    components: components.map(([site, type]) => ({ site, type })),
    start,
    end,
    reason,
    note,
    created_by: by,
    created_at: iso(Date.parse(end) + 25 * 60_000),
    updated_by: null,
    updated_at: null,
    removed_by: null,
    removed_at: null,
    ...extra,
  })
  // One flag two hours ago, so the site page's default 3-hour window shows it.
  const recent = Math.floor(now / H) * H - 2 * H
  return {
    flags: [
      flag(
        1,
        [['04', 'BARO']],
        '2026-10-02T05:00:00Z',
        '2026-10-02T06:00:00Z',
        'other',
        'Salah pilih barometer.',
        'budi',
        { removed_by: 'budi', removed_at: '2026-10-02T08:31:00Z' },
      ),
      flag(
        2,
        [['middle', 'ANEM']],
        '2026-10-08T13:10:00Z',
        '2026-10-08T13:40:00Z',
        'environmental',
        'Pemotongan rumput di dekat tiang; pembacaan angin terganggu.',
        'budi',
      ),
      flag(
        3,
        [
          ['04', 'RVR'],
          ['22', 'RVR'],
        ],
        '2026-10-15T01:00:00Z',
        '2026-10-15T03:00:00Z',
        'maintenance',
        'Pemeliharaan rutin transmisometer: kaca dibersihkan dan optik diselaraskan.',
        'budi',
      ),
      flag(
        4,
        [['22', 'CEL']],
        '2026-10-21T08:00:00Z',
        '2026-10-21T10:30:00Z',
        'sensor_fault',
        'Kaca ceilometer kotor setelah hujan lebat; dasar awan terbaca 0 ft sampai dibersihkan.',
        'andi',
        { updated_by: 'andi', updated_at: '2026-10-21T11:12:00Z' },
      ),
      flag(
        5,
        [['middle', 'ATRH']],
        '2026-11-03T02:00:00Z',
        '2026-11-03T02:45:00Z',
        'calibration',
        'Kalibrasi terhadap termometer acuan.',
        'andi',
      ),
      flag(
        6,
        [['04', 'ATRH']],
        iso(recent),
        iso(recent + H),
        'sensor_fault',
        'TEMP melompat 6 °C karena pelindung radiasi lepas; pelindung dipasang kembali.',
        'andi',
      ),
    ],
  }
}

let state: State | null = null
function current(): State {
  if (state) return state
  try {
    const s = globalThis.sessionStorage?.getItem(KEY)
    if (s) return (state = JSON.parse(s) as State)
  } catch {
    /* start fresh */
  }
  return (state = seed(Date.now()))
}

export function allFlags(): StoredFlag[] {
  return current().flags
}

export function saveFlags(): void {
  try {
    globalThis.sessionStorage?.setItem(KEY, JSON.stringify(current()))
  } catch {
    /* ignore */
  }
}

export function addFlag(f: Omit<StoredFlag, 'id'>): StoredFlag {
  const s = current()
  const flag = { ...f, id: Math.max(0, ...s.flags.map((x) => x.id)) + 1 }
  s.flags.push(flag)
  saveFlags()
  return flag
}

/** A preview of an edit leaves out the flag being edited. */
let excluded: number | null = null
export function withoutFlag<T>(id: number | null, fn: () => T): T {
  excluded = id
  try {
    return fn()
  } finally {
    excluded = null
  }
}

/** Active flags on one component overlapping [from, to), oldest first (a minute under two flags counts once). */
export function activeSpans(
  site: string,
  type: string,
  from: number,
  to: number,
): { start: number; end: number; id: number; reason: FlagReason }[] {
  const out = []
  for (const f of current().flags) {
    if (f.removed_at || f.id === excluded) continue
    if (!f.components.some((c) => c.site === site && c.type === type)) continue
    const start = Date.parse(f.start)
    const end = Date.parse(f.end)
    if (end > from && start < to) out.push({ start, end, id: f.id, reason: f.reason })
  }
  return out.sort((a, b) => a.id - b.id)
}

export function reasonOf(id: number): FlagReason {
  return current().flags.find((f) => f.id === id)?.reason ?? 'other'
}
