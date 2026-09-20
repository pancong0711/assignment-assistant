import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import './styles.css'

const app = createApp(App)
app.use(createPinia())
app.mount('#app')

// PWA：仅生产注册 service worker（离线缓存静态资源）
if (import.meta.env.PROD && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('./sw.js').catch(() => {
      // 离线缓存注册失败不阻塞页面（如非 https/localhost）
    })
  })
}
