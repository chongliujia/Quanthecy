import { t } from './i18n'
import { modelProviders, findModelProvider } from './modelProviders'
import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type Organization } from './api'
import { activeRun, runError, type AgentRun, type ModelConfiguration, type ModelConnection } from './agentTypes'
import { ErrorNotice } from './ResearchUI'

function ConfigurationForm({ value, organizationId, userId }: { value: ModelConfiguration; organizationId: string; userId: string }) {
  const client = useQueryClient()
  const [draft, setDraft] = useState(value)
  const [secret, setSecret] = useState('')
  const [clearKey, setClearKey] = useState(false)
  const [showKey, setShowKey] = useState(false)
  const [preset, setPreset] = useState(() => value.provider === 'local' ? 'local' : findModelProvider(value.base_url)?.id ?? 'custom')
  const [saved, setSaved] = useState(false)
  const [testId, setTestId] = useState('')
  const [requestId, setRequestId] = useState(() => crypto.randomUUID())
  const prefix = `/organizations/${organizationId}/agent`
  const dirty = JSON.stringify(draft) !== JSON.stringify(value) || !!secret || clearKey
  const save = useMutation({ mutationFn: () => api<ModelConfiguration>(`${prefix}/configuration`, 'PUT', {
    revision: draft.revision, provider: draft.provider, base_url: draft.base_url, model: draft.model,
    enabled: draft.enabled, daily_run_limit: draft.daily_run_limit, max_output_tokens: draft.max_output_tokens,
    context_window_tokens: draft.context_window_tokens, enable_thinking: draft.enable_thinking,
    ...(secret ? { api_key: secret } : {}), clear_api_key: clearKey,
  }), onSuccess: async (result) => {
    setSecret(''); setShowKey(false); setClearKey(false); setSaved(true); setDraft(result); setTestId('')
    client.setQueryData(['model-configuration', userId, organizationId], result)
    await client.invalidateQueries({ queryKey: ['agent-status', userId, organizationId] })
    await client.invalidateQueries({ queryKey: ['assistant-status', userId, organizationId] })
  } })
  const test = useMutation({ mutationFn: () => api<AgentRun>(`${prefix}/test`, 'POST', { idempotency_key: requestId }), onSuccess: (run) => { setTestId(run.id); setRequestId(crypto.randomUUID()) } })
  const result = useQuery({ queryKey: ['model-test', userId, organizationId, testId], enabled: !!testId, queryFn: () => api<AgentRun>(`${prefix}/runs/${testId}`), refetchInterval: (q) => !q.state.data || activeRun(q.state.data) ? 1500 : false })
  function submit(event: FormEvent) { event.preventDefault(); setSaved(false); save.mutate() }
  function update<K extends keyof ModelConfiguration>(key: K, next: ModelConfiguration[K]) { setSaved(false); setDraft((current) => ({ ...current, [key]: next })) }
  const connections = value.connections ?? []
  const sameConnection = (connection: Pick<ModelConfiguration, 'provider' | 'base_url'>) => connection.provider === draft.provider && connection.base_url.replace(/\/$/, '') === draft.base_url.replace(/\/$/, '')
  const targetConnection = sameConnection(value) ? value : connections.find(sameConnection)
  const hasStoredKey = targetConnection?.has_api_key ?? false
  const isLocal = draft.provider === 'local'
  const endpointProvider = findModelProvider(draft.base_url)
  const needsKey = draft.enabled && (draft.provider === 'anthropic' || draft.provider === 'openai' || (endpointProvider && endpointProvider.id !== 'local')) && !secret && (!hasStoredKey || clearKey)
  const invalidLocalLimits = isLocal && (!draft.context_window_tokens || draft.context_window_tokens <= draft.max_output_tokens)
  const selectedProvider = modelProviders.find((item) => item.id === preset)
  const wrongModelTarget = draft.base_url.replace(/\/$/, '') === 'https://api.openai.com/v1' && /^(deepseek|qwen|kimi|claude|gemini)/i.test(draft.model)
  const allowed = value.allowed_endpoints.includes(draft.base_url.replace(/\/$/, ''))
  function restoreConnection(connection: ModelConnection | ModelConfiguration) {
    setDraft(current => ({ ...current, provider: connection.provider, base_url: connection.base_url, model: connection.model, max_output_tokens: connection.max_output_tokens, context_window_tokens: connection.context_window_tokens, enable_thinking: connection.enable_thinking }))
    setPreset(connection.provider === 'local' ? 'local' : findModelProvider(connection.base_url)?.id ?? 'custom')
    setSecret(''); setShowKey(false); setClearKey(false); setSaved(false); setTestId('')
  }
  function chooseProvider(id: string) {
    if (id === preset) return
    const next = modelProviders.find((item) => item.id === id)
    setPreset(id); setSaved(false)
    if (next) {
      const savedConnection = [value, ...connections].find(connection => next.id === 'local' ? connection.provider === 'local' : connection.provider === next.protocol && findModelProvider(connection.base_url)?.id === next.id)
      if (savedConnection) { restoreConnection(savedConnection); return }
      setDraft((current) => ({ ...current, base_url: next.url, provider: next.protocol, model: '', context_window_tokens: next.id === 'local' ? 8192 : null, enable_thinking: false, max_output_tokens: next.id === 'local' ? Math.min(current.max_output_tokens, 2048) : current.max_output_tokens }))
      setSecret(''); setShowKey(false); setClearKey(false); setTestId('')
    } else {
      update('provider', 'openai_compatible')
    }
  }
  return <div className="settings-layout">
    <form id="model-configuration-form" className="panel model-settings" onSubmit={submit}>
      <div className="settings-card-heading"><span className="settings-step">01</span><div><h2>{t('Model connection')}</h2><p>{t('Choose a cloud provider or a locally deployed model.')}</p></div><span className="settings-state">{value.provider === 'local' && value.model ? t('Local model configured') : value.has_api_key ? t('Key saved') : t('Not connected')}</span></div>
      {connections.length > 0 && <div className="saved-model-connections"><label htmlFor="saved-model-connection">{t('Saved connections')}</label><select id="saved-model-connection" value={connections.find(sameConnection)?.id ?? ''} onChange={event => { const connection = connections.find(c => c.id === event.target.value); if (connection) restoreConnection(connection) }}><option value="">{t('New connection')}</option>{connections.map(connection => <option key={connection.id} value={connection.id}>{connection.model || t('Model not configured')} · {connection.base_url}</option>)}</select><p className="field-help">{t('Each address and protocol keeps its own saved model settings and encrypted key. Switching restores that connection; save to activate it.')}</p></div>}
      <label htmlFor="model-service">{t('Model provider')}</label>
      <div className="provider-grid" role="group" aria-label={t('Popular providers')}>
        {modelProviders.filter((item) => ['local', 'openai', 'deepseek', 'qwen', 'moonshot', 'gemini', 'anthropic'].includes(item.id)).map((item) => <button type="button" key={item.id} className={`provider-card ${item.id === 'local' ? 'local-provider-card' : ''} ${preset === item.id ? 'selected' : ''}`} aria-pressed={preset === item.id} onClick={() => chooseProvider(item.id)}><span className={`provider-avatar provider-${item.id}`}>{item.short}</span><strong>{t(item.name)}</strong><span className="provider-check">{preset === item.id ? '✓' : ''}</span></button>)}
      </div>
      <select id="model-service" value={preset} onChange={(event) => chooseProvider(event.target.value)}>{modelProviders.map((item) => <option key={item.id} value={item.id}>{t(item.name)}</option>)}<option value="custom">{t('Custom API provider')}</option></select>
      <div className="settings-field-row"><div><label htmlFor="model-endpoint">{t('API base URL')}</label><input id="model-endpoint" type="url" required maxLength={500} value={draft.base_url} onChange={(event) => { update('base_url', event.target.value); setSecret(''); setShowKey(false); setClearKey(false); setPreset(isLocal ? 'local' : 'custom') }} placeholder={isLocal ? 'http://127.0.0.1:8001/v1' : 'https://api.example.com/v1'} /></div><div><label htmlFor="model-name">{t('Model ID')}</label><input id="model-name" value={draft.model} maxLength={160} onChange={(event) => update('model', event.target.value)} placeholder={t('Exact model ID from your provider')} required={draft.enabled} /></div></div>
      <div className="field-help"><span>{t(isLocal ? 'Enter the model ID served by your local inference server.' : 'Enter the model ID available in your provider account.')}</span>{selectedProvider?.docs && <a href={selectedProvider.docs} target="_blank" rel="noopener noreferrer">{t('Provider documentation ↗')}</a>}</div>
      {isLocal && <section className="local-model-settings">
        <p>{t('Local inference uses OpenAI-compatible Chat Completions and connects directly without a proxy.')}</p>
        <p className="quiet">{t('The address must be reachable from the Agent worker. In Docker, 127.0.0.1 refers to that container unless host networking is configured.')}</p>
        <label htmlFor="model-context-window">{t('Context window tokens')}<input id="model-context-window" type="number" min={512} max={1048576} required value={draft.context_window_tokens ?? 8192} onChange={(event) => update('context_window_tokens', Number(event.target.value))} /></label>
        <p className="field-help">{t('Input and output share this window. Set it to the limit configured on your model server. The server counts tokens and rejects oversized contexts; this setting does not enlarge the model window.')}</p>
        <label className="check-label"><input type="checkbox" checked={draft.enable_thinking} onChange={(event) => update('enable_thinking', event.target.checked)} />{t('Enable thinking mode')}</label>
        <p className="field-help">{t('Sends chat_template_kwargs.enable_thinking. Leave off for a non-thinking deployment.')}</p>
        {invalidLocalLimits && <p className="data-warning" role="alert">{t('Set the local model context window above the maximum output tokens.')}</p>}
      </section>}
      {wrongModelTarget && <p className="data-warning" role="alert">{t('This model is not served by the OpenAI endpoint. Choose its provider and API base URL.')}</p>}
      {!allowed && <p className="data-warning">{t('This endpoint is not allowed by this installation. Add it to AGENT_ALLOWED_ENDPOINTS on the server before saving.')}</p>}
      <label htmlFor="model-key">{t('API key')} {hasStoredKey && <span className="badge">{t('Stored securely')}</span>}</label>
      <div className="secret-field"><input id="model-key" type={showKey ? 'text' : 'password'} value={secret} maxLength={4096} autoComplete="new-password" spellCheck={false} onChange={(event) => { setSecret(event.target.value); setClearKey(false); setSaved(false) }} placeholder={hasStoredKey ? t('Leave blank to keep the saved key') : t('Paste your API key')} disabled={!value.encryption_available} /><button type="button" aria-label={showKey ? t('Hide API key') : t('Show API key')} onClick={() => setShowKey(!showKey)}>{showKey ? t('Hide') : t('Show')}</button></div>
      <small className="field-help">{t('Encrypted on the server. The saved key is never shown again.')}</small>
      {isLocal && <p className="field-help">{t('Optional for a local server without authentication. Leave blank, or enter EMPTY if your server expects a placeholder.')}</p>}
      {!value.encryption_available && !isLocal && <div className="data-warning" role="status"><strong>{t('API key storage is not initialized.')}</strong><p>{t('Your platform operator must initialize credential storage.')}</p><button type="button" onClick={() => void client.invalidateQueries({ queryKey: ['model-configuration', userId, organizationId] })}>{t('Recheck credential storage')}</button></div>}
      {hasStoredKey && <label className="check-label"><input type="checkbox" checked={clearKey} onChange={(event) => { setClearKey(event.target.checked); setSecret(''); setSaved(false) }} />{t('Remove saved API key')}</label>}
      {needsKey && <p className="data-warning" role="status">{t('Add an API key before enabling this provider.')}</p>}
      {clearKey && <p className="quiet">{t('Saving removes only this connection’s key. Other saved connections are unchanged.')}</p>}
      <details className="advanced-model-settings"><summary>{t('Protocol & request limits')}</summary><label htmlFor="model-provider">{t('Provider protocol')}</label><select id="model-provider" value={draft.provider} onChange={(event) => { const provider = event.target.value as ModelConfiguration['provider']; setDraft((current) => ({ ...current, provider, context_window_tokens: provider === 'local' ? current.context_window_tokens ?? 8192 : current.context_window_tokens })); setPreset(provider === 'local' ? 'local' : 'custom'); setSecret(''); setShowKey(false); setClearKey(false); setSaved(false) }}><option value="local">{t('Local / offline · Chat Completions')}</option><option value="openai_compatible">{t('OpenAI-compatible · Chat Completions')}</option><option value="openai">{t("OpenAI · Chat Completions")}</option><option value="anthropic">{t("Anthropic · Messages")}</option></select><div className="settings-limits"><label>{t('Daily request limit')}<input type="number" min={1} max={100} value={draft.daily_run_limit} required onChange={(event) => update('daily_run_limit', Number(event.target.value))} /></label><label>{t('Maximum output tokens')}<input type="number" min={256} max={value.max_output_tokens_limit ?? 65536} value={draft.max_output_tokens} required onChange={(event) => update('max_output_tokens', Number(event.target.value))} /></label></div><p>{t('Output allowance per request, including reasoning where the provider counts it. The model may use less. Choose a value supported by your model; this does not increase evidence context or report field limits.')}</p><p>{t(isLocal ? 'Local requests allow up to five minutes for inference.' : 'Budgets above 8,000 tokens allow up to five minutes per model request. Larger budgets can increase waiting time and cost.')}</p><p>{t('Limits include research and test requests, including failures. They are not a currency spending cap.')}</p><p>{t('A collaboration reserves five requests; quick research and tests reserve one. Unused reservations remain counted for the day. The output token limit applies to each request.')}</p><details><summary>{t('Allowed API addresses')}</summary><ul>{value.allowed_endpoints.map((url) => <li key={url}>{url}</li>)}</ul></details></details>
      {save.error && <p className="error" role="alert">{t(save.error.message)}</p>}{saved && <p className="save-success" role="status">{t('Configuration saved. No model request was made.')}</p>}
      <div className="settings-actions"><span>{t('Saving does not call the model.')}</span><button className="primary" disabled={save.isPending || !allowed || wrongModelTarget || !!needsKey || invalidLocalLimits}>{save.isPending ? t('Saving…') : t('Save configuration')}</button></div>
    </form>
    <div className="settings-side">
      <section className="panel analysis-settings"><span className="settings-step">02</span><h3>{t('On-demand research')}</h3><p>{t('You decide when the analyst runs. Saving a connection never starts an analysis.')}</p><label className="enable-research"><span><strong>{t('Enable analysis')}</strong><small>{draft.enabled ? t('Ready for explicit requests') : t('Currently disabled')}</small></span><input form="model-configuration-form" role="switch" type="checkbox" checked={draft.enabled} onChange={(event) => update('enabled', event.target.checked)} aria-label={t('Enable on-demand analysis for this workspace')} /></label><div className="settings-summary"><span>{t('Daily request limit')}<b>{draft.daily_run_limit}</b></span><span>{t('Maximum output tokens')}<b>{draft.max_output_tokens.toLocaleString()}</b></span></div></section>
      <section className="panel connection-test"><span className="settings-step">03</span><h3>{t('Test connection')}</h3><p>{t('Optional. Sends one small request to the saved model and may incur a provider charge.')}</p><button disabled={dirty || !value.model || test.isPending || (!!result.data && activeRun(result.data))} onClick={() => test.mutate()}>{test.isPending || (result.data && activeRun(result.data)) ? t('Testing connection…') : t('Send test request')}</button>{dirty && <p className="quiet">{t('Save your changes before testing.')}</p>}
        {test.error && <p role="alert" className="error">{t(test.error.message)}</p>}{result.error && <ErrorNotice error={result.error} retry={() => void result.refetch()} />}
        {result.data?.state === 'SUCCEEDED' && <p className="save-success" role="status">{t('Connection verified. The model returned valid JSON.')}</p>}{result.data?.state === 'FAILED' && <p className="error" role="alert">{runError(result.data.error_code)}</p>}
      </section>
      <p className="settings-footnote">{t('Workspace owners manage connections. Reports keep their model version and evidence cutoff.')}</p>
    </div>
  </div>
}

export default function ModelSettings({ userId, organization }: { userId: string; organization?: Organization }) {
  const query = useQuery({ queryKey: ['model-configuration', userId, organization?.id], enabled: organization?.role === 'OWNER', queryFn: () => api<ModelConfiguration>(`/organizations/${organization!.id}/agent/configuration`) })
  if (!organization) return <p>{t("Select a workspace to configure its model.")}</p>
  if (organization.role !== 'OWNER') return <section className="panel"><h2>{t("Model connection")}</h2><p>{t("Ask your workspace owner to configure the model connection and request limits.")}</p></section>
  return <>{query.isPending && <p role="status">{t("Loading model configuration…")}</p>}{query.error && <ErrorNotice error={query.error} retry={() => void query.refetch()} />}{query.data && <ConfigurationForm key={organization.id} value={query.data} organizationId={organization.id} userId={userId} />}</>
}
