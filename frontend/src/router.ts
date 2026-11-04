import { createRouter, createWebHistory } from 'vue-router'

declare module 'vue-router' {
  interface RouteMeta {
    wall?: boolean
  }
}

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'board', component: () => import('@/views/BoardView.vue') },
    { path: '/sites/:slug', name: 'site', component: () => import('@/views/SiteView.vue'), props: true },
    // Wall screen / TV: current month, no controls, larger type, refreshes itself.
    {
      path: '/wall',
      name: 'wall',
      component: () => import('@/views/BoardView.vue'),
      props: { wall: true },
      meta: { wall: true },
    },
    { path: '/internal/health', name: 'health', component: () => import('@/views/HealthView.vue') },

    // Earlier SIMOLA and v2 paths (PRD §14.4)
    { path: '/systems/:code', redirect: '/' },
    { path: '/systems/:code/sites/:slug', redirect: (to) => `/sites/${String(to.params.slug)}` },
    { path: '/cat3', redirect: '/' },
    { path: '/cat3/system', redirect: '/' },
    { path: '/cat3/runway/:slug', redirect: (to) => `/sites/${String(to.params.slug)}` },
    { path: '/runway/:slug', redirect: (to) => `/sites/${String(to.params.slug)}` },
    { path: '/cat3/metar', redirect: '/' },
    { path: '/dashboard', redirect: '/' },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
  scrollBehavior: () => ({ top: 0 }),
})
