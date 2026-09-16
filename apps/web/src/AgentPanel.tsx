import { t, useLanguage } from './i18n'
import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type Organization } from './api'
import { activeRun, runError, type AgentRun, type AgentStatus, type Claim, type ResearchSkill } from './agentTypes'
import { ExpertTeam, ForecastView } from './IntelligenceView'
import ValidationNotice from './ValidationNotice'
import { ErrorNotice } from './ResearchUI'
import { readable, time } from './format'

export default function AgentPanel({ userId, organization, marketId, cutoff }: { userId: string; organization?: Organization; marketId: string; cutoff: string }) {
  const client = useQueryClient()
  const language = useLanguage()
  const [workflow, setWorkflow] = useState<'single' | 'team'>('team')
  const [selected, setSelected] = useState('')
  const [requestId, setRequestId] = useState(() => crypto.randomUUID())
  const prefix = `/organizations/${organization?.id}/agent`
  const key = ['agent-runs', userId, organization?.id, marketId]
  const status = useQuery({ queryKey: ['agent-status', userId, organization?.id], enabled: !!organization, queryFn: () => api<AgentStatus>(`${prefix}/status`) })
  const skills = useQuery({ queryKey: ['agent-skills', userId, organization?.id], enabled: !!organization, queryFn: () => api<ResearchSkill[]>(`${prefix}/skills`) })
  const requiredCalls = workflow === 'team' ? skills.data?.length ?? 5 : 1
  const budgetAvailable = !!status.data && status.data.daily_run_limit - status.data.runs_today >= requiredCalls
  const runs = useQuery({ queryKey: key, enabled: !!organization, queryFn: () => api<AgentRun[]>(`${prefix}/runs?market_id=${marketId}`), refetchInterval: (q) => q.state.data?.some(activeRun) ? 2000 : 15000 })
  const current = runs.data?.find((run) => run.id === selected) ?? runs.data?.[0]
  const detail = useQuery({ queryKey: ['agent-run', userId, organization?.id, current?.id, current?.state, current?.stage], enabled: !!current, queryFn: () => api<AgentRun>(`${prefix}/runs/${current!.id}`) })
  const run = detail.data ?? current
  const create = useMutation({ mutationFn: () => api<AgentRun>(`${prefix}/markets/${marketId}/runs`, 'POST', { idempotency_key: requestId, cutoff: cutoff || null, workflow, language }), onSuccess: async (result) => { setSelected(result.id); setRequestId(crypto.randomUUID()); await client.invalidateQueries({ queryKey: key }); await client.invalidateQueries({ queryKey: ['agent-status', userId, organization?.id] }) } })
  const cancel = useMutation({ mutationFn: () => api(`${prefix}/runs/${current!.id}/cancel`, 'POST'), onSuccess: () => client.invalidateQueries({ queryKey: key }) })
  function claim(item: Claim, index: number) {
    return <article className="agent-claim" key={`${item.text}-${index}`}><span className="micro-label">{readable(item.kind)}</span><p>{item.text}</p><div className="reference-chips">{item.references.map((id) => <a key={id} href={`#reference-${run?.id}-${id}`} onClick={(event) => { event.preventDefault(); const target = document.getElementById(`reference-${run?.id}-${id}`); for (let node = target; node; node = node.parentElement) { if (node instanceof HTMLDetailsElement) node.open = true } target?.scrollIntoView({ block: 'nearest' }) }}>{run?.context?.references.find((ref) => ref.id === id)?.label ?? id}</a>)}</div></article>
  }
  if (!organization) return <p className="terminal-empty">{t("Select a workspace to access research reports.")}</p>
  return <section className="agent-panel">
    <div className="panel-kicker"><span className="agent-glyph">✧</span><div><strong>{t("Intelligence desk")}</strong><small>{t("Specialist research · Shared evidence · Risk review")}</small></div></div>
    {status.isPending && <p role="status">{t("Loading model status…")}</p>}
    {status.error && <ErrorNotice error={status.error} retry={() => void status.refetch()} />}
    {status.data && <>
      <div className="agent-model"><span className={`connection-dot ${status.data.enabled ? '' : 'offline'}`} />{status.data.enabled ? status.data.model : t("Model not enabled")}</div>
      {status.data.configuration_issue && <p className="data-warning">{t(status.data.configuration_issue === 'missing_key' ? 'Add an API key in Model settings before starting analysis.' : status.data.configuration_issue === 'missing_model' ? 'Add a model ID in Model settings before starting analysis.' : 'Check the provider and API address in Model settings.')}</p>}
      {!status.data.enabled && <p>{t("Configure a model in your workspace to generate a research report. No model request runs until you explicitly start one.")}</p>}
      {status.data.can_manage && <a className="terminal-link" href="#/model-settings">{t("Model settings ↗")}</a>}
      <div className="workflow-switch" role="group" aria-label={t('Research mode')}>{(['team', 'single'] as const).map(mode => <button key={mode} aria-pressed={workflow === mode} disabled={create.isPending} onClick={() => { setWorkflow(mode); setRequestId(crypto.randomUUID()); create.reset() }}>{t(mode === 'team' ? 'Expert collaboration' : 'Quick research')}</button>)}</div>
      <p className="request-estimate">{t('Reserves up to {count} model requests. Uses your saved provider and may incur charges.', { count: requiredCalls })}</p>
      <button className="primary analyze-button" disabled={!status.data.can_run || !budgetAvailable || create.isPending || runs.data?.some(activeRun) || (workflow === 'team' && !skills.data?.length)} onClick={() => create.mutate()}>{create.isPending ? t("Queuing analysis…") : t("✧  Analyze this market")}</button>
      <small>{status.data.runs_today} / {status.data.daily_run_limit} {t("reserved requests today · UTC")}</small>
      {!budgetAvailable && status.data.can_run && <p className="data-warning">{t('Not enough daily request capacity for this workflow.')}</p>}
      {cutoff && <p className="selection-note">{t("Analyze evidence known by")} {time(cutoff)}.</p>}
      {organization.role === 'VIEWER' && <p>{t("Viewer access: you can read this workspace's reports.")}</p>}
    </>}
    {create.error && <p className="error" role="alert">{t(create.error.message)}</p>}
    {skills.error && <ErrorNotice error={skills.error} retry={() => void skills.refetch()} />}
    {(workflow === 'team' || run?.workflow === 'team') && skills.data && <ExpertTeam skills={skills.data} run={run?.workflow === 'team' ? run : undefined} claim={claim} />}
    {runs.error && <ErrorNotice error={runs.error} retry={() => void runs.refetch()} />}
    {!!runs.data?.length && <label className="run-picker">{t("Research history")}<select value={current?.id} onChange={(event) => setSelected(event.target.value)}>{runs.data.map((item) => <option value={item.id} key={item.id}>{time(item.created_at)} · {readable(item.state)}</option>)}</select></label>}
    {detail.error && <ErrorNotice error={detail.error} retry={() => void detail.refetch()} />}
    {run && <div className="run-result" key={run.id}>
      <div className="run-state"><span className={`badge ${activeRun(run) ? 'working-badge' : ''}`}>{readable(run.state)}</span><small>{readable(run.stage)}</small></div>
      {activeRun(run) && <><div className="research-progress" role="status" aria-label={`Research ${run.stage}`}><span /></div><p>{t("Metrics → event evidence → contract review → counter-evidence → report")}</p>{status.data?.can_run && <button className="text-button" disabled={cancel.isPending} onClick={() => cancel.mutate()}>{t("Cancel research")}</button>}</>}
      {cancel.error && <p role="alert" className="error">{t(cancel.error.message)}</p>}
      {run.state === 'FAILED' && (run.error_code === 'invalid_report' ? <ValidationNotice issues={run.validation_errors} stage={run.steps?.find(step => step.state === 'FAILED')?.name} /> : <p className="error" role="alert">{runError(run.error_code)}</p>)}
      {run.state === 'CANCELLED' && <p>{t("This request was cancelled. Any already submitted model call may still incur usage.")}</p>}
      {run.report && <>
        <h3>{t('Synthesis report')}</h3>
        <div className="research-decision"><span>{t(run.report.action)}</span><strong>{Math.round(run.report.confidence * 100)}<small>%</small></strong></div>
        <p className="confidence-note">{t("Agent confidence in research priority. Not an event probability or calibrated accuracy.")}</p>
        {claim(run.report.thesis, 0)}
        {run.report.claims.map(claim)}
        <ForecastView run={run} claim={claim} />
        {!!run.report.disagreements?.length && <><h4>{t('Expert disagreements')}</h4>{run.report.disagreements.map(claim)}</>}
        <h4>{t("Counter-evidence")}</h4>{run.report.counter_evidence.length ? run.report.counter_evidence.map(claim) : <p>{t("No counter-evidence identified in this bounded context.")}</p>}
        <h4>{t("Research limitations")}</h4><ul>{run.report.risk_flags.map((flag, i) => <li key={i}>{flag}</li>)}</ul>
        <h4>{t("Next observations")}</h4><ul>{run.report.follow_up.map((item, i) => <li key={i}>{item}</li>)}</ul>
      </>}
      {!!run.context?.references?.length && <details className="reference-library"><summary>{t('Frozen references')} · {run.context.references.length}</summary>{run.context.references.map((ref) => <details id={`reference-${run.id}-${ref.id}`} className="frozen-reference" key={ref.id}><summary>{ref.label}</summary><pre>{typeof ref.value === 'string' ? ref.value : JSON.stringify(ref.value, null, 2)}</pre>{ref.url && <a href={ref.url} target="_blank" rel="noopener noreferrer">{t("Open source ↗")}</a>}</details>)}</details>}
      <p className="run-provenance">{t("Cutoff")} {time(run.cutoff)}<br />{run.model} · {run.prompt_version} {t("· configuration v")}{run.configuration_revision}</p>
    </div>}
    {!runs.data?.length && !runs.isPending && <div className="agent-empty"><span>◇</span><strong>{t("Your research starts here")}</strong><p>{t("Reports connect market observations, event evidence and contract rules in one place.")}</p></div>}
  </section>
}
