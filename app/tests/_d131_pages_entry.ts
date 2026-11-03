/** D126-B / D131 浏览器回归入口：挂载**真实的** TeacherReportCard 与 MaterialsView。 */
import { createApp, h, ref } from 'vue'
import { createPinia } from 'pinia'
import TeacherReportCard from './.d126b-teacher.ts'
import MaterialsView from './.d131-materials.ts'
import { useSettingsStore } from '../src/stores/settings'

const addr = (window as any).__ENGINE_ADDR__ || ''
const which = (window as any).__WHICH__ || 'teacher'
const props = (window as any).__PROPS__ || {}

const app = createApp({
  setup() {
    if (which === 'teacher') {
      const key = ref(0)
      return () => h('div', [
        h(TeacherReportCard, { engineAddr: addr, token: '', classDir: props.classDir,
                               taskId: props.taskId, reloadKey: key.value }),
      ])
    }
    // MaterialsView 用 useSettingsStore() → 必须有 pinia（与真实 App 一致）
    return () => h(MaterialsView)
  },
})
const pinia = createPinia()
app.use(pinia)
// MaterialsView 用 settings.engineUrl 取数；测试里把 store 指到真实引擎临时端口
// （真实 App 里这是用户配置，这里不设就等于打默认端口 → Failed to fetch）
useSettingsStore(pinia).engineUrl = addr
app.mount('#app')
;(window as any).__ready = true
