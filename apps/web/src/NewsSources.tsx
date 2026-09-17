import { t } from './i18n'
import { time } from './format'
import type { Source } from './researchTypes'

const statuses: Record<Source['status'], string> = {
  healthy: 'Collection healthy', partial: 'Some entries need attention', empty: 'No usable entries',
  retrying: 'Collection retrying', stale: 'Collection overdue', pending: 'Awaiting first collection', paused: 'Collection paused',
}

export function SourceStatus({ source }: { source: Source }) {
  return <span className={`badge ${source.status === 'healthy' ? '' : 'badge-amber'}`}>{t(statuses[source.status])}</span>
}

export default function NewsSources({ sources, pollingEnabled }: { sources: Source[]; pollingEnabled: boolean }) {
  return <details className="panel news-sources">
    <summary>{t('News source coverage')} · {sources.length}</summary>
    <p className="quiet">{t('Current collection status. Polling frequency is not a delivery guarantee; publication and collection times are separate.')}</p>
    {!pollingEnabled && <p className="data-warning">{t('News polling is paused.')}</p>}
    <div className="table-scroll"><table><thead><tr><th>{t('Source')}</th><th>{t('Source type')}</th><th>{t('Status')}</th><th>{t('Poll interval')}</th><th>{t('Last success:')}</th><th>{t('Latest publication')}</th><th>{t('Accepted / rejected / duplicates')}</th></tr></thead>
      <tbody>{sources.map(source => <tr key={source.slug}>
        <td><a href={source.url} target="_blank" rel="noopener noreferrer">{t(source.name)} ↗</a>{source.error && <small className="error">{source.error}</small>}</td>
        <td>{t(source.kind === 'OFFICIAL' ? 'Official' : source.kind === 'MEDIA' ? 'Media' : 'Unknown source type')}</td>
        <td><SourceStatus source={source} /></td><td>{t('{count} minutes', { count: Math.round(source.poll_interval_seconds / 60) })}</td>
        <td>{time(source.last_success_at)}</td><td>{time(source.latest_published_at)}</td>
        <td>{source.last_entry_count} / {source.last_rejected_count} / {source.last_duplicate_count}{source.last_undated_count > 0 && <small>{t('{count} entries without publication time', { count: source.last_undated_count })}</small>}</td>
      </tr>)}</tbody></table></div>
  </details>
}
