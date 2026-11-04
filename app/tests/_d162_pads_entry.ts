import { createPinia, setActivePinia } from 'pinia'
import { useTaskpadStore } from '../src/stores/taskpad'
import { usePackStore } from '../src/stores/packs'

export function makeStores() {
  setActivePinia(createPinia())
  return { pads: useTaskpadStore(), packs: usePackStore() }
}
