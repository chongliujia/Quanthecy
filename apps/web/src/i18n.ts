import { useSyncExternalStore } from 'react'
import zh from './locales/zh'

export type Language = 'zh' | 'en'
const storageKey = 'quanthecy.language'
function initialLanguage(): Language {
  try { const value = localStorage.getItem(storageKey); if (value === 'en' || value === 'zh') return value } catch { /* Storage can be unavailable. */ }
  return 'zh'
}
let language = initialLanguage()
const listeners = new Set<() => void>()
export function setLanguage(next: Language) {
  language = next
  document.documentElement.lang = next === 'zh' ? 'zh-CN' : 'en'
  try { localStorage.setItem(storageKey, next) } catch { /* Language still works without storage. */ }
  listeners.forEach((listener) => listener())
}
function subscribe(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener) } }
export function useLanguage() { return useSyncExternalStore(subscribe, () => language) }
export function locale() { return language === 'zh' ? 'zh-CN' : 'en-US' }
export function t(key: string, values: Record<string, string | number> = {}) {
  const message = language === 'zh' ? zh[key] ?? key : key
  return message.replace(/\{(\w+)\}/g, (match, name: string) => String(values[name] ?? match))
}
document.documentElement.lang = language === 'zh' ? 'zh-CN' : 'en'
