import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import type { AgentStatus } from './agentTypes'
import { nodeNames, type AssistantGraph } from './assistantTypes'
import { effectiveOutputLimit } from './assistantConfiguration'
import { graphIssues } from './assistantGraph'
import { t } from './i18n'

type Policy = {
  entry_change_15m: string; market_budget_fraction: string; event_budget_fraction: string
  max_spread: string; max_quote_age_seconds: number; holding_minutes: number
}

export default function AssistantConfiguration({ graph, status, userId, organizationId, disabled, onGraph, onEdit }: {
  graph: AssistantGraph; status?: AgentStatus; userId: string; organizationId: string; disabled: boolean
  onGraph: (graph: AssistantGraph) => void; onEdit: (id: string, tab: 'prompt' | 'model' | 'inputs') => void
}) {
  const policy = useQuery({ queryKey: ['paper-policy', userId, organizationId], queryFn: () => api<Policy>(`/organizations/${organizationId}/paper/policy`) })
  const remaining = status ? Math.max(0, status.daily_run_limit - status.runs_today) : null
  const limits = graph.nodes.map(node => effectiveOutputLimit(node, status?.max_output_tokens, true))
  const output = limits.some(limit => limit == null) ? null : limits.reduce<number>((sum, limit) => sum + (limit ?? 0), 0)
  const issues = graphIssues(graph)
  return <div className="assistant-configuration">
    <div className="assistant-config-heading"><div><span className="eyebrow">{t('TEAM CONFIGURATION')}</span><h3>{t('Roles, model and safeguards')}</h3><p>{t('Define responsibilities first, connect the findings, then check the execution budget.')}</p></div><a href="#/model-settings">{t('Model settings')} ↗</a></div>
    <dl className="assistant-config-metrics">
      <div><dt>{t('Shared model')}</dt><dd>{status?.model || t('Model not configured')}</dd><small>{t('All roles inherit the workspace model')}</small></div>
      <div><dt>{t('Calls per review')}</dt><dd>{graph.nodes.length}</dd><small>{t('One request per node; no automatic retries')}</small></div>
      <div><dt>{t('Experiment output ceiling')}</dt><dd>{output?.toLocaleString() ?? '—'}</dd><small>{t('Sum of per-node output limits, not a cost estimate')}</small></div>
      <div><dt>{t('Workspace calls remaining')}</dt><dd>{remaining ?? '—'}</dd><small>{t('Shared by research and experiment reviews; resets at UTC midnight')}</small></div>
    </dl>
    {status && (!status.enabled || !status.model || status.configuration_issue) && <p className="paper-notice">{t('Model configuration needs attention. You can continue editing and publishing; model execution remains unavailable.')}</p>}
    {remaining != null && remaining < graph.nodes.length && <p className="paper-notice">{t('Not enough model calls remaining for this workflow.')}</p>}
    <div className="assistant-config-table" role="region" aria-label={t('Team responsibilities')} tabIndex={0}><table><thead><tr><th>{t('Role')}</th><th>{t('Upstream findings')}</th><th>{t('Required output')}</th><th>{t('Experiment token limit')}</th><th>{t('Configure')}</th></tr></thead><tbody>{graph.nodes.map(node => {
      const parents = graph.edges.filter(edge => edge.target === node.id).map(edge => graph.nodes.find(n => n.id === edge.source)).filter(n => n != null)
      return <tr key={node.id}><td><strong>{t(node.label)}</strong><small>{t(nodeNames[node.kind])}</small></td><td>{parents.length ? parents.map(n => t(n.label)).join(' · ') : t('Independent analysis')}</td><td>{t(node.kind === 'review' ? 'ALLOW / REJECT / WAIT with cited reasons' : node.kind === 'risk' ? 'Challenges, disagreements and evidence gaps' : 'Cited findings, limitations and follow-up')}</td><td>{effectiveOutputLimit(node, status?.max_output_tokens, true)?.toLocaleString() ?? '—'}</td><td><div className="assistant-config-links"><button onClick={() => onEdit(node.id, 'prompt')}>{t('Role method')}</button><button onClick={() => onEdit(node.id, 'inputs')}>{t('Inputs')}</button><button onClick={() => onEdit(node.id, 'model')}>{t('Model')}</button></div></td></tr>
    })}</tbody></table></div>
    <p className="assistant-help">{t('Every node receives frozen market evidence. Connections add validated upstream findings. Independent analysts do not see each other’s conclusions; all analysis must pass through risk review before entry review.')}</p>
    <p className="assistant-help">{t('Calls execute sequentially in a shared workspace queue. More nodes can increase latency and cause an opportunity to expire; peer agreement does not establish accuracy.')}</p>
    {issues.length > 0 && <div className="assistant-config-issues" role="status"><strong>{t('Workflow needs attention')}</strong>{issues.map((issue, i) => <button key={i} onClick={() => onEdit(issue.nodeId, 'inputs')}>{t(graph.nodes.find(n => n.id === issue.nodeId)?.label ?? issue.nodeId)} · {t(issue.message)}</button>)}</div>}
    <section className="assistant-config-risk"><div><span className="eyebrow">{t('ENTRY & RISK')}</span><h3>{t('Signal filter and execution safeguards')}</h3><label>{t('Minimum 15m movement (pp)')}<input type="number" min="2" max="20" step="0.5" value={Math.round(graph.entry_change_15m * 10000) / 100} disabled={disabled} onChange={e => { const value = Number(e.target.value); if (Number.isFinite(value)) onGraph({ ...graph, entry_change_15m: value / 100 }) }} /></label><p className="assistant-help">{t('Additional signal filter. The baseline threshold is 2 pp.')}</p></div><div><h4>{t('New experiment safeguards')}</h4><p className="assistant-help">{t('Enforced by the simulation engine. Prompts cannot relax these limits. Existing experiments retain their frozen policy.')}</p>{policy.error ? <p role="alert">{t('Unable to load execution safeguards.')} <button onClick={() => void policy.refetch()}>{t('Retry')}</button></p> : !policy.data ? <p role="status">{t('Loading…')}</p> : <dl className="assistant-policy-values">
      <div><dt>{t('Per-market capital cap')}</dt><dd>{Number(policy.data.market_budget_fraction) * 100}%</dd></div>
      <div><dt>{t('Per-event capital cap')}</dt><dd>{Number(policy.data.event_budget_fraction) * 100}%</dd></div>
      <div><dt>{t('Maximum spread')}</dt><dd>{Number(policy.data.max_spread) * 100} pp</dd></div>
      <div><dt>{t('Maximum quote age')}</dt><dd>{policy.data.max_quote_age_seconds} s</dd></div>
      <div><dt>{t('Strategy holding limit')}</dt><dd>{policy.data.holding_minutes} min</dd></div>
    </dl>}</div></section>
  </div>
}
