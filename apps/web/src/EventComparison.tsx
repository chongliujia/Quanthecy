import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import { t, useLanguage } from './i18n'
import type { ResearchEvent } from './EventPages'
import type { EventChartData } from './eventChartTypes'
import { time } from './format'
import { ErrorNotice } from './ResearchUI'
import { withCutoff } from './navigation'
import EventProbabilityChart from './EventProbabilityChart'

export default function EventComparison({ userId, marketId, platform, cutoff }: { userId: string; marketId: string; platform: string; cutoff: string }) {
  const language = useLanguage()
  const [chosen, setChosen] = useState('')
  const events = useQuery({ queryKey: ['market-events', userId, marketId, cutoff], queryFn: () => api<ResearchEvent[]>(`/research/events?market_id=${marketId}${cutoff ? `&cutoff=${encodeURIComponent(cutoff)}` : ''}`) })
  const event = events.data?.find((item) => item.slug === chosen) ?? events.data?.[0]
  return <section className="chart-panel event-comparison" aria-label={t('Event comparison')}>
    {events.error && <ErrorNotice error={events.error} retry={() => void events.refetch()} />}
    {events.isPending && <p role="status" className="analytics-note">{t('Loading events…')}</p>}
    {events.data?.length === 0 && <div className="chart-empty"><h3>{t('No linked research event')}</h3><p>{t('An operator must link contracts to an event before they can be compared here.')}</p></div>}
    {event && <><div className="event-chart-heading"><select aria-label={t('Research event')} value={event.slug} onChange={(e) => setChosen(e.target.value)}>{events.data?.map((item) => <option key={item.id} value={item.slug}>{language === 'zh' && item.title_zh || item.title}</option>)}</select><a href={`#${withCutoff(`/events/${event.slug}`, cutoff)}`}>{t('Event dossier →')}</a></div><EventSeries key={`${event.slug}:${cutoff}`} userId={userId} slug={event.slug} initialPlatform={platform} cutoff={cutoff} /></>}
  </section>
}

function EventSeries({ userId, slug, initialPlatform, cutoff }: { userId: string; slug: string; initialPlatform: string; cutoff: string }) {
  const [platform, setPlatform] = useState(initialPlatform)
  const [hours, setHours] = useState(6)
  const [selection, setSelection] = useState<string[] | null>(null)
  const [view, setView] = useState<'history' | 'latest'>('history')
  const query = useQuery({ queryKey: ['event-chart', userId, slug, cutoff, hours, platform, selection], queryFn: () => api<EventChartData>(`/research/events/${slug}/chart?hours=${hours}&platform=${platform}&market_ids=${selection?.join(',') ?? ''}${cutoff ? `&cutoff=${encodeURIComponent(cutoff)}` : ''}`), refetchInterval: cutoff ? false : 60000 })
  const selected = selection ?? query.data?.series.map((line) => line.market_id) ?? []
  return <>
    <div className="chart-toolbar analytics-toolbar"><div className="interval-switch" role="group" aria-label={t('Event chart window')}>{[1, 6, 24].map((h) => <button key={h} aria-pressed={hours === h} onClick={() => setHours(h)}>{h === 24 ? '1D' : `${h}H`}</button>)}</div><div className="interval-switch" role="group" aria-label={t('Event chart platform')}>{[['', 'All'], ['polymarket', 'Polymarket'], ['kalshi', 'Kalshi']].map(([value, label]) => <button key={value} aria-pressed={platform === value} onClick={() => { setPlatform(value); setSelection(null) }}>{t(label)}</button>)}</div><div className="interval-switch" role="group" aria-label={t('Event chart view')}><button aria-pressed={view === 'history'} onClick={() => setView('history')}>{t('History')}</button><button aria-pressed={view === 'latest'} onClick={() => setView('latest')}>{t('At cutoff')}</button></div></div>
    <p className="analytics-note">{t('Linked contracts may overlap or settle differently. Values are not normalized to 100%.')}</p>
    {query.isPending && <p role="status" className="analytics-note">{t('Loading aligned quotes…')}</p>}
    {query.error && <ErrorNotice error={query.error} retry={() => void query.refetch()} />}
    {query.data && <><EventProbabilityChart data={query.data} view={view} selected={selected} onSelection={setSelection} />{(query.data.contracts_truncated || query.data.series.some((line) => line.truncated)) && <p className="analytics-note">{t('Chart coverage is bounded. Shorten the window or select fewer contracts.')}</p>}<div className="analytics-footer"><span>{t('60-second grid · quotes up to 90 seconds old · gaps stay blank')}</span><span>{time(query.data.end)} · {selected.length} / 6 {t('contracts')}</span></div></>}
  </>
}
