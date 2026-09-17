import type { Observation } from './marketTypes'

export type ChartPoint = [number, number | null]
export function validQuote(row: Observation) {
  return row.best_bid != null && row.best_ask != null && Number.isFinite(row.best_bid) && Number.isFinite(row.best_ask) && row.best_bid >= 0 && row.best_ask <= 1 && row.best_bid <= row.best_ask && !row.quality_flags.some((flag) => ['CROSSED_BOOK', 'STALE', 'OUT_OF_ORDER'].includes(flag))
}
export function chartData(rows: Observation[]) {
  const probability: ChartPoint[] = [], spread: ChartPoint[] = [], volume: ChartPoint[] = [], bid: ChartPoint[] = [], ask: ChartPoint[] = [], band: ChartPoint[] = []
  const units = new Set(rows.flatMap((r) => r.volume ? [r.volume.unit] : []))
  const volumeUnit = units.size === 1 ? [...units][0] : null
  rows.forEach((row, index) => {
    const at = Date.parse(row.received_at), previous = rows[index - 1]
    const elapsed = previous ? at - Date.parse(previous.received_at) : 0
    const gap = !!previous && (elapsed > 150000 || elapsed <= 0 || row.quality_flags.includes('GAP'))
    if (gap) {
      const middle = at - elapsed / 2
      probability.push([middle, null]); spread.push([middle, null]); bid.push([middle, null]); ask.push([middle, null]); band.push([middle, null])
    }
    probability.push([at, row.probability == null ? null : row.probability.value * 100])
    const quoted = validQuote(row), width = quoted ? (row.best_ask! - row.best_bid!) * 100 : null
    bid.push([at, quoted ? row.best_bid! * 100 : null]); ask.push([at, quoted ? row.best_ask! * 100 : null]); band.push([at, width])
    spread.push([at, width])
    const currentVolume = row.volume, previousVolume = previous?.volume
    const validVolume = !gap && volumeUnit && currentVolume && previousVolume && currentVolume.unit === previousVolume.unit && currentVolume.basis === previousVolume.basis && currentVolume.value >= previousVolume.value
    volume.push([at, validVolume ? currentVolume.value - previousVolume.value : null])
  })
  return { probability, spread, volume, volumeUnit, bid, ask, band }
}

// Five-minute display buckets retain every underlying item for drill-down.
export function eventBuckets<T>(items: T[], timestamp: (item: T) => string): T[][] {
  const buckets = new Map<number, T[]>()
  for (const item of items) {
    const at = Date.parse(timestamp(item))
    if (!Number.isFinite(at)) continue
    const key = Math.floor(at / 300000)
    buckets.set(key, [...(buckets.get(key) ?? []), item])
  }
  return [...buckets.entries()].sort(([a], [b]) => a - b).map(([, values]) => values.sort((a, b) => Date.parse(timestamp(a)) - Date.parse(timestamp(b))))
}
export function chartNumber(value: number | null | undefined, unit = '') {
  return value == null || !Number.isFinite(value) ? '—' : `${Number(value.toFixed(2)).toLocaleString('en', { maximumFractionDigits: 2 })}${unit}`
}
export function probabilityBounds(values: (number | null)[]) {
  const valid = values.filter((value): value is number => value != null && Number.isFinite(value))
  if (!valid.length) return { min: 0, max: 100 }
  const low = Math.min(...valid), high = Math.max(...valid), padding = Math.max((high - low) * .1, .5)
  return { min: Math.max(0, Math.floor((low - padding) * 100) / 100), max: Math.min(100, Math.ceil((high + padding) * 100) / 100) }
}
