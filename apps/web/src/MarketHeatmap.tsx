import { useEffect, useState, type CSSProperties } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, type Organization } from './api'
import { t } from './i18n'
import { useWatchlists } from './watchlistQueries'
import type { Market } from './marketTypes'
import { heatmapValue } from './heatmapData'
import { change, probability, time } from './format'
import { ErrorNotice } from './ResearchUI'

export default function MarketHeatmap({ userId, organization, watchlist, onWatchlistChange, onSelect }: {
  userId: string; organization?: Organization; watchlist: string; onWatchlistChange: (id: string) => void; onSelect: (id: string) => void;
}) {
  const lists = useWatchlists(userId, organization?.id)
  const [platform, setPlatform] = useState('')
  return <section className="chart-panel heatmap-panel" aria-label={t('Market heatmap')}>
    <div className="chart-toolbar analytics-toolbar"><label>{t('Scope')}<select aria-label={t('Heatmap watchlist')} value={watchlist} onChange={(e) => onWatchlistChange(e.target.value)}><option value="">{t('Collected sample')}</option>{lists.data?.map((list) => <option key={list.id} value={list.id}>{list.name}</option>)}</select></label><div className="interval-switch" role="group" aria-label={t('Heatmap platform')}>{[['', 'All'], ['polymarket', 'Polymarket'], ['kalshi', 'Kalshi']].map(([value, label]) => <button key={value} aria-pressed={platform === value} onClick={() => setPlatform(value)}>{t(label)}</button>)}</div></div>
    {lists.error && <ErrorNotice error={lists.error} retry={() => void lists.refetch()} />}
    <HeatmapTiles key={`${organization?.id}:${watchlist}:${platform}`} userId={userId} organization={organization} watchlist={watchlist} platform={platform} onSelect={onSelect} />
  </section>
}

function HeatmapTiles({ userId, organization, watchlist, platform, onSelect }: {
  userId: string; organization?: Organization; watchlist: string; platform: string; onSelect: (id: string) => void;
}) {
  const [offset, setOffset] = useState(0)
  const [now, setNow] = useState(Date.now)
  useEffect(() => { const timer = window.setInterval(() => setNow(Date.now()), 15000); return () => clearInterval(timer) }, [])
  const query = useQuery({ queryKey: ['heatmap', userId, organization?.id, watchlist, platform, offset], enabled: !watchlist || !!organization,
    queryFn: () => api<{ items: Market[]; total: number }>(`/markets?limit=60&offset=${offset}&sort=recent${platform ? `&platform=${platform}` : ''}${watchlist ? `&watchlist_id=${watchlist}&organization_id=${organization!.id}` : ''}`), refetchInterval: 30000 })
  return <>
    <div className="heatmap-key"><strong>{t('15-minute change · pp')}</strong><span className="heat-scale">−5 <i /> +5</span><span>{t('Equal tile sizes · gray means unavailable or unchanged')}</span></div>
    {query.error && <ErrorNotice error={query.error} retry={() => void query.refetch()} />}
    {query.isPending && <p role="status" className="analytics-note">{t('Loading markets…')}</p>}
    <div className="heatmap-tiles">{query.data?.items.map((market) => {
      const cell = heatmapValue(market, now)
      return <button key={market.id} className={`heatmap-tile ${cell.value != null && cell.value !== 0 ? cell.value > 0 ? 'heat-up' : 'heat-down' : 'heat-neutral'}`} style={{ '--heat-strength': `${12 + cell.intensity * 34}%` } as CSSProperties} onClick={() => onSelect(market.id)} title={`${market.title}\n${t('Last observed')}: ${time(market.last_observed_at)}`}>
        <span className="heatmap-meta">{market.platform}<small>{t(market.status)}</small></span><strong className="heatmap-title">{market.title}</strong><div className="heatmap-values"><b>{cell.value == null ? '—' : change(cell.value)}</b><span>{probability(market.probability)}</span></div><small>{cell.state === 'ready' ? t('Bid / ask midpoint') : cell.state === 'stale' ? t('Stale observation') : t('No comparable window')}</small>
      </button>
    })}{query.data?.items.length === 0 && <p>{t('No markets in this selection.')}</p>}</div>
    <div className="analytics-footer"><span>{t('Showing')} {query.data?.items.length ? offset + 1 : 0}–{offset + (query.data?.items.length ?? 0)} / {query.data?.total ?? '—'}</span><div><button disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 60))}>{t('Previous')}</button><button disabled={!query.data || offset + 60 >= query.data.total} onClick={() => setOffset(offset + 60)}>{t('Next')}</button></div></div>
  </>
}
