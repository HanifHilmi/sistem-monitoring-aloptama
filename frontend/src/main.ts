import { createPinia } from 'pinia'
import { createApp } from 'vue'
import App from './App.vue'
import { i18n, currentLocale } from './i18n'
import { router } from './router'
import './styles/main.css'

document.documentElement.lang = currentLocale()
createApp(App).use(createPinia()).use(router).use(i18n).mount('#app')
