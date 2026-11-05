import { createRouter, createWebHistory } from 'vue-router'
import type { Role } from '@/api/types'
import { useAuthStore } from '@/stores/auth'
import { DEFAULT_SYSTEM } from '@/stores/live'
import { boardPath, sitePath } from '@/utils/paths'

declare module 'vue-router' {
  interface RouteMeta {
    wall?: boolean
    /** least role that may open the page (PRD §5.4); the server checks again on every request */
    role?: Role
  }
}

const site = (slug: unknown) => sitePath(DEFAULT_SYSTEM, String(slug))

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    // Dashboard: every system at a glance.
    { path: '/', name: 'overview', component: () => import('@/views/OverviewView.vue') },
    { path: '/systems/:code', name: 'board', component: () => import('@/views/BoardView.vue'), props: true },
    {
      path: '/systems/:code/sites/:slug',
      name: 'site',
      component: () => import('@/views/SiteView.vue'),
      props: true,
    },
    // Wall screen / TV: current month, no controls, larger type, refreshes itself.
    {
      path: '/wall',
      name: 'wall',
      component: () => import('@/views/BoardView.vue'),
      props: { wall: true, code: DEFAULT_SYSTEM },
      meta: { wall: true },
    },
    {
      path: '/internal/health',
      name: 'health',
      component: () => import('@/views/HealthView.vue'),
      meta: { role: 'viewer' },
    },

    // Accounts (R2.1)
    { path: '/login', name: 'login', component: () => import('@/views/LoginView.vue') },
    {
      path: '/account/password',
      name: 'password',
      component: () => import('@/views/PasswordView.vue'),
      meta: { role: 'viewer' },
    },
    { path: '/forbidden', name: 'forbidden', component: () => import('@/views/ForbiddenView.vue') },
    {
      path: '/admin',
      component: () => import('@/views/admin/AdminLayout.vue'),
      meta: { role: 'admin' },
      children: [
        { path: '', redirect: { name: 'admin-users' } },
        { path: 'users', name: 'admin-users', component: () => import('@/views/admin/UsersView.vue') },
        { path: 'audit', name: 'admin-audit', component: () => import('@/views/admin/AuditView.vue') },
      ],
    },

    // Earlier SIMOLA and v2 paths (PRD §14.4)
    { path: '/sites/:slug', redirect: (to) => site(to.params.slug) },
    { path: '/cat3', redirect: boardPath(DEFAULT_SYSTEM) },
    { path: '/cat3/system', redirect: boardPath(DEFAULT_SYSTEM) },
    { path: '/cat3/runway/:slug', redirect: (to) => site(to.params.slug) },
    { path: '/runway/:slug', redirect: (to) => site(to.params.slug) },
    { path: '/cat3/metar', redirect: boardPath(DEFAULT_SYSTEM) },
    { path: '/dashboard', redirect: '/' },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
  scrollBehavior: () => ({ top: 0 }),
})

// Pages for Viewers and Admins need a session; a temporary password must be changed first (FR-AUTH-003).
router.beforeEach(async (to) => {
  const auth = useAuthStore()
  await auth.load()
  if (auth.me?.must_change_password && to.name !== 'password' && to.name !== 'login')
    return { name: 'password' }
  // Signed-in users skip the sign-in page and go where they were headed.
  if (to.name === 'login' && auth.me) {
    const next = typeof to.query.next === 'string' ? to.query.next : '/'
    return next.startsWith('/') && !next.startsWith('//') ? next : '/'
  }
  const need = to.meta.role
  if (!need) return true
  if (!auth.me) return { name: 'login', query: { next: to.fullPath } }
  if (need === 'admin' && !auth.isAdmin) return { name: 'forbidden' }
  return true
})
