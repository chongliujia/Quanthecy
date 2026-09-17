import { t } from './i18n'
import { lazy, Suspense, useState, type FormEvent } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import { withCutoff } from './navigation'
import { Empty, ErrorNotice, EvidenceCard, ResearchTime } from './ResearchUI'
import { change, probability, readable, time } from './format'
import type { Comparison, Evidence, EvidenceDetail, FeedSignal, Overview, Quote, Review, Timeline, SourcePage } from './researchTypes'

import OfficialDocumentPanel from './OfficialDocumentPanel'
import NewsSources, { SourceStatus } from './NewsSources'

const ComparisonChart = lazy(() => import('./ComparisonChart'))

function PairCard({ review, cutoff = '' }: { review: Review; cutoff?: string }) {
  return <a className="panel pair-card" href={`#${withCutoff(`/comparisons/${review.comparison_id}`, cutoff)}`}>
    <div className="section-heading"><span className="eyebrow">{review.topic}</span><span className={`badge ${review.relation !== 'EQUIVALENT' ? 'badge-amber' : ''}`}>{readable(review.relation)}</span></div>
    <h3>{review.title}</h3><p>{review.rationale}</p><div className="pair-platforms"><span>{review.left_snapshot.platform}</span><span>↔</span><span>{review.right_snapshot.platform}</span></div>
    <div className="card-bottom"><small>{t("Review v")}{review.version} · {time(review.reviewed_at)}</small><span aria-hidden="true">↗</span></div>
  </a>
}

export function ResearchOverview({ userId }: { userId: string }) {
  const overview = useQuery({ queryKey: ['research-overview', userId], queryFn: () => api<Overview>('/research/overview'), refetchInterval: 30000 })
  const pairs = useQuery({ queryKey: ['comparisons', userId, ''], queryFn: () => api<Review[]>('/comparisons'), refetchInterval: 60000 })
  const news = useQuery({ queryKey: ['evidence-preview', userId], queryFn: () => api<{ items: Evidence[]; total: number }>('/evidence?limit=3'), refetchInterval: 60000 })
  return <>
    <section className="research-hero"><div><span className="eyebrow">{t("FOCUS / 01")}</span><h2>{t("Macro & interest rates")}</h2><p>{t("Follow the Fed, compare what contracts actually settle on, and inspect the evidence behind market activity.")}</p><div className="hero-links"><a className="primary button-link" href="#/comparisons">{t("Compare markets ↗")}</a><a href="#/markets">{t("Explore all markets →")}</a></div></div><div className="hero-aside"><span className="eyebrow">{t("RESEARCH WORKFLOW")}</span><ol><li>{t("Observe the market")}</li><li>{t("Read the contract")}</li><li>{t("Check the evidence")}</li></ol><small>{t("Polymarket + Kalshi · Selected coverage")}</small></div></section>
    {overview.isPending && <p role="status">{t("Loading research coverage…")}</p>}
    {overview.error && <ErrorNotice error={overview.error} retry={() => void overview.refetch()} />}
    {overview.data && <><div className="metric-grid overview-metrics">{[[overview.data.markets, t("Collected markets"), t('{count} open with recent observations', { count: overview.data.fresh_markets })], [overview.data.reviewed_pairs, t("Reviewed comparisons"), t("Explicit outcome and rule alignment")], [overview.data.evidence_items, t("News & evidence entries"), t("Versioned from first collection")]].map(([value, label, note]) => <section className="panel" key={label}><span>{label}</span><strong>{value}</strong><small>{note}</small></section>)}</div><p className="quiet">{t("Latest market observation:")} {time(overview.data.latest_observation)}{t(". All times use your local timezone.")}</p></>}
    <div className="section-heading"><h2>{t("Reviewed comparisons")}</h2><a className="text-button" href="#/comparisons">{t("View all →")}</a></div>
    {pairs.isPending && <p role="status">{t("Loading comparisons…")}</p>}
    {pairs.error && <ErrorNotice error={pairs.error} retry={() => void pairs.refetch()} />}
    {pairs.data && (pairs.data.length ? <div className="pair-grid">{pairs.data.slice(0, 2).map((r) => <PairCard key={r.id} review={r} />)}</div> : <Empty title={t("No reviewed pairs yet")}>{t("Comparisons appear after both markets have been collected and their settlement rules reviewed.")}</Empty>)}
    <div className="research-columns"><section className="panel"><div className="section-heading"><h2>{t("Latest news & evidence")}</h2><a className="text-button" href="#/evidence">{t("All evidence →")}</a></div>
      {news.isPending && <p role="status">{t("Loading announcements…")}</p>}{news.error && <ErrorNotice error={news.error} retry={() => void news.refetch()} />}
      {news.data?.items.map((item) => <EvidenceCard key={item.id} item={item} compact />)}{news.data?.items.length === 0 && <p>{t("No announcements collected yet.")}</p>}
    </section><section className="panel source-panel"><span className="eyebrow">{t("COLLECTION STATUS")}</span><h2>{t("Know your coverage")}</h2><p>{t("Official releases and selected media feeds. Publication dates can precede collection.")}</p>
      {overview.data?.news_polling_enabled === false && <p className="data-warning">{t("News polling is paused.")}</p>}
      {overview.data?.sources.map((source) => <article key={source.slug}><a href={source.url} target="_blank" rel="noopener noreferrer">{t(source.name)} ↗</a><SourceStatus source={source} /><small>{t("Last success:")} {time(source.last_success_at)}</small><small>{t("Last check:")} {time(source.last_checked_at)}</small>{source.error && <p className="error">{source.error}</p>}</article>)}
      <p className="quiet">{t("REST market snapshots · History from collection · Versioned evidence")}</p>
    </section></div>
  </>
}

export function ComparisonList({ userId, cutoff }: { userId: string; cutoff: string }) {
  const query = useQuery({ queryKey: ['comparisons', userId, cutoff], queryFn: () => api<Review[]>(withCutoff('/comparisons', cutoff)), refetchInterval: cutoff ? false : 60000 })
  return <><p className="page-description">{t("Compare selected contracts after checking wording, outcomes, expiry and settlement rules.")}</p><ResearchTime key={cutoff} cutoff={cutoff} path="/comparisons" />
    <p className="coverage-note">{t("First topic: macroeconomics & interest rates. Related contracts may settle differently; price differences are research observations.")}</p>
    {query.isPending && <p role="status">{t("Loading reviewed comparisons…")}</p>}{query.error && <ErrorNotice error={query.error} retry={() => void query.refetch()} />}
    {query.data && (query.data.length ? <div className="pair-grid">{query.data.map((r) => <PairCard key={r.id} review={r} cutoff={cutoff} />)}</div> : <Empty title={t("No reviews available at this time")}>{t("A comparison needs collected markets and an explicit rule review. Later reviews do not appear at an earlier cutoff.")}</Empty>)}
  </>
}

function QuoteCard({ name, quote, label }: { name: string; quote: Quote | null; label: string }) {
  return <section className="panel quote-card"><span className="eyebrow">{name} · {label}</span><strong>{probability(quote?.probability)}</strong><p>{t("Bid")} {probability(quote?.bid)} {t("· Ask")} {probability(quote?.ask)}</p><small>{t("Observed")} {time(quote?.received_at)}</small><small>{quote?.basis ?? t("Basis unavailable")} · {quote?.source ?? t("Source unavailable")}</small></section>
}

export function ComparisonView({ userId, id, cutoff }: { userId: string; id: string; cutoff: string }) {
  const [hours, setHours] = useState('24')
  const query = useQuery({ queryKey: ['comparison', userId, id, cutoff, hours], queryFn: () => api<Comparison>(`/comparisons/${encodeURIComponent(id)}?hours=${hours}${cutoff ? `&cutoff=${encodeURIComponent(cutoff)}` : ''}`), refetchInterval: cutoff ? false : 60000 })
  const data = query.data
  return <><a className="text-button" href={`#${withCutoff('/comparisons', cutoff)}`}>{t("← All comparisons")}</a><ResearchTime key={cutoff} cutoff={cutoff} path={`/comparisons/${id}`} />
    {query.isPending && <p role="status">{t("Aligning collected observations…")}</p>}{query.error && <ErrorNotice error={query.error} retry={() => void query.refetch()} />}
    {data && <><div className="market-title"><span className="eyebrow">{data.review.topic} {t("/ REVIEW v")}{data.review.version}</span><h2>{data.review.title}</h2><span className="badge badge-amber">{readable(data.review.relation)}</span></div>
      <p className="coverage-note">{data.review.rationale} {data.review.relation !== 'EQUIVALENT' && t("These contracts are not interchangeable.")}</p>
      <div className="comparison-quotes"><QuoteCard name={data.review.left_snapshot.platform} quote={data.current.left} label={data.review.left_snapshot.outcome.label} /><section className="panel difference-card"><span>{t("Left − aligned right")}</span><strong>{change(data.current.difference)}</strong><small>{t("Contextual probability difference")}</small><small>{t("As of")} {time(data.cutoff)}</small></section><QuoteCard name={data.review.right_snapshot.platform} quote={data.current.right} label={data.review.alignment === 'COMPLEMENT' ? `1 − ${data.review.right_snapshot.outcome.label}` : data.review.right_snapshot.outcome.label} /></div>
      {data.current.issues.length > 0 && <div className="data-warning" role="status"><strong>{t("Difference unavailable")}</strong><ul>{data.current.issues.map((issue) => <li key={issue}>{readable(issue)}</li>)}</ul></div>}
      <p className="quiet">{t("Observation skew:")} {data.current.skew_seconds == null ? 'unknown' : `${data.current.skew_seconds.toFixed(1)} seconds`}{t(". Maximum")} {data.max_skew_seconds}{t("s; maximum sample age")} {data.max_age_seconds}{t("s. Exchange quote times are unavailable.")}</p>
      <section className="panel history-panel"><div className="section-heading"><h3>{t("Aligned probability history")}</h3><label>{t("Window")}<select aria-label={t("Comparison history window")} value={hours} onChange={(event) => setHours(event.target.value)}><option value="1">{t("1 hour")}</option><option value="6">{t("6 hours")}</option><option value="24">{t("24 hours")}</option></select></label></div>
        {data.history.some((point) => point.difference !== null) ? <Suspense fallback={<p>{t("Loading chart…")}</p>}><ComparisonChart points={data.history} left={data.review.left_snapshot.platform} right={`${data.review.right_snapshot.platform}${data.review.alignment === 'COMPLEMENT' ? t(" (complement)") : ''}`} /></Suspense> : <p>{t("No qualified pairs of observations in this window. Collection and review availability both limit the chart.")}</p>}
        {data.history.filter((point) => point.difference !== null).length === 1 && <p className="data-warning">{t("Only one qualified point is available so far. History begins once both observations and a review are available.")}</p>}
        <p className="quiet">{t("Five-minute sampling; only observations and reviews known at each point are used. Missing or excluded data remain blank.")}</p>
        <details><summary>{t("Recent alignment audit")}</summary><div className="table-scroll"><table><thead><tr><th>{t("At")}</th><th>{t("Left")}</th><th>{t("Aligned right")}</th><th>{t("Difference")}</th><th>{t("Qualification")}</th></tr></thead><tbody>{data.history.slice(-12).map((p) => <tr key={p.at}><td>{time(p.at)}</td><td>{probability(p.left?.probability)}</td><td>{probability(p.right?.probability)}</td><td>{change(p.difference)}</td><td>{p.issues.map(readable).join(', ') || `Review v${p.review_version}`}</td></tr>)}</tbody></table></div><p className="quiet audit-ids">{t("Current input IDs:")} {data.current.left?.observation_id ?? 'unavailable'} / {data.current.right?.observation_id ?? 'unavailable'}</p></details>
      </section>
      <section className="panel rules"><h3>{t("What the review found")}</h3><p className="rules-text">{data.review.differences}</p><p className="quiet">{data.review.reviewer_label} · {time(data.review.reviewed_at)} {t("· Match confidence")} {(data.review.confidence * 100).toFixed(0)}{t("% (review judgment, not calibrated)")}</p><div className="rule-columns">{[data.review.left_snapshot, data.review.right_snapshot].map((m) => <details key={m.market.id}><summary>{m.platform} {t("· frozen rules")}</summary><p><a className="text-button" href={`#/markets/${m.market.id}`}>{m.market.title} {t("→ latest market view")}</a></p><p className="rules-text">{m.market.resolution_rules}</p><p className="quiet">{t("Closes:")} {time(m.market.closes_at)}<br />{t("Outcome:")} {m.outcome.label}</p><small className="audit-ids">{t("Rule version:")} {m.market.rules_version}<br />{t("Resolution source:")} {m.market.resolution_source || t("See contract rules")}</small></details>)}</div>
        <details className="review-history"><summary>{t("Review history (")}{data.revisions.length})</summary>{[...data.revisions].reverse().map((r) => <article key={r.id}><strong>{t("v")}{r.version} · {readable(r.relation)}</strong><p>{time(r.reviewed_at)} · {r.reviewer_label}</p><p>{r.rationale}</p><p className="rules-text">{r.differences}</p></article>)}</details>
      </section>
      <MarketTimeline userId={userId} id={data.review.left_snapshot.market.id} cutoff={cutoff} />
    </>}
  </>
}

export function EvidenceList({ userId, cutoff }: { userId: string; cutoff: string }) {
  const [source, setSource] = useState('')
  const [kind, setKind] = useState('')
  const sources = useQuery({ queryKey: ['news-sources', userId], queryFn: () => api<SourcePage>('/research/sources'), refetchInterval: 60000 })
  const [draft, setDraft] = useState('')
  const [search, setSearch] = useState('')
  const [offset, setOffset] = useState(0)
  const query = useQuery({ queryKey: ['evidence', userId, cutoff, source, kind, search, offset], queryFn: () => api<{ items: Evidence[]; total: number }>(`/evidence?limit=20&offset=${offset}&source=${source}&kind=${kind}&search=${encodeURIComponent(search)}${cutoff ? `&cutoff=${encodeURIComponent(cutoff)}` : ''}`), refetchInterval: cutoff ? false : 60000 })
  function submit(event: FormEvent) { event.preventDefault(); setSearch(draft); setOffset(0) }
  return <><p className="page-description">{t("Official economic releases and selected business news, with source labels, publication dates and saved versions.")}</p><ResearchTime key={cutoff} cutoff={cutoff} path="/evidence" />
    <div className="market-controls"><form onSubmit={submit}><label className="sr-only" htmlFor="news-search">{t("Search news and evidence")}</label><input id="news-search" placeholder={t("Search news and evidence")} value={draft} maxLength={200} onChange={(e) => setDraft(e.target.value)} /><button>{t("Search")}</button></form><label>{t("Source")}<select value={source} onChange={(e) => { setSource(e.target.value); setOffset(0) }}><option value="">{t("All sources")}</option>{sources.data?.sources?.filter(s => !kind || s.kind === kind).map(s => <option key={s.slug} value={s.slug}>{t(s.name)}</option>)}</select></label><label>{t("Source type")}<select value={kind} onChange={e => { setKind(e.target.value); setSource(''); setOffset(0) }}><option value="">{t("All source types")}</option><option value="OFFICIAL">{t("Official")}</option><option value="MEDIA">{t("Media")}</option></select></label></div>
    <p className="coverage-note">{t("Official and media sources are labeled separately. Feed excerpts are not full articles. Topic matches do not establish causation.")}</p>
    {sources.error && <ErrorNotice error={sources.error} retry={() => void sources.refetch()} />}
    {sources.data?.sources && <NewsSources sources={sources.data.sources} pollingEnabled={sources.data.polling_enabled} />}
    {query.isPending && <p role="status">{t("Loading evidence…")}</p>}{query.error && <ErrorNotice error={query.error} retry={() => void query.refetch()} />}
    {query.data && (query.data.items.length ? <><section className="panel evidence-list">{query.data.items.map((item) => <EvidenceCard key={item.id} item={item} cutoff={cutoff} />)}</section><div className="pagination"><button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 20))}>{t("Previous")}</button><span>{offset + 1}–{Math.min(offset + 20, query.data.total)} {t("of")} {query.data.total}</span><button disabled={offset + 20 >= query.data.total} onClick={() => setOffset(offset + 20)}>{t("Next")}</button></div></> : <Empty title={t("No evidence available for this view")}>{t("Try another filter or a later cutoff. Older publication dates do not imply that Quanthecy had collected those entries at the time.")}</Empty>)}
  </>
}

export function EvidenceView({ userId, id, cutoff }: { userId: string; id: string; cutoff: string }) {
  const query = useQuery({ queryKey: ['evidence-item', userId, id, cutoff], queryFn: () => api<EvidenceDetail>(withCutoff(`/evidence/${encodeURIComponent(id)}`, cutoff)), refetchInterval: cutoff ? false : 60000 })
  return <><a className="text-button" href={`#${withCutoff('/evidence', cutoff)}`}>{t("← All evidence")}</a><ResearchTime key={cutoff} cutoff={cutoff} path={`/evidence/${id}`} />
    {query.isPending && <p role="status">{t("Loading evidence record…")}</p>}{query.error && <ErrorNotice error={query.error} retry={() => void query.refetch()} />}
    {query.data && <><section className="panel evidence-detail"><EvidenceCard item={query.data.item} cutoff={cutoff} /><p className="quiet">{t("This version was observed")} {time(query.data.item.observed_at)}{t(". The publisher's publication date is stored separately.")}</p><details><summary>{t("Stored versions (")}{query.data.revisions.length})</summary>{query.data.revisions.map((r) => <article className="revision" key={r.revision_id}><strong>{t("v")}{r.version} · {r.title}</strong><p>{t("Published")} {time(r.published_at)} {t("· Observed")} {time(r.observed_at)}</p><p>{r.excerpt}</p><small className="audit-ids">{t("Content SHA-256:")} {r.content_hash}</small><p><a href={`#${withCutoff(`/evidence/${id}`, r.observed_at)}`}>{t("View this saved version →")}</a> · {r.document ? t("Text captured") : t("Feed excerpt only")}</p></article>)}</details></section>
      <OfficialDocumentPanel key={`${id}:${query.data.item.revision_id}`} document={query.data.document} collection={query.data.document_collection} supported={query.data.item.document_supported} historical={Boolean(cutoff)} />
      <section className="panel rules"><h3>{t("Market associations")}</h3><p>{t("Relevance is separate from causation. Automatic matches need further research.")}</p>{query.data.links.length === 0 && <p>{t("No market associations known at this cutoff.")}</p>}{query.data.links.map((link) => <article className="signal-row" key={link.id}><div><span className={`badge ${link.status === 'TOPIC_ONLY' ? 'badge-amber' : ''}`}>{readable(link.status)}</span><p>{link.rationale}</p><small>{time(link.created_at)} · {link.method}</small></div><a href={`#/markets/${link.market_id}`}>{t("Latest market view →")}</a></article>)}</section>
    </>}
  </>
}

export function MarketTimeline({ userId, id, cutoff = '' }: { userId: string; id: string; cutoff?: string }) {
  const [visible, setVisible] = useState(10)
  const query = useQuery({ queryKey: ['timeline', userId, id, cutoff], queryFn: () => api<Timeline>(withCutoff(`/markets/${encodeURIComponent(id)}/timeline`, cutoff)), refetchInterval: cutoff ? false : 60000 })
  return <section className="panel timeline-panel"><h3>{t("News & evidence timeline")}</h3><p>{t("News & evidence entries associated with this market's topic. Timing and topic alone do not establish a cause for price movements.")}</p>
    {query.isPending && <p role="status">{t("Loading timeline…")}</p>}{query.error && <ErrorNotice error={query.error} retry={() => void query.refetch()} />}
    {query.data?.items.length === 0 && <p>{t("No associated evidence has been collected for this market at this time.")}</p>}
    {query.data?.truncated && <p className="data-warning">{t("Showing 100 associations. Explore the evidence feed for wider coverage.")}</p>}
    {query.data?.items.slice(0, visible).map(({ evidence, association }) => <div className="timeline-entry" key={association.id}><span className="badge badge-amber">{readable(association.status)}</span><EvidenceCard item={evidence} cutoff={cutoff} compact /><details><summary>{t("Why this is associated")}</summary><p>{association.rationale}</p><small>{t("Association created")} {time(association.created_at)} · {association.method}</small></details></div>)}
    {query.data && visible < query.data.items.length && <button onClick={() => setVisible(visible + 10)}>{t("Show more evidence (")}{query.data.items.length - visible} {t("remaining)")}</button>}
  </section>
}

export function SignalFeed({ userId }: { userId: string }) {
  const [platform, setPlatform] = useState('')
  const [kind, setKind] = useState('')
  const query = useQuery({ queryKey: ['signal-feed', userId, platform, kind], queryFn: () => api<FeedSignal[]>(`/signals?limit=100${platform ? `&platform=${platform}` : ''}${kind ? `&signal_type=${kind}` : ''}`), refetchInterval: 60000 })
  return <><p className="page-description">{t("Deterministic market observations with saved inputs and versioned thresholds. Latest 100 signals from the past seven days.")}</p><div className="market-controls"><label>{t("Platform")}<select value={platform} onChange={(e) => setPlatform(e.target.value)}><option value="">{t("All platforms")}</option><option value="polymarket">{t("Polymarket")}</option><option value="kalshi">{t("Kalshi")}</option></select></label><label>{t("Signal type")}<select value={kind} onChange={(e) => setKind(e.target.value)}><option value="">{t("All signals")}</option>{['PROBABILITY_SPIKE', 'PROBABILITY_DROP', 'SPREAD_WIDENING', 'VOLUME_SPIKE'].map((k) => <option value={k} key={k}>{readable(k)}</option>)}</select></label></div>
    {query.isPending && <p role="status">{t("Loading signals…")}</p>}{query.error && <ErrorNotice error={query.error} retry={() => void query.refetch()} />}
    {query.data && (query.data.length ? <section className="panel">{query.data.map((signal) => <article className="signal-row feed-row" key={signal.id}><div><span className="badge">{readable(signal.signal_type)}</span><h3><a href={`#/markets/${signal.market_id}`}>{signal.market_title} →</a></h3><p>{signal.platform} · {time(signal.received_at)} · {signal.version}</p><small>{t("15m probability")} {change(signal.metrics.probability_change_15m)} {t("· Volume z")} {signal.metrics.volume_zscore?.toFixed(2) ?? 'unavailable'} · {signal.observation_ids.length} {t("saved inputs")}</small><details><summary>{t("Calculation thresholds")}</summary><dl>{Object.entries(signal.parameters).map(([name, value]) => <div key={name}><dt>{readable(name)}</dt><dd>{value}</dd></div>)}</dl></details></div><a href={`/api/v1/signals/${signal.id}/inputs?format=csv`}>{t("Export inputs ↓")}</a></article>)}</section> : <Empty title={t("No qualifying signals in this window")}>{t("Signals require sufficient continuous history and a threshold crossing. Quiet markets and missing data do not produce artificial signals.")}</Empty>)}
  </>
}
