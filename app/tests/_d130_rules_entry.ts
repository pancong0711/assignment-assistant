/** D130-T9 浏览器回归入口：挂载**真实的** GradingRulesCard.vue（非复刻）。 */
import { createApp, h } from 'vue'
import GradingRulesCard from './.d130-card.ts'

const addr = (window as any).__ENGINE_ADDR__ || ''
const app = createApp({
  render: () => h(GradingRulesCard, { engineAddr: addr, token: '' }),
})
app.mount('#app')
;(window as any).__ready = true
