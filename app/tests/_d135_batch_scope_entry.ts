/** D135：packs store 的单测入口（自带 pinia，避免两份实例）。 */
import { createPinia, setActivePinia } from 'pinia'
import { usePackStore } from '../src/stores/packs'

export function makeStore() {
  setActivePinia(createPinia())
  return usePackStore()
}
