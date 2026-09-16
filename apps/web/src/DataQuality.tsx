import { t } from './i18n'
import type { ResearchQuality } from './marketTypes'
import { qualityReasons } from './qualityReasons'

export default function DataQuality({ quality }: { quality?: ResearchQuality }) {
  if (!quality) return null
  const label = quality.state === 'ready' ? 'Both indicators available' : quality.state === 'limited' ? 'Some indicators unavailable' : 'Research indicators unavailable'
  return <details className={`data-quality quality-${quality.state}`}>
    <summary>{t('Data quality')} · {t(label)}</summary>
    <p>{t('Price change')}: {t(quality.price_usable ? 'Available' : 'Not computable')} · {t('Volume anomaly')}: {t(quality.volume_usable ? 'Available' : 'Not computable')}</p>
    {quality.reasons.length > 0 && <ul>{quality.reasons.map((reason) => <li key={reason}>{t(qualityReasons[reason] ?? reason)}</li>)}</ul>}
    <p>{t('Based on the latest processed 15-minute window and freshness at the research time.')}</p>
    <p>{t('Known limitations')}: {quality.limitations.map((reason) => t(qualityReasons[reason] ?? reason)).join(' · ') || '—'}</p>
    <small>{t('Data eligibility does not measure forecast accuracy.')}</small>
  </details>
}
