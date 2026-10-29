// Hash routing: a handful of screens do not need a router dependency, and hash URLs survive a
// static host with no rewrite rules.
import { useSyncExternalStore } from 'react'

export type Route =
  | { name: 'home' }
  | { name: 'practice'; scenarioId: string }
  | { name: 'report'; reportId: string }
  | { name: 'latency' }
  | { name: 'team' }
  | { name: 'rate' }
  | { name: 'rateItem'; itemId: string }

export function parse(hash: string): Route {
  const parts = hash.replace(/^#\/?/, '').split('/').filter(Boolean)
  if (parts[0] === 'practice' && parts[1]) return { name: 'practice', scenarioId: parts[1] }
  if (parts[0] === 'report' && parts[1]) return { name: 'report', reportId: parts[1] }
  if (parts[0] === 'latency') return { name: 'latency' }
  if (parts[0] === 'team') return { name: 'team' }
  if (parts[0] === 'rate' && parts[1]) return { name: 'rateItem', itemId: parts[1] }
  if (parts[0] === 'rate') return { name: 'rate' }
  return { name: 'home' }
}

export function navigate(path: string) {
  window.location.hash = path
}

export function useRoute(): Route {
  const hash = useSyncExternalStore(
    (fn) => (window.addEventListener('hashchange', fn), () => window.removeEventListener('hashchange', fn)),
    () => window.location.hash,
  )
  return parse(hash)
}
