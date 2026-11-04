/** D134-T3e：挂载**真实** MaterialsView（含 pinia + 真实引擎地址）。 */
import { createApp, h } from 'vue'
import { createPinia } from 'pinia'
import MaterialsView from './.d134-materials.ts'
import { useSettingsStore } from '../src/stores/settings'

const addr = (window as any).__ENGINE_ADDR__ || ''
const app = createApp({ render: () => h(MaterialsView) })
const pinia = createPinia()
app.use(pinia)
// MaterialsView 通过 settings.engineUrl 取数（真实 App 里是用户配置）
useSettingsStore(pinia).engineUrl = addr
app.mount('#app')
;(window as any).__ready = true
