import { useSyncExternalStore } from 'react'

export type Theme = 'light' | 'dark'
export type ThemePreference = Theme | 'system'
const storageKey = 'quanthecy.theme'
const media = window.matchMedia('(prefers-color-scheme: dark)')
const listeners = new Set<() => void>()

function preference(value: string | null): ThemePreference {
  return value === 'light' || value === 'dark' ? value : 'system'
}
function savedPreference(): ThemePreference {
  try { return preference(localStorage.getItem(storageKey)) } catch { return 'system' }
}
function resolve(value: ThemePreference): Theme {
  return value === 'system' ? media.matches ? 'dark' : 'light' : value
}
let state = { preference: savedPreference(), theme: 'light' as Theme }
state.theme = resolve(state.preference)

function apply() {
  document.documentElement.dataset.theme = state.theme
  document.documentElement.style.colorScheme = state.theme
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', state.theme === 'dark' ? '#0b1018' : '#f4f7fb')
}
function update(value: ThemePreference) {
  const theme = resolve(value)
  if (state.preference === value && state.theme === theme) return
  state = { preference: value, theme }
  apply()
  listeners.forEach((listener) => listener())
}
function onSystemChange() { if (state.preference === 'system') update('system') }
function onStorage(event: StorageEvent) {
  if (event.key === storageKey || event.key === null) update(preference(event.newValue))
}
function subscribe(listener: () => void) {
  if (!listeners.size) {
    media.addEventListener('change', onSystemChange)
    window.addEventListener('storage', onStorage)
    update(savedPreference())
  }
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
    if (!listeners.size) {
      media.removeEventListener('change', onSystemChange)
      window.removeEventListener('storage', onStorage)
    }
  }
}
export function setThemePreference(value: ThemePreference) {
  try { localStorage.setItem(storageKey, value) } catch { /* Switching still works when storage is blocked. */ }
  update(value)
}
export function useTheme() { return useSyncExternalStore(subscribe, () => state) }
apply()
