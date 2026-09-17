import type { Market } from './marketTypes'

// Fixed color scale: equal tile areas, saturation at ±5 percentage points.
export function heatmapValue(market: Market, now: number) {
  const age = now - Date.parse(market.last_observed_at)
  const value = market.metrics.probability_change_15m
  const stale = market.stale || !Number.isFinite(age) || age < 0 || age > 180000
  const usable = !stale && market.status === 'OPEN' && market.data_quality?.price_usable === true && value != null && Number.isFinite(value)
  return { value: usable ? value : null, state: stale ? 'stale' : usable ? 'ready' : 'unavailable', intensity: usable ? Math.min(Math.abs(value) / .05, 1) : 0 }
}
