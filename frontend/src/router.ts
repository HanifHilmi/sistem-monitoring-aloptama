import { createRouter, createWebHistory } from 'vue-router'
import { DEFAULT_SYSTEM } from '@/stores/live'
import { boardPath, sitePath } from '@/utils/paths'

declare module 'vue-router' {
  interface RouteMeta {
    wall?: boolean
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
    { path: '/internal/health', name: 'health', component: () => import('@/views/HealthView.vue') },

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
