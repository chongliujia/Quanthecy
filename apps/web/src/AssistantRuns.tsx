import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './api'
import { runError } from './agentTypes'
import { t, locale } from './i18n'
import type { AssistantRun, AssistantRunSummary, AssistantStep } from './assistantTypes'

const active = (state: string) => ['PENDING', 'RUNNING'].includes(state)

function StepOutput({ step }: { step: AssistantStep }) {
  const output = step.output
  if (!output) return null
  if ('decision' in output) return <><strong>{t(output.decision)}</strong><p>{output.rationale.text}</p><small>{output.rationale.references.join(', ')}</small>{[...output.blocking_risks, ...output.cautions].map((c, i) => <p key={i}>{c.text}<small>{c.references.join(', ')}</small></p>)}{output.missing_evidence.map((v, i) => <p key={i}>{v}</p>)}</>
  if ('summary' in output) return <><p>{output.summary.text}</p><small>{output.summary.references.join(', ')}</small>{[...output.findings, ...output.challenges].map((c, i) => <p key={i}>{c.text}<small>{c.references.join(', ')}</small></p>)}{output.limitations.map((v, i) => <p key={i} className="quiet">{v}</p>)}</>
  return null
}

export function AssistantRunDetail({ userId, organizationId, runId, writable }: { userId: string; organizationId: string; runId: string; writable: boolean }) {
  const client = useQueryClient()
  const key = ['assistant-run', userId, organizationId, runId]
  const detail = useQuery({ queryKey: key, queryFn: () => api<AssistantRun>(`/organizations/${organizationId}/agent/runs/${runId}`), refetchInterval: query => active(query.state.data?.state ?? '') ? 2000 : false })
  const cancel = useMutation({ mutationFn: () => api(`/organizations/${organizationId}/agent/runs/${runId}/cancel`, 'POST'), onSuccess: () => { void client.invalidateQueries({ queryKey: key }); void client.invalidateQueries({ queryKey: ['assistant-runs'] }) } })
  const run = detail.data
  if (detail.error) return <p role="alert">{t(detail.error.message)}</p>
  if (!run) return <p role="status">{t('Loading…')}</p>
  return <section className="assistant-run-detail">
    <div className="paper-toolbar"><div><h3>{t(run.kind === 'ASSIST_TEST' ? 'Single-market trial' : 'Experiment review')}</h3><small>{run.assistant_name} · {new Date(run.cutoff).toLocaleString(locale())} · {run.model}</small></div><span className="badge">{t(run.state)}</span>{active(run.state) && writable && <button onClick={() => cancel.mutate()} disabled={cancel.isPending}>{t('Cancel run')}</button>}</div>
    {cancel.error && <p role="alert">{t(cancel.error.message)}</p>}
    {run.kind === 'ASSIST_TEST' && <p className="paper-notice">{t('This trial only reviews the market. It creates no orders and does not change an experiment.')}</p>}
    <p className="quiet">{t('Reserved calls')}: {run.reserved_calls} · {t('Provider calls attempted')}: {run.usage.provider_calls ?? 0} · {t('Input / output tokens reported')}: {run.usage.prompt_tokens ?? 0} / {run.usage.completion_tokens ?? 0}</p>
    {run.error_code && <p role="alert">{runError(run.error_code)}</p>}
    {run.report && <div className="paper-notice"><strong>{t(run.report.decision)}</strong> · {run.report.rationale.text}</div>}
    {!run.steps.length && <p>{t('Waiting for the worker to assemble frozen evidence.')}</p>}
    {run.steps.map((step, index) => <details className="assistant-step" key={step.id} open={step.state === 'RUNNING' || step.state === 'FAILED'}><summary><span>{index + 1}. {t(step.name)}</span><span>{t(step.state)} {step.finished_at && `· ${((Date.parse(step.finished_at) - Date.parse(step.started_at)) / 1000).toFixed(1)} s`}</span></summary><StepOutput step={step} />
      {step.model_settings && <p className="quiet">{step.model_settings.model} · {t('Effective output token limit')}: {step.model_settings.max_output_tokens.toLocaleString()} · {t('Model configuration revision')}: {step.model_settings.configuration_revision}</p>}
      {step.error_code && <p role="alert">{runError(step.error_code)}</p>}
      {step.validation_errors?.map((e, i) => <p key={i}>{e.field}: {e.code}</p>)}
      <p className="quiet">{t('Input / output tokens reported')}: {step.usage.prompt_tokens ?? 0} / {step.usage.completion_tokens ?? 0}</p>
      <details><summary>{t('Frozen node input')}</summary><pre>{JSON.stringify(step.input_packet ?? step.input_manifest, null, 2)}</pre></details>
    </details>)}
    <details><summary>{t('Referenced evidence')}</summary>{run.context?.references.map(ref => <details key={ref.id}><summary>{ref.id} · {ref.label}</summary><pre>{JSON.stringify(ref.value, null, 2)}</pre></details>)}</details>
    <details><summary>{t('Frozen workflow')}</summary><small>{run.assistant_graph_hash}</small><pre>{JSON.stringify(run.assistant_graph, null, 2)}</pre></details>
  </section>
}

export default function AssistantRuns({ userId, organizationId, writable, selectedRun }: { userId: string; organizationId: string; writable: boolean; selectedRun?: string | null }) {
  const [selected, setSelected] = useState<string | null>(selectedRun ?? null)
  const runs = useQuery({ queryKey: ['assistant-runs', userId, organizationId], queryFn: () => api<AssistantRunSummary[]>(`/organizations/${organizationId}/assistants/runs`), refetchInterval: 5000 })
  return <div className="assistant-history"><section className="panel"><h3>{t('Run history')}</h3>{runs.isPending && <p>{t('Loading…')}</p>}{runs.error && <p role="alert">{t(runs.error.message)}</p>}{runs.data?.length === 0 && <p>{t('Run a single-market trial or start an assistant comparison to see execution records.')}</p>}
    {runs.data?.map(run => <button className="assistant-run-row" key={run.id} aria-pressed={selected === run.id} onClick={() => setSelected(run.id)}><span>{run.assistant_name || t(run.kind === 'ASSIST_TEST' ? 'Single-market trial' : 'Experiment review')}<small>{new Date(run.created_at).toLocaleString(locale())} · {run.model}</small></span><span>{t(run.state)}<small>{run.usage.provider_calls ?? 0}/{run.reserved_calls} {t('model calls')}</small></span></button>)}
  </section>{selected && <div className="panel"><AssistantRunDetail key={selected} userId={userId} organizationId={organizationId} runId={selected} writable={writable} /></div>}</div>
}
