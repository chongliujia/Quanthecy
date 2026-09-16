import { t } from './i18n'
import { modelProviders, findModelProvider } from './modelProviders'
import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type Organization } from './api'
import { activeRun, runError, type AgentRun, type ModelConfiguration } from './agentTypes'
import { ErrorNotice } from './ResearchUI'

function ConfigurationForm({ value, organizationId, userId }: { value: ModelConfiguration; organizationId: string; userId: string }) {
  const client = useQueryClient()
  const [draft, setDraft] = useState(value)
  const [secret, setSecret] = useState('')
  const [clearKey, setClearKey] = useState(false)
  const [showKey, setShowKey] = useState(false)
  const [preset, setPreset] = useState(() => findModelProvider(value.base_url)?.id ?? 'custom')
  const [saved, setSaved] = useState(false)
  const [testId, setTestId] = useState('')
  const [requestId, setRequestId] = useState(() => crypto.randomUUID())
  const prefix = `/organizations/${organizationId}/agent`
  const dirty = JSON.stringify(draft) !== JSON.stringify(value) || !!secret || clearKey
  const save = useMutation({ mutationFn: () => api<ModelConfiguration>(`${prefix}/configuration`, 'PUT', {
    revision: draft.revision, provider: draft.provider, base_url: draft.base_url, model: draft.model,
    enabled: draft.enabled, daily_run_limit: draft.daily_run_limit, max_output_tokens: draft.max_output_tokens,
    ...(secret ? { api_key: secret } : {}), clear_api_key: clearKey,
  }), onSuccess: async (result) => {
    setSecret(''); setShowKey(false); setClearKey(false); setSaved(true); setDraft(result); setTestId('')
    client.setQueryData(['model-configuration', userId, organizationId], result)
    await client.invalidateQueries({ queryKey: ['agent-status', userId, organizationId] })
  } })
  const test = useMutation({ mutationFn: () => api<AgentRun>(`${prefix}/test`, 'POST', { idempotency_key: requestId }), onSuccess: (run) => { setTestId(run.id); setRequestId(crypto.randomUUID()) } })
  const result = useQuery({ queryKey: ['model-test', userId, organizationId, testId], enabled: !!testId, queryFn: () => api<AgentRun>(`${prefix}/runs/${testId}`), refetchInterval: (q) => !q.state.data || activeRun(q.state.data) ? 1500 : false })
  function submit(event: FormEvent) { event.preventDefault(); setSaved(false); save.mutate() }
  function update<K extends keyof ModelConfiguration>(key: K, next: ModelConfiguration[K]) { setSaved(false); setDraft((current) => ({ ...current, [key]: next })) }
  const changingEndpoint = draft.base_url.replace(/\/$/, '') !== value.base_url.replace(/\/$/, '')
  const needsReplacement = value.has_api_key && changingEndpoint && !secret && !clearKey
  const needsKey = draft.enabled && (draft.provider === 'anthropic' || draft.provider === 'openai' || !!findModelProvider(draft.base_url)) && !secret && (!value.has_api_key || clearKey || changingEndpoint)
  const selectedProvider = modelProviders.find((item) => item.id === preset)
  const wrongModelTarget = draft.base_url.replace(/\/$/, '') === 'https://api.openai.com/v1' && /^(deepseek|qwen|kimi|claude|gemini)/i.test(draft.model)
  const allowed = value.allowed_endpoints.includes(draft.base_url.replace(/\/$/, ''))
  function chooseProvider(id: string) {
    if (id === preset) return
    const next = modelProviders.find((item) => item.id === id)
    setPreset(id); setSaved(false)
    if (next) {
      setDraft((current) => ({ ...current, base_url: next.url, provider: next.protocol, model: '' }))
      setSecret(''); setClearKey(false)
    }
  }
  return <div className="settings-layout">
    <form id="model-configuration-form" className="panel model-settings" onSubmit={submit}>
      <div className="settings-card-heading"><span className="settings-step">01</span><div><h2>{t('Model connection')}</h2><p>{t('Choose your provider, then add a model and API key.')}</p></div><span className="settings-state">{value.has_api_key ? t('Key saved') : t('Not connected')}</span></div>
      <label htmlFor="model-service">{t('Model provider')}</label>
      <div className="provider-grid" role="group" aria-label={t('Popular providers')}>
        {modelProviders.filter((item) => ['openai', 'deepseek', 'qwen', 'moonshot', 'gemini', 'anthropic'].includes(item.id)).map((item) => <button type="button" key={item.id} className={`provider-card ${preset === item.id ? 'selected' : ''}`} aria-pressed={preset === item.id} onClick={() => chooseProvider(item.id)}><span className={`provider-avatar provider-${item.id}`}>{item.short}</span><strong>{t(item.name)}</strong><span className="provider-check">{preset === item.id ? '✓' : ''}</span></button>)}
      </div>
      <select id="model-service" value={preset} onChange={(event) => chooseProvider(event.target.value)}>{modelProviders.map((item) => <option key={item.id} value={item.id}>{t(item.name)}</option>)}<option value="custom">{t('Custom / local model')}</option></select>
      <div className="settings-field-row"><div><label htmlFor="model-endpoint">{t('API base URL')}</label><input id="model-endpoint" type="url" required maxLength={500} value={draft.base_url} onChange={(event) => { update('base_url', event.target.value); setPreset('custom') }} placeholder="https://api.example.com/v1" /></div><div><label htmlFor="model-name">{t('Model ID')}</label><input id="model-name" value={draft.model} maxLength={160} onChange={(event) => update('model', event.target.value)} placeholder={t('Exact model ID from your provider')} required={draft.enabled} /></div></div>
      <div className="field-help"><span>{t('Enter the model ID available in your provider account.')}</span>{selectedProvider && <a href={selectedProvider.docs} target="_blank" rel="noopener noreferrer">{t('Provider documentation ↗')}</a>}</div>
      {wrongModelTarget && <p className="data-warning" role="alert">{t('This model is not served by the OpenAI endpoint. Choose its provider and API base URL.')}</p>}
      {!allowed && <p className="data-warning">{t('This endpoint is not allowed by this installation. Add it to AGENT_ALLOWED_ENDPOINTS on the server before saving.')}</p>}
      <label htmlFor="model-key">{t('API key')} {value.has_api_key && <span className="badge">{t('Stored securely')}</span>}</label>
      <div className="secret-field"><input id="model-key" type={showKey ? 'text' : 'password'} value={secret} maxLength={4096} autoComplete="new-password" spellCheck={false} onChange={(event) => { setSecret(event.target.value); setClearKey(false); setSaved(false) }} placeholder={value.has_api_key ? t('Leave blank to keep the saved key') : t('Paste your API key')} disabled={!value.encryption_available} /><button type="button" aria-label={showKey ? t('Hide API key') : t('Show API key')} onClick={() => setShowKey(!showKey)}>{showKey ? t('Hide') : t('Show')}</button></div>
      <small className="field-help">{t('Encrypted on the server. The saved key is never shown again.')}</small>
      {!value.encryption_available && <div className="data-warning" role="status"><strong>{t('API key storage is not initialized.')}</strong><p>{t('Your platform operator must initialize credential storage.')}</p><button type="button" onClick={() => void client.invalidateQueries({ queryKey: ['model-configuration', userId, organizationId] })}>{t('Recheck credential storage')}</button></div>}
      {value.has_api_key && <label className="check-label"><input type="checkbox" checked={clearKey} onChange={(event) => { setClearKey(event.target.checked); setSecret(''); setSaved(false) }} />{t('Remove saved API key')}</label>}
      {(needsReplacement || needsKey) && <p className="data-warning" role="status">{t(needsReplacement ? 'Changing provider requires a new API key. The saved key will stay with its original endpoint until you replace or explicitly remove it.' : 'Add an API key before enabling this provider.')}</p>}
      {clearKey && <p className="quiet">{t('The previous key will be removed when you save. Enter a new key for this provider.')}</p>}
      <details className="advanced-model-settings"><summary>{t('Protocol & request limits')}</summary><label htmlFor="model-provider">{t('Provider protocol')}</label><select id="model-provider" value={draft.provider} onChange={(event) => update('provider', event.target.value as ModelConfiguration['provider'])}><option value="openai_compatible">{t('OpenAI-compatible · Chat Completions')}</option><option value="openai">{t("OpenAI · Chat Completions")}</option><option value="anthropic">{t("Anthropic · Messages")}</option></select><div className="settings-limits"><label>{t('Daily request limit')}<input type="number" min={1} max={100} value={draft.daily_run_limit} required onChange={(event) => update('daily_run_limit', Number(event.target.value))} /></label><label>{t('Maximum output tokens')}<input type="number" min={256} max={8000} value={draft.max_output_tokens} required onChange={(event) => update('max_output_tokens', Number(event.target.value))} /></label></div><p>{t('Limits include research and test requests, including failures. They are not a currency spending cap.')}</p><p>{t('A collaboration reserves five requests; quick research and tests reserve one. Unused reservations remain counted for the day. The output token limit applies to each request.')}</p><details><summary>{t('Allowed API addresses')}</summary><ul>{value.allowed_endpoints.map((url) => <li key={url}>{url}</li>)}</ul></details></details>
      {save.error && <p className="error" role="alert">{t(save.error.message)}</p>}{saved && <p className="save-success" role="status">{t('Configuration saved. No model request was made.')}</p>}
      <div className="settings-actions"><span>{t('Saving does not call the model.')}</span><button className="primary" disabled={save.isPending || !allowed || wrongModelTarget || needsReplacement || needsKey}>{save.isPending ? t('Saving…') : t('Save configuration')}</button></div>
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
