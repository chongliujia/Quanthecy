import { t, locale } from './i18n'
export function probability(value: number | null | undefined) { return value == null ? t('Unavailable') : `${(value * 100).toFixed(2)}%` }
// Color follows the displayed precision, so rounded zero is always neutral.
export function valueTone(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return ''
  const displayed = Number(value.toFixed(2))
  return displayed > 0 ? 'positive' : displayed < 0 ? 'negative' : ''
}
export function changeTone(value: number | null | undefined, stale = false) {
  return stale || value == null ? '' : valueTone(value * 100)
}
export function change(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return t('Unavailable')
  const displayed = Number((value * 100).toFixed(2))
  return `${displayed > 0 ? '+' : ''}${displayed.toFixed(2)} pp`
}
export function time(value: string | null | undefined) { return value ? new Date(value).toLocaleString(locale()) : t('Unknown') }
export function readable(value: string) { return t(value.toLowerCase().replaceAll('_', ' ')) }
