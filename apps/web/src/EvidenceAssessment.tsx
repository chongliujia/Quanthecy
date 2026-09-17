import { t } from './i18n'
import { withCutoff } from './navigation'
import type { Evidence } from './researchTypes'

type Quote = { paragraph: number; text: string; truncated: boolean }
export type Discovery = { method?: string; priority?: number; reasons?: string[]; matches?: { field: string; paragraph: number | null; text: string; truncated: boolean }[] }
export type VersionChanges = { kind?: string; previous_observed_at?: string; changed_fields?: string[]; added?: Quote[]; removed?: Quote[]; truncated?: boolean; previous_excerpt?: string | null; previous_excerpt_truncated?: boolean }
export type OutcomeReview = { stance?: string; feed_quote?: string; target_market_id?: string | null; target_snapshot?: { market: { title: string }; outcome: { label: string } } | null; target?: { title: string; outcome: { label: string } }; stance_applicable?: boolean }
const reasons: Record<string, string> = { SELECTED_SOURCE: 'Source selected for this event', FED_POLICY_TERMS: 'Fed policy terms in saved text', US_MACRO_TERMS: 'US macroeconomic terms in saved text', EVENT_MONTH_MENTION: 'Event month and year mentioned', PUBLICATION_IN_WINDOW: 'Published within the discovery window', PUBLICATION_UNKNOWN: 'Publication time unknown' }
const fields: Record<string, string> = { title: 'Title', excerpt: 'Feed excerpt', url: 'Source link', published_at: 'Publication time', document: 'Captured body' }
const link = (id: string, at: string, paragraph?: number) => `#${withCutoff(`/evidence/${id}`, at)}${paragraph ? `&paragraph=${paragraph}` : ''}`

export function DiscoveryBasis({ discovery, evidence }: { discovery?: Discovery; evidence: Evidence }) {
  if (!discovery?.method) return <p className="quiet">{t('Matched by selected source; relevance remains unreviewed.')}</p>
  return <details className="evidence-assessment"><summary>{t('Why this is a candidate')}</summary>
    <p className="quiet">{t('Matching rules prioritize review; they do not measure probability or market impact.')}</p>
    <ul>{discovery.reasons?.map(code => <li key={code}>{t(reasons[code] ?? code)}</li>)}</ul>
    {discovery.matches?.map((match, i) => <blockquote key={i}><small>{match.paragraph ? <a href={link(evidence.id, evidence.observed_at, match.paragraph)}>{t('Paragraph {number}', { number: match.paragraph })} ↗</a> : t(fields[match.field] ?? match.field)}</small><p>{match.text}{match.truncated && '…'}</p></blockquote>)}
  </details>
}

export function OutcomeStance({ review }: { review: OutcomeReview }) {
  const target = review.target ?? (review.target_snapshot ? { title: review.target_snapshot.market.title, outcome: review.target_snapshot.outcome } : null)
  const label = review.stance === 'SUPPORTS' ? 'Supports the selected outcome' : review.stance === 'OPPOSES' ? 'Opposes the selected outcome' : 'Outcome stance undetermined'
  return <div className="evidence-assessment"><strong>{t(label)}</strong>{target && <p>{target.title} · {target.outcome.label}</p>}
    {target && <small>{t('Applies to the saved contract scope, not every market in this event.')}</small>}
    {review.stance_applicable === false && review.stance !== 'UNKNOWN' && <p className="data-warning">{t('This saved stance does not apply to the current contract and rules.')}</p>}
    {review.feed_quote && <blockquote><small>{t('Exact feed quote')}</small><p>{review.feed_quote}</p></blockquote>}
  </div>
}

export function SavedVersionChanges({ changes, evidence }: { changes?: VersionChanges; evidence: { id: string; observed_at: string } }) {
  if (!changes?.kind) return null
  if (changes.kind === 'FIRST_OBSERVED') return <p className="quiet">{t('First saved version; earlier publisher history is unknown.')}</p>
  return <details className="evidence-assessment"><summary>{t('What changed in this saved version')}</summary>
    <p>{changes.changed_fields?.map(field => t(fields[field] ?? field)).join(' · ')}</p>
    <p className="quiet">{t('Compared with the previous saved version, not your previous report. First body capture need not mean a new publisher statement.')}</p>
    {changes.previous_observed_at && <a href={link(evidence.id, changes.previous_observed_at)}>{t('Open previous saved version →')}</a>}
    {changes.previous_excerpt && <blockquote><small>{t('Previous feed excerpt')}</small><p>{changes.previous_excerpt}{changes.previous_excerpt_truncated && '…'}</p></blockquote>}
    {changes.added?.map(p => <blockquote key={`added-${p.paragraph}`}><a href={link(evidence.id, evidence.observed_at, p.paragraph)}>{t('Added in this capture')} · {t('Paragraph {number}', { number: p.paragraph })} ↗</a><p>{p.text}{p.truncated && '…'}</p></blockquote>)}
    {changes.removed?.map(p => <blockquote key={`removed-${p.paragraph}`}><small>{t('Removed from the current capture')}</small>{changes.previous_observed_at && <a href={link(evidence.id, changes.previous_observed_at, p.paragraph)}> {t('Previous version')} ↗</a>}<p>{p.text}{p.truncated && '…'}</p></blockquote>)}
    {changes.truncated && <p className="quiet">{t('Changes are excerpted; open both versions for the complete context.')}</p>}
  </details>
}
