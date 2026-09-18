import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import { runError } from './agentTypes'
import { t, locale } from './i18n'
import TerminalDialog from './TerminalDialog'
import { paperReasons, type PaperLabData, type PaperReviewDetail } from './paperTypes'

const seconds = (value: number | null) => value == null ? '—' : `${value.toFixed(1)} s`
export default function PaperReviewPanel({ userId, organizationId, experiment }: { userId: string; organizationId: string; experiment: PaperLabData }) {
  const [selected, setSelected] = useState<string | null>(null)
  const detail = useQuery({ queryKey: ['paper-review', userId, organizationId, selected], queryFn: () => api<PaperReviewDetail>(`/organizations/${organizationId}/paper/opportunities/${selected}`), enabled: !!selected })
  const stats = experiment.review_summary!
  const result = detail.data
  return <section className="panel paper-reviews"><div className="paper-intro"><h3>{t('Automatic entry reviews')}</h3><span className="badge">{stats.model_ready ? t('Model ready') : t('Waiting for model configuration')}</span></div>
    {!stats.model_ready && <p className="paper-notice">{t('Configure and enable a model in this workspace. Eligible signals will then request reviews automatically. Baseline accounts keep running.')} <a href="#/model-settings">{t('Model settings')}</a></p>}
    <p className="quiet">{t('Daily review reservations')} {stats.calls_today} / {stats.daily_limit} · {t('Remaining within both limits')} {stats.calls_remaining} · {stats.model || t('No model configured')}</p>
    <div className="paper-review-metrics"><dl><dt>{t('Eligible candidates / completed reviews')}</dt><dd>{stats.candidates} / {stats.reviewed}</dd><dt>{t('Allow / reject / wait')}</dt><dd>{stats.allowed} / {stats.rejected} / {stats.abstained}</dd><dt>{t('Expired or invalidated / failed')}</dt><dd>{stats.invalidated} / {stats.failed}</dd><dt>{t('Awaiting review or application')}</dt><dd>{stats.waiting}</dd></dl><dl><dt>{t('Participation in matched baseline entries')}</dt><dd>{stats.participation == null ? '—' : `${(stats.participation * 100).toFixed(1)}%`} ({stats.paired_agent_entries}/{stats.paired_candidates})</dd><dt>{t('Average signal-to-report time')}</dt><dd>{seconds(stats.average_latency_seconds)}</dd><dt>{t('Average queue wait')}</dt><dd>{seconds(stats.average_queue_seconds)}</dd></dl><dl><dt>{t('Provider calls attempted')}</dt><dd>{stats.provider_calls}</dd><dt>{t('Input / output tokens reported')}</dt><dd>{stats.prompt_tokens} / {stats.completion_tokens}</dd><dt>{t('Model cost in USD')}</dt><dd>{stats.model_cost_usd ?? t('Unavailable')}</dd></dl></div>
    <p className="quiet">{t('Participation counts candidates with an actual baseline fill and checks whether the Agent also filled. Missing reports and model refusals are recorded separately. Model charges are not deducted from virtual balances; absent billing data is not treated as zero cost.')}</p>
    <div className="table-scroll"><table><thead><tr><th>{t('Market')}</th><th>{t('Review / result')}</th><th>{t('Reason')}</th><th>{t('Baseline / Agent filled')}</th><th>{t('Details')}</th></tr></thead><tbody>{experiment.recent_reviews?.map(r => <tr key={r.id}><td>{r.title}{r.assistant_label && <small>{r.assistant_label}</small>}<small>{new Date(r.detected_at).toLocaleString(locale())}</small></td><td>{t(r.review_decision ?? r.run_state ?? 'WAIT')}<small>{t(r.state)}</small></td><td>{t(paperReasons[r.reason] ?? r.reason)}{r.error_code && <small>{r.error_code.startsWith('paper_') ? t(paperReasons[r.reason] ?? r.reason) : runError(r.error_code)}</small>}</td><td>{r.baseline_filled ? '✓' : '—'} / {r.agent_filled ? '✓' : '—'}</td><td><button onClick={() => setSelected(r.id)}>{t('Inspect entry review')}</button></td></tr>)}</tbody></table></div>
    {!experiment.recent_reviews?.length && <p>{t('No eligible entry signal yet. The experiment does not call a model merely to fill the queue.')}</p>}
    <TerminalDialog open={!!selected} onClose={() => setSelected(null)} title={t('Entry review evidence')} className="paper-dialog">
      {detail.isPending && <p role="status">{t('Loading…')}</p>}{detail.error && <p role="alert">{t(detail.error.message)}</p>}
      {result && <><h3>{result.title}</h3><p>{t(paperReasons[result.reason] ?? result.reason)}</p>{result.report && <><strong>{t(result.report.decision)}</strong><p>{result.report.rationale.text}</p><h4>{t('Blocking risks')}</h4>{result.report.blocking_risks.length ? result.report.blocking_risks.map((c, i) => <p key={i}>{c.text}<small>{c.references.join(', ')}</small></p>) : <p>—</p>}<h4>{t('General cautions')}</h4>{result.report.cautions.map((c, i) => <p key={i}>{c.text}<small>{c.references.join(', ')}</small></p>)}<h4>{t('Missing essential evidence')}</h4>{result.report.missing_evidence.map((v, i) => <p key={i}>{v}</p>)}</>}
      <details><summary>{t('Frozen review and entry evidence')}</summary><pre>{JSON.stringify({ inputs: result.inputs, context: result.context, report: result.report, usage: result.usage }, null, 2)}</pre></details></>}
    </TerminalDialog>
  </section>
}
