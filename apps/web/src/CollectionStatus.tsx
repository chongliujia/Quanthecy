import { t } from './i18n'
import { useCollectionStatus, age, collectionLabels, collectionExplanations } from './collectionHealth'
import { time } from './format'

const reasons: Record<string, string> = { network: 'Exchange connection failed', rate_limited: 'Exchange rate limit', exchange: 'Exchange request rejected', invalid_data: 'Invalid exchange response', storage: 'Persistence interrupted' }
export default function CollectionStatus({ userId }: { userId: string }) {
  const query = useCollectionStatus(userId)
  if (query.isPending) return <div className="collection-strip" role="status">{t("Checking market data sources…")}</div>
  if (query.error) return <div className="collection-strip degraded" role="status">{t("Source status unavailable")} <button onClick={() => void query.refetch()}>{t("Retry status")}</button></div>
  return <div className="collection-strip" aria-label={t("Market data sources")}>
    <span className="collection-label">{t("DATA SOURCES")}</span>
    {query.data?.sources?.map((source) => <details className={`source-health ${source.run_state && source.run_state !== 'active' || source.state !== 'recent' || source.error_code ? 'degraded' : ''}`} key={source.platform}>
      <summary><i /><strong>{source.platform}</strong><span>{source.run_state ? t(collectionLabels[source.run_state]) : source.error_code ? t("Request failed") : source.state === 'recent' ? t("Collecting") : source.state === 'delayed' ? t("Delayed") : t("No data")}</span><time title={time(source.latest_observation)}>{age(source.delay_seconds)}</time></summary>
      <div className="source-health-detail"><strong>{source.error_code ? t(reasons[source.error_code] ?? 'Collection interrupted') : source.state === 'recent' ? t("Recent observations available") : t("No recent observations received")}</strong>{source.run_state && collectionExplanations[source.run_state] && <p>{t(collectionExplanations[source.run_state])}</p>}<p>{t("Last observation:")} {time(source.latest_observation)}</p><p>{source.fresh_markets} {t("fresh open markets /")} {source.total_markets} {t("collected")}</p><p>{source.collector_checked_at ? t('Last collection attempt: {time}', { time: time(source.collector_checked_at) }) : t("Collector diagnostics unavailable. Freshness is based on saved observations.")}</p>{source.managed && <p>{t('Enabled targets: {count}. Requested revision: {desired}; acknowledged revision: {applied}.', { count: source.enabled_targets ?? 0, desired: source.desired_revision ?? '—', applied: source.applied_revision ?? '—' })}</p>}<small>{t("REST snapshots · Status checked")} {time(query.data.checked_at)}</small></div>
    </details>)}
  </div>
}
