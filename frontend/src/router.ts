import { createRouter, createWebHistory } from 'vue-router'
import { DEFAULT_SYSTEM } from '@/stores/problems'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'overview', component: () => import('@/views/OverviewView.vue') },
    {
      path: '/systems/:code',
      name: 'system',
      component: () => import('@/views/SystemView.vue'),
      props: true,
    },
    {
      path: '/systems/:code/sites/:slug',
      name: 'site',
      component: () => import('@/views/SiteView.vue'),
      props: true,
    },
    { path: '/internal/health', name: 'health', component: () => import('@/views/HealthView.vue') },

    // v2 paths keep working after cutover (PRD §14.4)
    { path: '/cat3', redirect: `/systems/${DEFAULT_SYSTEM}` },
    { path: '/cat3/system', redirect: `/systems/${DEFAULT_SYSTEM}` },
    {
      path: '/cat3/runway/:slug',
      redirect: (to) => `/systems/${DEFAULT_SYSTEM}/sites/${String(to.params.slug)}`,
    },
    { path: '/runway/:slug', redirect: (to) => `/systems/${DEFAULT_SYSTEM}/sites/${String(to.params.slug)}` },
    { path: '/cat3/metar', redirect: `/systems/${DEFAULT_SYSTEM}` },
    { path: '/dashboard', redirect: `/systems/${DEFAULT_SYSTEM}` },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
  scrollBehavior: () => ({ top: 0 }),
})
