import { useEffect, useRef, useState, useSyncExternalStore, type KeyboardEvent, type PointerEvent } from 'react'

export function useCompactScreen() {
  return useSyncExternalStore((listener) => {
    const media = window.matchMedia('(max-width: 1100px)')
    media.addEventListener('change', listener)
    return () => media.removeEventListener('change', listener)
  }, () => window.matchMedia('(max-width: 1100px)').matches, () => false)
}
export function useLayoutPreference<T>(key: string, fallback: T, valid: (value: unknown) => value is T) {
  const [value, setValue] = useState<T>(() => {
    try { const stored: unknown = JSON.parse(localStorage.getItem(key) ?? 'null'); return valid(stored) ? stored : fallback } catch { return fallback }
  })
  useEffect(() => { try { localStorage.setItem(key, JSON.stringify(value)) } catch { /* Private browsing may disable storage. */ } }, [key, value])
  return [value, setValue] as const
}
export function usePanelResize(key: string, initial: number, min: number, max: number, axis: 'x' | 'y', reverse = false) {
  const [size, setSize] = useLayoutPreference(key, initial, (value): value is number => typeof value === 'number' && Number.isFinite(value) && value >= min && value <= max)
  const drag = useRef<{ at: number; size: number } | null>(null)
  const clamp = (value: number) => Math.min(max, Math.max(min, value))
  return { size, separator: {
    role: 'separator' as const, tabIndex: 0, 'aria-orientation': axis === 'x' ? 'vertical' as const : 'horizontal' as const,
    'aria-valuenow': Math.round(size), 'aria-valuemin': min, 'aria-valuemax': max,
    onPointerDown: (event: PointerEvent<HTMLDivElement>) => { if (event.button !== 0) return; event.preventDefault(); event.currentTarget.setPointerCapture(event.pointerId); drag.current = { at: axis === 'x' ? event.clientX : event.clientY, size } },
    onPointerMove: (event: PointerEvent<HTMLDivElement>) => { if (drag.current) setSize(clamp(drag.current.size + ((axis === 'x' ? event.clientX : event.clientY) - drag.current.at) * (reverse ? -1 : 1))) },
    onPointerUp: () => { drag.current = null }, onLostPointerCapture: () => { drag.current = null },
    onKeyDown: (event: KeyboardEvent<HTMLDivElement>) => {
      const negative = axis === 'x' ? 'ArrowLeft' : 'ArrowUp', positive = axis === 'x' ? 'ArrowRight' : 'ArrowDown'
      if ([negative, positive, 'Home', 'End'].includes(event.key)) { event.preventDefault(); setSize(event.key === 'Home' ? min : event.key === 'End' ? max : clamp(size + (event.key === positive ? 16 : -16) * (reverse ? -1 : 1))) }
    },
    onDoubleClick: () => setSize(initial),
  } }
}
