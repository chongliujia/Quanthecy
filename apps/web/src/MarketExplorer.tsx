import { t, locale, useLanguage } from './i18n'
import { lazy, Suspense, useState, type FormEvent } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useCollectionStatus } from './collectionHealth'
import { api, type Organization } from './api'
import type { Market } from './marketTypes'
const MarketWorkbench = lazy(() => import('./MarketWorkbench'))

type TopicCoverage = {
  slug: string; name: string; name_zh: string; description: string; description_zh: string
  configured: number; observed: number; fresh: number; price_usable: number; volume_usable: number; missing: number; needs_attention: number
}

function probability(value: number | null | undefined) { return value == null ? t("Unavailable") : `${(value * 100).toFixed(2)}%` }
function change(value: number | null | undefined) { return value == null ? '—' : `${value > 0 ? '+' : ''}${(value * 100).toFixed(2)} pp` }
function localTime(value: string) { return new Date(value).toLocaleString(locale()) }
function ErrorNotice({ error, retry }: { error: Error; retry: () => void }) {
  return <div role="alert" className="error">{t(error.message)} <button onClick={retry}>{t("Retry")}</button></div>
}

export default function MarketExplorer({ userId, selectedId, onSelect, organization, cutoff = '' }: { userId: string; organization?: Organization; cutoff?: string; selectedId?: string | null; onSelect?: (id: string | null) => void }) {
  const language = useLanguage()
  const [topic, setTopic] = useState('')
  const topics = useQuery({ queryKey: ['research-topics', userId], queryFn: () => api<TopicCoverage[]>('/research/topics'), refetchInterval: 30000 })
  const topicCoverage = topics.data?.find((item) => item.slug === topic)
  const collection = useCollectionStatus(userId)
  const [platform, setPlatform] = useState('')
  const [sort, setSort] = useState('recent')
  const [search, setSearch] = useState('')
  const [draft, setDraft] = useState('')
  const [offset, setOffset] = useState(0)
  const [localSelected, setLocalSelected] = useState<string | null>(null)
  const selected = selectedId === undefined ? localSelected : selectedId
  const setSelected = onSelect ?? setLocalSelected
  const markets = useQuery({ queryKey: ['markets', userId, platform, sort, search, offset, topic],
    queryFn: () => api<{ items: Market[]; total: number }>(`/markets?limit=20&offset=${offset}&sort=${sort}&search=${encodeURIComponent(search)}${platform ? `&platform=${platform}` : ''}${topic ? `&topic=${encodeURIComponent(topic)}` : ''}`), refetchInterval: 30000 })
  function submit(event: FormEvent) { event.preventDefault(); setOffset(0); setSearch(draft) }
  if (selected) return <Suspense fallback={<p role="status">{t("Loading research terminal…")}</p>}><MarketWorkbench key={`${selected}-${cutoff}`} id={selected} userId={userId} organization={organization} cutoff={cutoff} close={() => setSelected(null)} /></Suspense>
  return <section>
    <h2>{t("Market explorer")}</h2><p>{t("Inspect collected markets, probability changes, and their evidence.")}</p>
    <p className="coverage-note">{t("Coverage: selected binary markets on Polymarket and Kalshi, YES outcome only. REST snapshots start when collection begins. Rankings cover this sample.")}</p>
    <div className="market-controls"><form onSubmit={submit}><label className="sr-only" htmlFor="market-search">{t("Search markets")}</label><input id="market-search" placeholder={t("Search collected markets")} value={draft} onChange={(e) => setDraft(e.target.value)} maxLength={200} /><button>{t("Search")}</button></form>
      <label>{t("Research topic")}<select value={topic} onChange={(e) => { setTopic(e.target.value); setOffset(0) }}><option value="">{t("All collected markets")}</option>{topics.data?.map((item) => <option key={item.slug} value={item.slug}>{language === 'zh' && item.name_zh ? item.name_zh : item.name}</option>)}</select></label>
      <label>{t("Platform")}<select value={platform} onChange={(e) => { setPlatform(e.target.value); setOffset(0) }}><option value="">{t("All platforms")}</option><option value="polymarket">{t("Polymarket")}</option><option value="kalshi">{t("Kalshi")}</option></select></label>
      <label>{t("Sort by")}<select value={sort} onChange={(e) => { setSort(e.target.value); setOffset(0) }}><option value="recent">{t("Recently observed")}</option><option value="movement">{t("Largest 15m movement")}</option><option value="volume_anomaly">{t("Volume anomaly")}</option></select></label>
    </div>
    {topics.error && !markets.error && <ErrorNotice error={topics.error} retry={() => void topics.refetch()} />}
    {topicCoverage && <section className="panel topic-coverage" aria-label={t("Topic coverage")}>
      <h3>{language === 'zh' && topicCoverage.name_zh ? topicCoverage.name_zh : topicCoverage.name}</h3>
      <p>{language === 'zh' && topicCoverage.description_zh ? topicCoverage.description_zh : topicCoverage.description}</p>
      <div className="topic-stats">
        <div><strong>{topicCoverage.configured}</strong><span>{t("Enabled collection targets")}</span></div>
        <div><strong>{topicCoverage.fresh}</strong><span>{t("Fresh observations")}</span></div>
        <div><strong>{topicCoverage.price_usable}</strong><span>{t("Price change available")}</span></div>
        <div><strong>{topicCoverage.volume_usable}</strong><span>{t("Volume anomaly available")}</span></div>
      </div>
      <p className="quiet">{t("Awaiting first observation: {missing}. Targets needing attention: {attention}.", { missing: topicCoverage.missing, attention: topicCoverage.needs_attention })} {t("Coverage counts describe the whole topic across both exchanges. New targets need continuous history before research metrics become available.")}</p>
      <p className="quiet">{t("A shared topic does not establish equivalent settlement rules or an arbitrage opportunity.")}</p>
    </section>}
    {markets.isPending && <p role="status">{t("Loading markets…")}</p>}
    {markets.error && <ErrorNotice error={markets.error} retry={() => void markets.refetch()} />}
    {markets.data && <>
      <p className="quiet">{markets.data.total} {t("markets")}{sort !== 'recent' && t(" with fresh, comparable metrics")}</p>
      {markets.data.items.length === 0 ? <section className="panel"><h3>{t("No markets to show yet")}</h3><p>{collection.data?.sources?.some((source) => (!platform || source.platform === platform) && (source.state === 'delayed' || source.error_code)) ? t("Collection is interrupted or delayed. Rankings exclude stale observations. Check the source status above or switch to Recently observed to inspect saved history.") : t("No collected markets match these filters with enough recent history. Try another filter or inspect Recently observed markets.")}</p></section>
        : <div className="panel table-scroll"><table className="market-table"><thead><tr><th>{t("Market · YES")}</th><th>{t("Midpoint")}</th><th>{t("15m change")}</th><th>{t("Last observed")}</th></tr></thead><tbody>{markets.data.items.map((m) => <tr key={m.id}><td><button className="market-link" onClick={() => setSelected(m.id)}>{m.title}</button><small>{m.platform} · {t(m.status)}{m.stale ? t(" · STALE") : ''}</small></td><td>{probability(m.probability)}</td><td>{change(m.metrics.probability_change_15m)}</td><td>{localTime(m.last_observed_at)}</td></tr>)}</tbody></table></div>}
      <div className="pagination"><button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 20))}>{t("Previous")}</button><span>{markets.data.total ? offset + 1 : 0}–{Math.min(offset + 20, markets.data.total)} {t("of")} {markets.data.total}</span><button disabled={offset + 20 >= markets.data.total} onClick={() => setOffset(offset + 20)}>{t("Next")}</button></div>
    </>}
  </section>
}
