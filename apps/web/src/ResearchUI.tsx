import { t } from './i18n'
import { useState, type FormEvent } from 'react'
import { navigate, withCutoff } from './navigation'
import type { Evidence } from './researchTypes'
import { time } from './format'

export function ErrorNotice({ error, retry }: { error: Error; retry: () => void }) {
  return <div role="alert" className="error notice">{t(error.message)} <button onClick={retry}>{t("Retry")}</button></div>
}
export function Empty({ title, children }: { title: string; children: React.ReactNode }) {
  return <section className="panel empty-state"><span className="eyebrow">{t("RESEARCH COVERAGE")}</span><h3>{title}</h3><p>{children}</p></section>
}

function localInput(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.valueOf()) ? '' : new Date(date.valueOf() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
}
export function ResearchTime({ cutoff, path }: { cutoff: string; path: string }) {
  const [draft, setDraft] = useState(cutoff ? localInput(cutoff) : '')
  function submit(event: FormEvent) { event.preventDefault(); if (draft) navigate(withCutoff(path, new Date(draft).toISOString())) }
  return <section className="research-time">
    <div><span className={`badge ${cutoff ? 'badge-amber' : ''}`}>{cutoff ? t("Historical view") : t("Latest available")}</span><p>{cutoff ? t('Known by {time}', { time: time(cutoff) }) : t("Refreshes every minute")}</p></div>
    <form onSubmit={submit}><label htmlFor="research-cutoff">{t("Research cutoff · local time")}<input id="research-cutoff" type="datetime-local" value={draft} max={localInput(new Date().toISOString())} required onChange={(event) => setDraft(event.target.value)} /></label><button disabled={!draft}>{t("Apply cutoff")}</button>{cutoff && <a className="text-button" href={`#${path}`}>{t("Return to latest")}</a>}</form>
  </section>
}

export function EvidenceCard({ item, cutoff = '', compact = false }: { item: Evidence; cutoff?: string; compact?: boolean }) {
  return <article className="evidence-card"><div className="evidence-meta"><span>{item.source_name}</span><span>{t("Published")} {time(item.published_at)}</span></div>
    <h3><a href={`#${withCutoff(`/evidence/${item.id}`, cutoff)}`}>{item.title}</a></h3>
    {!compact && item.excerpt !== item.title && <p>{item.excerpt}</p>}
    <div className="evidence-footer"><span>{t("First observed")} {time(item.first_observed_at)} {t("· v")}{item.version}</span><a href={item.url} target="_blank" rel="noopener noreferrer">{t("Official source ↗")}</a></div>
  </article>
}
