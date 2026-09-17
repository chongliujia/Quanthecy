import { useState } from 'react'
import { DiscoveryBasis, OutcomeStance, SavedVersionChanges, type Discovery, type VersionChanges, type OutcomeReview } from './EvidenceAssessment'
import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import { t, useLanguage } from './i18n'
import { time } from './format'
import { withCutoff } from './navigation'
import { Empty, ErrorNotice, ResearchTime } from './ResearchUI'
import type { Evidence } from './researchTypes'
import type { ResearchReference } from './agentTypes'

export type ResearchEvent = { id: string; slug: string; version: number; title: string; title_zh: string; scope: string; scope_zh: string; starts_on: string; ends_on: string; calendar_url: string; observed_at: string; market_count: number }
type Review = OutcomeReview & { id: string; relation: string; rationale: string; paragraphs: number[]; reviewed_at: string }
type Passage = { paragraph: number; text: string; truncated: boolean }
type Candidate = { id: string; evidence: Evidence; status: string; review: Review | null; passages: Passage[]; history: Review[]; matched_at: string; discovery?: Discovery; changes?: VersionChanges }
export type EventDetail = { event: ResearchEvent; cutoff: string; official_direct_count?: number; markets: { id: string; platform: string; title: string; outcome: string; resolution_rules: string; closes_at: string | null; linked_at: string }[]; evidence: Candidate[]; counts: Record<string, number>; truncated: boolean; changes: { id: string; kind: string; title: string; observed_at: string; item_id: string | null; evidence_observed_at: string | null }[] }
const labels: Record<string, string> = { PENDING: 'Pending review', STALE: 'New version needs review', DIRECT: 'Directly relevant', BACKGROUND: 'Background only', UNRELATED: 'Unrelated', SCOPE: 'Event scope recorded', EVIDENCE: 'Evidence discovered', REVISION: 'Evidence version captured', REVIEW: 'Review recorded', MARKET: 'Contract linked' }
const statusLabel = (status: string) => t(labels[status] ?? status)
function paragraphLink(itemId: string, observedAt: string, paragraph?: number) { return `#${withCutoff(`/evidence/${itemId}`, observedAt)}${paragraph ? `&paragraph=${paragraph}` : ''}` }

export function MarketEventLinks({ userId, marketId, cutoff }: { userId: string; marketId: string; cutoff: string }) {
  const language = useLanguage()
  const query = useQuery({ queryKey: ['market-events', userId, marketId, cutoff], queryFn: () => api<ResearchEvent[]>(`/research/events?market_id=${marketId}${cutoff ? `&cutoff=${encodeURIComponent(cutoff)}` : ''}`) })
  if (!Array.isArray(query.data) || !query.data.length) return null
  return <div className="event-market-links"><span>{t('Event dossiers')}</span>{query.data.map(event => <a key={event.id} href={`#${withCutoff(`/events/${event.slug}`, cutoff)}`}>{language === 'zh' && event.title_zh ? event.title_zh : event.title} →</a>)}</div>
}

export default function EventPages({ userId, slug, cutoff }: { userId: string; slug?: string; cutoff: string }) {
  const language = useLanguage()
  const [filter, setFilter] = useState('ALL')
  const [section, setSection] = useState('evidence')
  const path = slug ? `/events/${slug}` : '/events'
  const query = useQuery({ queryKey: ['research-events', userId, slug, cutoff], queryFn: () => api<ResearchEvent[] | EventDetail>(withCutoff(`/research${path}`, cutoff)), refetchInterval: cutoff ? false : 60000 })
  const name = (event: ResearchEvent) => language === 'zh' && event.title_zh ? event.title_zh : event.title
  const scope = (event: ResearchEvent) => language === 'zh' && event.scope_zh ? event.scope_zh : event.scope
  const detail = query.data && !Array.isArray(query.data) ? query.data : null
  return <div className="event-research">
    <ResearchTime key={cutoff} cutoff={cutoff} path={path} />
    {query.isPending && <p role="status">{t('Loading event research…')}</p>}
    {query.error && <ErrorNotice error={query.error} retry={() => void query.refetch()} />}
    {Array.isArray(query.data) && (query.data.length ? <div className="event-list">{query.data.map(event => <a className="panel event-summary" key={event.id} href={`#${withCutoff(`/events/${event.slug}`, cutoff)}`}><span className="eyebrow">{t('EVENT RESEARCH')} · {event.starts_on} — {event.ends_on}</span><h2>{name(event)}</h2><p>{scope(event)}</p><strong>{t('{count} linked contracts', { count: event.market_count })} →</strong></a>)}</div> : <Empty title={t('No event dossier at this cutoff')}>{t('Event scope and evidence become available from their recorded observation time.')}</Empty>)}
    {detail && <>
      <a className="text-button" href={`#${withCutoff('/events', cutoff)}`}>← {t('Event dossiers')}</a>
      <section className="panel event-hero"><span className="eyebrow">{t('EVENT RESEARCH')} · v{detail.event.version}</span><h2>{name(detail.event)}</h2><p>{scope(detail.event)}</p><div className="event-schedule"><strong>{detail.event.starts_on} — {detail.event.ends_on}</strong><a href={detail.event.calendar_url} target="_blank" rel="noopener noreferrer">{t('Official calendar ↗')}</a><small>{t('Scope observed')} {time(detail.event.observed_at)}</small></div></section>
      <div className="event-stats">{[['Linked contracts', detail.markets.length], ['Directly relevant', detail.counts.DIRECT], ['Background only', detail.counts.BACKGROUND], ['Needs review', (detail.counts.PENDING ?? 0) + (detail.counts.STALE ?? 0)]].map(([label, value]) => <div key={label} className="panel"><span>{t(String(label))}</span><strong>{value}</strong></div>)}</div>
      <div className="event-section-switch" role="group" aria-label={t('Event dossier sections')}>{[['evidence', 'Evidence for this event'], ['contracts', 'Linked contracts'], ['changes', 'Evidence changes']].map(([id, label]) => <button key={id} aria-pressed={section === id} onClick={() => setSection(id)}>{t(label)}</button>)}</div>
      <section className="panel" hidden={section !== 'evidence'}><div className="section-heading"><div><span className="eyebrow">{t('EVIDENCE REVIEW')}</span><h3>{t('Evidence for this event')}</h3></div><label>{t('Relevance filter')}<select value={filter} onChange={e => setFilter(e.target.value)}><option value="ALL">{t('All evidence')}</option>{Object.keys(detail.counts).map(s => <option key={s} value={s}>{statusLabel(s)} · {detail.counts[s]}</option>)}</select></label></div>
        <p className="coverage-note">{t('Direct relevance is not support for YES or proof of causation. A new document or event scope requires a new review.')}</p>
        {!(detail.official_direct_count ?? detail.counts.DIRECT) && <p className="data-warning">{t('No directly relevant official body passages have been reviewed. Agent probability estimates remain unavailable; qualitative research can continue.')}</p>}
        <div className="event-evidence-list">{detail.evidence.filter(c => filter === 'ALL' || c.status === filter).map(candidate => <article className="event-evidence" key={candidate.id}><div className="evidence-meta"><span>{t(candidate.evidence.source_kind === 'MEDIA' ? 'Media' : candidate.evidence.source_kind === 'OFFICIAL' ? 'Official' : 'Unknown source type')} · {candidate.evidence.source_name} · v{candidate.evidence.version}</span><span className={`badge ${candidate.status === 'DIRECT' ? '' : 'badge-amber'}`}>{statusLabel(candidate.status)}</span></div><h4><a href={paragraphLink(candidate.evidence.id, candidate.evidence.observed_at)}>{candidate.evidence.title}</a></h4><small>{t('Published')} {time(candidate.evidence.published_at)} · {t('Observed')} {time(candidate.evidence.observed_at)}</small>
          <DiscoveryBasis discovery={candidate.discovery} evidence={candidate.evidence} /><SavedVersionChanges changes={candidate.changes} evidence={candidate.evidence} />
          {candidate.review ? <><p>{candidate.review.rationale}</p><OutcomeStance review={candidate.review} />{candidate.passages.map(p => <blockquote key={p.paragraph}><a href={paragraphLink(candidate.evidence.id, candidate.evidence.observed_at, p.paragraph)}>{t('Paragraph {number}', { number: p.paragraph })} ↗</a><p>{p.text}{p.truncated && '…'}</p></blockquote>)}<small>{t('Review recorded')} {time(candidate.review.reviewed_at)}</small></> : <p className="quiet">{t('Candidate relevance has not been approved by an operator.')}</p>}
          {candidate.history.length > 1 && <details><summary>{t('Review history')}</summary>{candidate.history.map(r => <div key={r.id}>{time(r.reviewed_at)} · {statusLabel(r.relation)} — {r.rationale}<OutcomeStance review={r} /></div>)}</details>}
        </article>)}</div>
        {!detail.evidence.some(c => filter === 'ALL' || c.status === filter) && <p>{t('No evidence in this category.')}</p>}
        {detail.truncated && <p className="data-warning">{t('Showing up to 100 candidates ordered by discovery priority. This view is not exhaustive.')}</p>}
      </section>
      <div className="event-bottom-grid" hidden={section === 'evidence'}><section className="panel" hidden={section !== 'contracts'}><h3>{t('Linked contracts')}</h3><p className="quiet">{t('Rules below were saved when the contract was linked. Open the market to check its latest rules; related contracts are not automatically equivalent.')}</p><div className="event-contract-list">{detail.markets.map(m => <details key={m.id}><summary><span>{m.platform} · {m.outcome}</span><strong>{m.title}</strong></summary><p>{m.resolution_rules}</p><a href={`#${withCutoff(`/markets/${m.id}`, cutoff)}`}>{t('Open market →')}</a></details>)}</div></section>
      <section className="panel" hidden={section !== 'changes'}><h3>{t('Evidence changes')}</h3><p className="quiet">{t('Latest 50 records, ordered by platform observation time. These updates do not imply a price impact.')}</p><ol className="event-changes">{detail.changes.map(change => <li key={change.id}><span>{statusLabel(change.kind)}</span><small>{time(change.observed_at)}</small>{change.item_id && change.evidence_observed_at ? <a href={paragraphLink(change.item_id, change.evidence_observed_at)}>{change.title}</a> : <p>{change.title}</p>}</li>)}</ol></section></div>
    </>}
  </div>
}

export function FrozenEvidence({ reference }: { reference: ResearchReference }) {
  if (reference.kind !== 'evidence' || !reference.value || typeof reference.value !== 'object') return null
  const value = reference.value as { evidence?: { id?: string; observed_at?: string }; document_selection?: { passages?: Passage[] }; version_changes?: VersionChanges; event_reviews?: { event_slug: string; review: Review }[] }
  const evidence = value.evidence
  if (!evidence?.id || !evidence.observed_at) return null
  return <div className="frozen-evidence-passages"><a href={paragraphLink(evidence.id, evidence.observed_at)}>{t('Open the cited evidence version →')}</a>{value.event_reviews?.map(v => <div key={v.review.id}><p>{statusLabel(v.review.relation)} · {v.review.rationale}</p><OutcomeStance review={v.review} /></div>)}<SavedVersionChanges changes={value.version_changes} evidence={{ id: evidence.id, observed_at: evidence.observed_at }} />{value.document_selection?.passages?.map(p => <blockquote key={p.paragraph}><a href={paragraphLink(evidence.id!, evidence.observed_at!, p.paragraph)}>{t('Paragraph {number}', { number: p.paragraph })} ↗</a><p>{p.text}{p.truncated && '…'}</p></blockquote>)}</div>
}
