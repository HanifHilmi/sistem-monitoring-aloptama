// Sample accounts and audit log for dev:sample and CI (R2.1). Everything lives in this browser tab's
// sessionStorage; names are fictional and addresses come from the documentation ranges (RFC 5737).
import type { AuditEvent, AuditPage, Me, Role, UserRow } from '@/api/types'

/** Every sample account signs in with this password (sample-data builds only). */
export const SAMPLE_PASSWORD = 'sampel-sandi-12'

interface MockUser extends Omit<UserRow, 'password_temporary'> {
  password: string
  must_change_password: boolean
  failures: number[]
}
interface State {
  users: MockUser[]
  session: string | null
  audit: AuditEvent[]
  next: number
}

const KEY = 'simola.mock.accounts'
const H = 3_600_000
const iso = (ms: number) => new Date(ms).toISOString()

function seed(now: number): State {
  const user = (
    id: number,
    username: string,
    display_name: string,
    role: Role,
    extra: Partial<MockUser> = {},
  ) => ({
    id,
    username,
    display_name,
    email: `${username}@example.org`,
    role,
    active: true,
    locked_until: null,
    last_login_at: iso(now - id * 7 * H),
    created_at: iso(now - (40 - id) * 24 * H),
    password: SAMPLE_PASSWORD,
    must_change_password: false,
    failures: [],
    ...extra,
  })
  const users: MockUser[] = [
    user(1, 'andi', 'Andi Pratama', 'admin'),
    user(2, 'budi', 'Budi Santoso', 'admin', { email: null }),
    user(3, 'siti', 'Siti Rahmawati', 'viewer'),
    user(4, 'rudi', 'Rudi Hartono', 'viewer', { locked_until: iso(now + 9 * 60_000), last_login_at: null }),
    user(5, 'dewi', 'Dewi Lestari', 'viewer', { active: false, last_login_at: iso(now - 30 * 24 * H) }),
  ]
  // A plausible fortnight of activity, oldest first.
  const raw: Omit<AuditEvent, 'id'>[] = []
  const add = (hoursAgo: number, actor: string | null, action: string, extra: Partial<AuditEvent> = {}) =>
    raw.push({
      time: iso(now - hoursAgo * H),
      actor,
      action,
      entity_type: null,
      entity_id: null,
      before: null,
      after: null,
      source_ip: actor ? `192.0.2.${10 + (actor.length % 7)}` : null,
      ...extra,
    })
  add(330, 'andi', 'user_created', {
    entity_type: 'user',
    entity_id: 'dewi',
    after: { username: 'dewi', role: 'viewer', active: true },
  })
  add(300, 'andi', 'user_created', {
    entity_type: 'user',
    entity_id: 'siti',
    after: { username: 'siti', role: 'viewer', active: true },
  })
  for (let d = 13; d >= 0; d--) {
    add(d * 24 + 9.2, 'andi', 'login_ok', { entity_type: 'session' })
    if (d % 2 === 0) add(d * 24 + 7.5, 'siti', 'login_ok', { entity_type: 'session' })
    if (d % 3 === 1) add(d * 24 + 5.1, 'budi', 'login_ok', { entity_type: 'session' })
    if (d % 4 === 2) add(d * 24 + 4.4, 'andi', 'logout', { entity_type: 'session' })
  }
  add(200, 'andi', 'user_updated', {
    entity_type: 'user',
    entity_id: 'budi',
    before: { role: 'viewer' },
    after: { role: 'admin' },
  })
  add(150, 'andi', 'user_updated', {
    entity_type: 'user',
    entity_id: 'dewi',
    before: { active: true },
    after: { active: false },
  })
  add(120, 'budi', 'password_changed', { entity_type: 'user', entity_id: 'budi' })
  add(48, 'andi', 'audit_exported', { entity_type: 'audit', after: { rows: 212 } })
  add(26, 'budi', 'password_reset', { entity_type: 'user', entity_id: 'rudi' })
  for (let i = 0; i < 5; i++)
    add(0.4 - i * 0.02, null, 'login_failed', {
      entity_type: 'user',
      entity_id: 'rudi',
      source_ip: '198.51.100.23',
    })
  add(0.3, null, 'account_locked', {
    entity_type: 'user',
    entity_id: 'rudi',
    after: { locked_until: users[3]!.locked_until },
    source_ip: '198.51.100.23',
  })
  raw.sort((a, b) => Date.parse(a.time) - Date.parse(b.time))
  const audit = raw.map((e, i) => ({ ...e, id: i + 1 }))
  return { users, session: null, audit, next: audit.length + 1 }
}

function load(now: number): State {
  try {
    const s = sessionStorage.getItem(KEY)
    if (s) return JSON.parse(s) as State
  } catch {
    /* storage unavailable: start fresh */
  }
  return seed(now)
}
function save(s: State) {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(s))
  } catch {
    /* ignore */
  }
}

const json = (body: unknown, status = 200) =>
  new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
const problem = (status: number, code: string) => json({ code, title: code, status }, status)
const row = (u: MockUser): UserRow => ({
  id: u.id,
  username: u.username,
  display_name: u.display_name,
  email: u.email,
  role: u.role,
  active: u.active,
  locked_until: u.locked_until,
  password_temporary: u.must_change_password,
  last_login_at: u.last_login_at,
  created_at: u.created_at,
})
const me = (u: MockUser): Me => ({
  id: u.id,
  username: u.username,
  display_name: u.display_name,
  role: u.role,
  must_change_password: u.must_change_password,
})
const temporary = () =>
  Array.from({ length: 3 }, () => Math.random().toString(36).slice(2, 6)).join('-') +
  '-' +
  (100 + Math.floor(Math.random() * 900))

/** Handles /auth/* and /admin/{users,audit}; returns null for other paths. */
export function accountsRoute(path: string, url: URL, method: string, body: unknown): Response | null {
  const now = Date.now()
  const s = load(now)
  const current = s.users.find((u) => u.username === s.session && u.active) ?? null
  const log = (action: string, extra: Partial<AuditEvent> = {}) =>
    s.audit.push({
      id: s.next++,
      time: iso(now),
      actor: current?.username ?? null,
      action,
      entity_type: null,
      entity_id: null,
      before: null,
      after: null,
      source_ip: '192.0.2.10',
      ...extra,
    })
  const b = (body ?? {}) as Record<string, unknown>
  const done = (r: Response) => {
    save(s)
    return r
  }

  if (path === '/auth/me') return json(current ? me(current) : null)
  if (path === '/auth/login' && method === 'POST') {
    const u = s.users.find((x) => x.username === String(b.username ?? '').toLowerCase())
    if (u?.locked_until && Date.parse(u.locked_until) > now) return done(problem(423, 'account_locked'))
    if (!u || !u.active || u.password !== b.password) {
      if (u) {
        u.failures = [...u.failures.filter((t) => now - t < 15 * 60_000), now]
        if (u.failures.length >= 5) u.locked_until = iso(now + 15 * 60_000)
      }
      log('login_failed', {
        actor: null,
        entity_type: 'user',
        entity_id: String(b.username ?? ''),
        after: { reason: 'password' },
      })
      return done(problem(401, 'invalid_credentials'))
    }
    u.failures = []
    u.last_login_at = iso(now)
    s.session = u.username
    log('login_ok', { actor: u.username, entity_type: 'session' })
    return done(json(me(u)))
  }
  if (path === '/auth/logout' && method === 'POST') {
    if (current) log('logout', { entity_type: 'session' })
    s.session = null
    return done(json(null, 204))
  }
  if (path === '/auth/password' && method === 'POST') {
    if (!current) return problem(401, 'not_authenticated')
    if (b.current_password !== current.password) return problem(400, 'wrong_password')
    if (['password1234', 'qwertyuiop12'].includes(String(b.new_password)))
      return problem(400, 'weak_password')
    current.password = String(b.new_password)
    current.must_change_password = false
    log('password_changed', { entity_type: 'user', entity_id: current.username })
    return done(json(me(current)))
  }

  if (!path.startsWith('/admin/users') && !path.startsWith('/admin/audit')) return null
  if (!current) return problem(401, 'not_authenticated')
  if (current.role !== 'admin') return problem(403, 'forbidden')

  if (path === '/admin/users' && method === 'GET') return json(s.users.map(row))
  if (path === '/admin/users' && method === 'POST') {
    const username = String(b.username ?? '')
    if (s.users.some((u) => u.username === username)) return problem(409, 'username_taken')
    const pw = temporary()
    const u: MockUser = {
      id: Math.max(...s.users.map((x) => x.id)) + 1,
      username,
      display_name: String(b.display_name ?? username),
      email: (b.email as string | null) ?? null,
      role: b.role === 'admin' ? 'admin' : 'viewer',
      active: true,
      locked_until: null,
      last_login_at: null,
      created_at: iso(now),
      password: pw,
      must_change_password: true,
      failures: [],
    }
    s.users.push(u)
    log('user_created', {
      entity_type: 'user',
      entity_id: username,
      after: { username, role: u.role, active: true },
    })
    return done(json({ user: row(u), temporary_password: pw }, 201))
  }
  const m = path.match(/^\/admin\/users\/(\d+)(\/reset-password)?$/)
  if (m) {
    const u = s.users.find((x) => x.id === Number(m[1]))
    if (!u) return problem(404, 'not_found')
    if (m[2] && method === 'POST') {
      const pw = temporary()
      u.password = pw
      u.must_change_password = true
      u.locked_until = null
      u.failures = []
      log('password_reset', { entity_type: 'user', entity_id: u.username })
      return done(json({ user: row(u), temporary_password: pw }))
    }
    if (method === 'PATCH') {
      const role = b.role === 'admin' ? 'admin' : b.role === 'viewer' ? 'viewer' : u.role
      const active = typeof b.active === 'boolean' ? b.active : u.active
      if (u.id === current.id && (role !== 'admin' || !active)) return problem(409, 'own_account')
      const admins = s.users.filter((x) => x.active && x.role === 'admin' && x.id !== u.id).length
      if (admins === 0 && (role !== 'admin' || !active)) return problem(409, 'last_admin')
      const before: Record<string, unknown> = {}
      const after: Record<string, unknown> = {}
      for (const [k, v] of Object.entries({
        display_name: b.display_name ?? u.display_name,
        email: b.email === undefined ? u.email : b.email,
        role,
        active,
      })) {
        if ((u as unknown as Record<string, unknown>)[k] !== v) {
          before[k] = (u as unknown as Record<string, unknown>)[k]
          after[k] = v
          ;(u as unknown as Record<string, unknown>)[k] = v
        }
      }
      if (Object.keys(after).length)
        log('user_updated', { entity_type: 'user', entity_id: u.username, before, after })
      return done(json(row(u)))
    }
  }
  if (path === '/admin/audit' && method === 'GET') {
    const q = url.searchParams
    const from = Date.parse(q.get('from') ?? '')
    const to = Date.parse(q.get('to') ?? '')
    const before = Number(q.get('before') ?? Infinity)
    const limit = Number(q.get('limit') ?? 50)
    const all = [...s.audit].reverse()
    const hits = all.filter(
      (e) =>
        e.id < before &&
        (Number.isNaN(from) || Date.parse(e.time) >= from) &&
        (Number.isNaN(to) || Date.parse(e.time) < to) &&
        (!q.get('actor') || e.actor === q.get('actor')) &&
        (!q.get('action') || e.action === q.get('action')) &&
        (!q.get('entity_type') || e.entity_type === q.get('entity_type')),
    )
    const page: AuditPage = {
      events: hits.slice(0, limit),
      next_before: hits.length > limit ? hits[limit - 1]!.id : null,
      actors: [...new Set(all.map((e) => e.actor).filter((a): a is string => !!a))].sort(),
      actions: [...new Set(all.map((e) => e.action))].sort(),
    }
    return json(page)
  }
  return problem(405, 'method_not_allowed')
}

/** Viewer-level routes need a session in sample mode too, like the real API. */
export function signedIn(): boolean {
  const s = load(Date.now())
  return s.users.some((u) => u.username === s.session && u.active)
}
