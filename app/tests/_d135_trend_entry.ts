/** D135：挂载**真实** TrendCard（连真实引擎 /grade/trend）。 */
import { createApp, h } from 'vue'
import { createPinia } from 'pinia'
import TrendCard from './.d135-trend.ts'

const addr = (window as any).__ENGINE_ADDR__ || ''
const classDir = (window as any).__CLASS_DIR__ || ''
const app = createApp({
  render: () => h(TrendCard, { engineAddr: addr, token: '', classDir, reloadKey: 0 }),
})
app.use(createPinia())
app.mount('#app')
;(window as any).__ready = true
