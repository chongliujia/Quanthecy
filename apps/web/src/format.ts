import { t, locale } from './i18n'
export function probability(value: number | null | undefined) { return value == null ? t('Unavailable') : `${(value * 100).toFixed(2)}%` }
export function change(value: number | null | undefined) { return value == null ? t('Unavailable') : `${value > 0 ? '+' : ''}${(value * 100).toFixed(2)} pp` }
export function time(value: string | null | undefined) { return value ? new Date(value).toLocaleString(locale()) : t('Unknown') }
export function readable(value: string) { return t(value.toLowerCase().replaceAll('_', ' ')) }
