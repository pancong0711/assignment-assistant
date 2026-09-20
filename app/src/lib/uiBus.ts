/** 极简事件总线：视图 → App 横幅等跨层通信（无需引入依赖库）。 */
type Handler = (payload: string) => void

const handlers = new Map<string, Set<Handler>>()

export function on(event: string, fn: Handler): () => void {
  const set = handlers.get(event) ?? new Set<Handler>()
  set.add(fn)
  handlers.set(event, set)
  return () => { set.delete(fn) }
}

export function emit(event: string, payload: string): void {
  for (const fn of handlers.get(event) ?? []) fn(payload)
}
