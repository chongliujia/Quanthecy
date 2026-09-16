import { t } from './i18n'
import type { Signal } from './marketTypes'
import { change } from './format'

export function signalValue(signal: Signal) {
  if (signal.signal_type === 'VOLUME_SPIKE') return { value: signal.metrics.volume_zscore?.toFixed(2) ?? t('Unavailable'), label: t('Volume-rate z-score'), tone: 'caution' }
  const spread = signal.signal_type === 'SPREAD_WIDENING'
  const value = spread ? signal.metrics.spread_change_15m : signal.metrics.probability_change_15m
  return { value: change(value), label: spread ? t('15-minute spread change') : t('15-minute probability change'), tone: value == null ? '' : spread ? 'caution' : value < 0 ? 'negative' : 'positive' }
}
