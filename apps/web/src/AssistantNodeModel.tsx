import type { AgentStatus } from './agentTypes'
import type { AssistantNode } from './assistantTypes'
import { effectiveOutputLimit } from './assistantConfiguration'
import { t } from './i18n'

export default function AssistantNodeModel({ node, status, disabled, onPatch }: {
  node: AssistantNode; status?: AgentStatus; disabled: boolean; onPatch: (patch: Partial<AssistantNode>) => void
}) {
  const trial = effectiveOutputLimit(node, status?.max_output_tokens)
  const paper = effectiveOutputLimit(node, status?.max_output_tokens, true)
  return <div className="assistant-model-config">
    <span className="eyebrow">{t('WORKSPACE MODEL')}</span>
    <strong>{status?.model || t('Model not configured')}</strong>
    <p className="assistant-help">{t('All nodes inherit this workspace model. Changing a role or its name does not select a different model.')}</p>
    <a href="#/model-settings">{t('Model settings')} ↗</a>
    <label>{t('Node output token limit')}<input type="number" min="256" max="65536" step="1" placeholder={t('Inherit workspace limit')} value={node.max_output_tokens ?? ''} disabled={disabled} onChange={e => onPatch({ max_output_tokens: e.target.value === '' ? null : Number(e.target.value) })} /></label>
    <dl className="assistant-effective-limits"><div><dt>{t('Effective trial limit')}</dt><dd>{trial?.toLocaleString() ?? '—'}</dd></div><div><dt>{t('Effective experiment limit')}</dt><dd>{paper?.toLocaleString() ?? '—'}</dd></div></dl>
    <p className="assistant-help">{t('The smaller node and workspace limits apply. Automatic experiment reviews also cap each call at 2,048 output tokens. These are ceilings, not expected usage or cost.')}</p>
    <p className="assistant-help">{t('A low output limit can truncate a report and fail validation. Provider reasoning may use this allowance. Limits are frozen when you publish or run a trial.')}</p>
  </div>
}
