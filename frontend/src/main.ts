import { createPinia } from 'pinia'
import { createApp } from 'vue'
import App from './App.vue'
import { currentLocale, i18n } from './i18n'
import { router } from './router'
import './styles/main.css'

// Sample-data mode for design work without a backend (VITE_MOCK=1). Never part of production builds.
if (import.meta.env.VITE_MOCK === '1') {
  const { installMocks } = await import('./mocks/install')
  installMocks()
}

document.documentElement.lang = currentLocale()
createApp(App).use(createPinia()).use(router).use(i18n).mount('#app')
