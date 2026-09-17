import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './api'
import { t } from './i18n'
import { directionLabels } from './watchlistTypes'
import { probability, time } from './format'
import { ErrorNotice } from './ResearchUI'
import TerminalDialog from './TerminalDialog'
import type { AlertDetail, AlertPage } from './watchlistTypes'

export default function AlertInbox({ userId, organizationId, marketId }: { userId: string; organizationId: string; marketId?: string }) {
  const client = useQueryClient()
  const [unread, setUnread] = useState(false)
  const [offset, setOffset] = useState(0)
  const [selected, setSelected] = useState('')
  const query = useQuery({ queryKey: ['alerts', userId, organizationId, marketId, unread, offset],
    queryFn: () => api<AlertPage>(`/organizations/${organizationId}/alerts?limit=20&offset=${offset}&unread_only=${unread}${marketId ? `&market_id=${marketId}` : ''}`), refetchInterval: 30000 })
  const read = useMutation({ mutationFn: ({ id, value }: { id: string; value: boolean }) => api(`/organizations/${organizationId}/alerts/${id}/read`, 'PATCH', { read: value }),
    onSuccess: () => client.invalidateQueries({ queryKey: ['alerts', userId, organizationId] }) })
  return <section className="alert-inbox" aria-label={t('Alert inbox')}>
    <div className="watch-heading"><span>{t('{count} unread alerts', { count: query.data?.unread ?? 0 })}</span><label className="watch-check"><input type="checkbox" checked={unread} onChange={e => { setUnread(e.target.checked); setOffset(0) }} />{t('Unread only')}</label></div>
    <p className="quiet">{t('In-app alerts from new eligible observations. No automatic model requests.')}</p>
    {query.isPending && <p role="status">{t('Loading alerts…')}</p>}
    {query.error && <ErrorNotice error={query.error} retry={() => void query.refetch()} />}
    {read.error && <p role="alert" className="error">{t(read.error.message)}</p>}
    <div className="watch-scroll">
      {query.data?.items.length === 0 && <div className="watch-empty"><h3>{t('No alerts in this view')}</h3><p>{t('Create a watchlist rule. Alerts appear after fresh, complete data meets its condition.')}</p></div>}
      {query.data?.items.map(event => <article key={event.id} className={`alert-row ${event.is_read ? '' : 'unread'}`}>
        <div className="watch-heading"><strong>{event.rule_name}</strong><span className="numeric">{event.value_pp > 0 ? '+' : ''}{event.value_pp.toFixed(2)} pp</span></div>
        <a href={`#/markets/${event.market_id}`}>{event.title}</a>
        <small>{event.platform} · {t('{minutes} minute window', { minutes: event.window_minutes })} · {time(event.observed_at)}</small>
        <div className="watch-actions"><button onClick={() => setSelected(event.id)}>{t('Trigger details')}</button><button className="text-button" disabled={read.isPending} onClick={() => read.mutate({ id: event.id, value: !event.is_read })}>{event.is_read ? t('Mark unread') : t('Mark read')}</button></div>
      </article>)}
    </div>
    {query.data && query.data.total > 20 && <div className="pagination"><button disabled={!offset} onClick={() => setOffset(offset - 20)}>{t('Previous')}</button><span>{offset + 1}–{Math.min(offset + 20, query.data.total)} / {query.data.total}</span><button disabled={offset + 20 >= query.data.total} onClick={() => setOffset(offset + 20)}>{t('Next')}</button></div>}
    <TerminalDialog open={!!selected} onClose={() => setSelected('')} title={t('Alert trigger details')} className="alert-detail-dialog">
      {selected && <TriggerDetails key={`${organizationId}-${selected}`} userId={userId} organizationId={organizationId} id={selected} />}
    </TerminalDialog>
  </section>
}

function TriggerDetails({ userId, organizationId, id }: { userId: string; organizationId: string; id: string }) {
  const query = useQuery({ queryKey: ['alert-detail', userId, organizationId, id], queryFn: () => api<AlertDetail>(`/organizations/${organizationId}/alerts/${id}`) })
  if (query.isPending) return <p role="status">{t('Loading alert inputs…')}</p>
  if (query.error) return <ErrorNotice error={query.error} retry={() => void query.refetch()} />
  if (!query.data) return null
  const event = query.data, calculation = event.snapshot.calculation
  const knownAt = calculation.inputs.reduce((latest, input) => Date.parse(input.recorded_at) > Date.parse(latest) ? input.recorded_at : latest, event.observed_at)
  return <div className="watch-form"><h3>{event.title}</h3><p>{event.rule_name} · {t('Rule revision')} {event.revision}</p>
    <p>{t(event.kind === 'PROBABILITY_MOVE' ? 'Midpoint change' : 'Spread widening')} · {t(directionLabels[event.direction])} · {t('Threshold')} {event.threshold_pp.toFixed(2)} pp · {t('Observed change')} {event.value_pp.toFixed(2)} pp</p>
    <p>{time(calculation.window_start)} → {time(calculation.window_end)}</p><small>{calculation.version} · {calculation.inputs.length} {t('saved quote inputs')}</small>
    <p className="quiet">{t('These are frozen normalized quotes, not executable prices. The condition was observed at a sample; crossing time between samples is unknown.')}</p>
    <div className="table-scroll"><table><thead><tr><th>{t('Observed time')}</th><th>{t('Midpoint')}</th><th>{t('Bid')}</th><th>{t('Ask')}</th></tr></thead><tbody>{calculation.inputs.map(input => <tr key={input.observation_id}><td>{time(input.received_at)}</td><td>{probability(input.probability.value)}</td><td>{probability(input.best_bid)}</td><td>{probability(input.best_ask)}</td></tr>)}</tbody></table></div>
    <details><summary>{t('Frozen calculation and provenance')}</summary><pre className="alert-json">{JSON.stringify(event.snapshot, null, 2)}</pre></details>
    <a href={`#/markets/${event.market_id}?cutoff=${encodeURIComponent(knownAt)}`}>{t('Open market at trigger time →')}</a>
  </div>
}
