import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type Organization } from './api'
import type { AgentStatus } from './agentTypes'
import type { Assistant, AssistantGraph, AssistantNode, AssistantRun, AssistantVersion } from './assistantTypes'
import type { PaperCandidate } from './paperTypes'
import { t, locale } from './i18n'
import AssistantCanvas, { type CanvasView } from './AssistantCanvas'
import AssistantIcon from './AssistantIcon'
import AssistantNodeInspector from './AssistantNodeInspector'
import { nodeConfigurationError } from './assistantConfiguration'
import AssistantConfiguration from './AssistantConfiguration'
import { AssistantRunDetail } from './AssistantRuns'
import TerminalDialog from './TerminalDialog'

export default function AssistantBuilder({ userId, organization, onCompare }: { userId: string; organization: Organization; onCompare: (id: string) => void }) {
  const client = useQueryClient(), path = `/organizations/${organization.id}/assistants`
  const key = ['assistants', userId, organization.id]
  const list = useQuery({ queryKey: key, queryFn: () => api<Assistant[]>(path) })
  const [selectedId, setSelectedId] = useState<string | null>(null), [dirty, setDirty] = useState(false)
  const [pending, setPending] = useState<(() => void) | null>(null)
  const selected = list.data?.find(a => a.id === selectedId) ?? list.data?.[0]
  const writable = organization.role !== 'VIEWER'
  const change = (action: () => void) => { if (dirty) setPending(() => action); else action() }
  const create = useMutation({ mutationFn: (source?: Assistant) => api<Assistant>(path, 'POST', { name: source ? `${t(source.name).slice(0, 100)} · ${t('Copy')}` : t('My trading assistant'), source_id: source?.id ?? null }), onSuccess: data => { client.setQueryData<Assistant[]>(key, old => [data, ...old ?? []]); setSelectedId(data.id); setDirty(false) } })
  const changed = (data: Assistant) => { client.setQueryData<Assistant[]>(key, old => old?.map(a => a.id === data.id ? data : a)); setDirty(false) }
  return <div className="assistant-studio">
    <header className="assistant-studio-heading"><div><span className="eyebrow">{t('PAPER LAB / AGENT STUDIO')}</span><h2>{t('Build your research team')}</h2><p>{t('Shape how your agents think, collaborate and review every opportunity.')}</p></div><span className="assistant-studio-badge"><AssistantIcon kind="team" />{t('Simulation only')}</span></header>
    <div className="assistant-library-bar"><div><AssistantIcon kind="team" /><label><span>{t('My assistants')}</span><select aria-label={t('My assistants')} value={selected?.id ?? ''} disabled={!list.data?.length || create.isPending} onChange={e => { const id = e.target.value; change(() => { setSelectedId(id); setDirty(false) }) }}>{!list.data?.length && <option value="">{t('No assistants yet')}</option>}{list.data?.map(a => <option value={a.id} key={a.id}>{t(a.name)}{a.is_default ? ` · ${t('Default')}` : ''}</option>)}</select></label></div><div><button disabled={!writable || !selected || create.isPending} onClick={() => change(() => create.mutate(selected))}>{t('Copy assistant')}</button><button disabled={!writable || create.isPending} onClick={() => change(() => create.mutate(undefined))}>＋ {t('Use default template')}</button></div></div>
    {create.error && <p role="alert" className="error">{t(create.error.message)}</p>}{list.error && <p role="alert" className="error">{t(list.error.message)} <button onClick={() => void list.refetch()}>{t('Retry')}</button></p>}{list.isPending && <p role="status">{t('Loading…')}</p>}
    {selected ? <AssistantEditor key={selected.id} assistant={selected} userId={userId} organization={organization} onSaved={changed} onDirty={setDirty} onCompare={onCompare} onCopy={() => create.mutate(selected)} /> : !list.isPending && !list.error && <section className="assistant-empty"><div className="assistant-empty-diagram"><span><AssistantIcon kind="quant" /></span><span><AssistantIcon kind="events" /></span><span><AssistantIcon kind="pricing" /></span><i /><span><AssistantIcon kind="risk" /></span></div><h3>{t('Your first team is ready to build')}</h3><p>{t('Start with five connected specialists. Give each one a prompt and the skills to make it your own.')}</p><button className="primary" disabled={!writable || create.isPending} onClick={() => create.mutate(undefined)}>{t('Create my first assistant')} →</button><small>{t('Saving and publishing do not call the model.')}</small></section>}
    <TerminalDialog open={!!pending} onClose={() => setPending(null)} title={t('Unsaved changes')}><p>{t('Save this draft before switching, or discard the unsaved changes.')}</p><div className="assistant-dialog-footer"><button onClick={() => setPending(null)}>{t('Keep editing')}</button><button onClick={() => { pending?.(); setPending(null) }}>{t('Discard and continue')}</button></div></TerminalDialog>
  </div>
}

function AssistantEditor({ assistant, userId, organization, onSaved, onDirty, onCompare, onCopy }: { assistant: Assistant; userId: string; organization: Organization; onSaved: (a: Assistant) => void; onDirty: (dirty: boolean) => void; onCompare: (id: string) => void; onCopy: () => void }) {
  const client = useQueryClient(), path = `/organizations/${organization.id}/assistants/${assistant.id}`
  const [baseline, setBaseline] = useState(assistant), [graph, setGraph] = useState<AssistantGraph>(structuredClone(assistant.draft))
  const [name, setName] = useState(assistant.name), [selected, setSelected] = useState<string | null>(graph.nodes[0]?.id ?? null)
  const [market, setMarket] = useState(''), [runId, setRunId] = useState<string | null>(null), [tab, setTab] = useState('workflow')
  const [versions, setVersions] = useState(assistant.versions), [message, setMessage] = useState('')
  const [past, setPast] = useState<AssistantGraph[]>([]), [future, setFuture] = useState<AssistantGraph[]>([])
  const groupRef = useRef({ key: '', at: 0 })
  const canvasView = useRef<CanvasView | null>(null), editor = useRef<HTMLElement>(null), inspector = useRef<HTMLDivElement>(null)
  const [inspectorOpen, setInspectorOpen] = useState(true), [fullscreen, setFullscreen] = useState(false)
  const [editRequest, setEditRequest] = useState<{ tab: 'prompt' | 'skills' | 'model' | 'inputs'; revision: number }>({ tab: 'prompt', revision: 0 })
  useEffect(() => {
    const changed = () => setFullscreen(document.fullscreenElement === editor.current)
    document.addEventListener('fullscreenchange', changed)
    return () => document.removeEventListener('fullscreenchange', changed)
  }, [])
  const toggleFullscreen = async () => {
    try {
      if (document.fullscreenElement === editor.current) await document.exitFullscreen()
      else if (editor.current?.requestFullscreen) await editor.current.requestFullscreen()
      else setMessage(t('Fullscreen is unavailable in this browser.'))
    } catch { setMessage(t('Fullscreen is unavailable in this browser.')) }
  }
  const editNode = (id: string, tab: 'prompt' | 'skills' | 'model' | 'inputs') => {
    setTab('workflow')
    setSelected(id); setInspectorOpen(true); setEditRequest(previous => ({ tab, revision: previous.revision + 1 }))
    if (window.matchMedia('(max-width: 900px)').matches) requestAnimationFrame(() => inspector.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
  }
  const writable = organization.role !== 'VIEWER', editable = writable && !assistant.is_default
  const dirty = name !== baseline.name || JSON.stringify(graph) !== JSON.stringify(baseline.draft)
  const node = graph.nodes.find(n => n.id === selected)
  const customizationError = graph.nodes.map(nodeConfigurationError).find(Boolean)
    ?? (graph.entry_change_15m < .02 || graph.entry_change_15m > .20 ? 'The entry threshold must be between 2 and 20 pp.' : null)
  useEffect(() => { onDirty(dirty) }, [dirty, onDirty])
  useEffect(() => {
    if (!dirty) return
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = '' }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])
  const candidates = useQuery({ queryKey: ['assistant-candidates', userId, organization.id], queryFn: () => api<PaperCandidate[]>(`/organizations/${organization.id}/paper/candidates`), enabled: tab === 'trial' })
  const status = useQuery({ queryKey: ['assistant-status', userId, organization.id], queryFn: () => api<AgentStatus>(`/organizations/${organization.id}/agent/status`), refetchInterval: tab === 'trial' ? 5000 : 30000 })
  const persist = async () => {
    if (!dirty) return baseline
    const data = await api<Assistant>(path, 'PUT', { name, graph, revision: baseline.revision })
    setBaseline(data); setGraph(data.draft); onSaved(data)
    return data
  }
  const save = useMutation({ mutationFn: persist, onSuccess: () => setMessage(t('Draft saved.')) })
  const validate = useMutation({ mutationFn: () => api<{ valid: boolean; errors: string[]; model_calls: number }>(`/organizations/${organization.id}/assistants/validate`, 'POST', graph) })
  const publish = useMutation({ mutationFn: async () => { const saved = await persist(); return api<AssistantVersion>(`${path}/publish`, 'POST', { revision: saved.revision }) }, onSuccess: data => { setVersions(v => [data, ...v.filter(x => x.id !== data.id)]); setMessage(t('Version published. Existing experiments keep their original version.')); setTab('versions'); void client.invalidateQueries({ queryKey: ['assistants', userId, organization.id] }) } })
  const trial = useMutation({ mutationFn: async () => { const saved = await persist(); return api<AssistantRun>(`${path}/trial`, 'POST', { revision: saved.revision, market_id: market, idempotency_key: crypto.randomUUID() }) }, onSuccess: data => setRunId(data.id) })
  const busy = save.isPending || publish.isPending || trial.isPending
  const changeGraph = (value: AssistantGraph, group = '') => {
    if (JSON.stringify(value) === JSON.stringify(graph)) return
    const now = Date.now()
    if (!group || groupRef.current.key !== group || now - groupRef.current.at > 750) setPast(p => [...p.slice(-39), graph])
    groupRef.current = { key: group, at: now }
    setFuture([]); setGraph(value); validate.reset(); setMessage('')
  }
  const patchNode = (id: string, patch: Partial<AssistantNode>) => changeGraph({ ...graph, nodes: graph.nodes.map(n => n.id === id ? { ...n, ...patch } : n) }, `edit-${id}-${Object.keys(patch).join('-')}`)
  const undo = () => { const value = past.at(-1); if (!value) return; setFuture(f => [graph, ...f]); setPast(p => p.slice(0, -1)); setGraph(value); validate.reset(); setMessage(''); groupRef.current.key = '' }
  const redo = () => { const value = future[0]; if (!value) return; setPast(p => [...p, graph]); setFuture(f => f.slice(1)); setGraph(value); validate.reset(); setMessage(''); groupRef.current.key = '' }
  const canTrial = writable && !!market && status.data?.can_run && status.data.daily_run_limit - status.data.runs_today >= graph.nodes.length && !customizationError && !!name.trim()
  const removeNode = (id: string) => {
    if (!editable || busy || graph.nodes.some(n => n.id === id && ['risk', 'review'].includes(n.kind))) return
    changeGraph({ ...graph, nodes: graph.nodes.filter(n => n.id !== id), edges: graph.edges.filter(e => e.source !== id && e.target !== id) })
    setSelected(graph.nodes.find(n => n.id !== id)?.id ?? null)
  }
  return <section className="assistant-editor" ref={editor}>
    <div className="assistant-editor-toolbar"><div className="assistant-editor-identity"><input aria-label={t('Assistant name')} value={name} maxLength={120} disabled={!editable || busy} onChange={e => { setName(e.target.value); setMessage('') }} /><span className={`assistant-save-state ${dirty ? 'dirty' : ''}`}><i />{dirty ? t('Unsaved changes') : t('Saved draft')}</span></div><div className="assistant-editor-buttons"><button disabled={!editable || !dirty || busy || !!customizationError || !name.trim()} onClick={() => save.mutate()}>{save.isPending ? t('Saving…') : t('Save draft')}</button><button className="primary" disabled={!editable || busy || !!customizationError || !name.trim()} onClick={() => publish.mutate()}>{publish.isPending ? t('Publishing…') : t('Publish version')} ↗</button></div></div>
    <div className="assistant-editor-navigation"><nav aria-label={t('Assistant editor sections')}>{[['configuration', 'Configuration'], ['workflow', 'Workflow'], ['trial', 'Trial run'], ['versions', 'Versions']].map(([id, label]) => <button key={id} aria-pressed={tab === id} onClick={() => setTab(id)}>{t(label)}{id === 'versions' && <span>{versions.length}</span>}</button>)}</nav><div className="assistant-history-actions"><button aria-pressed={inspectorOpen} disabled={tab !== 'workflow'} onClick={() => setInspectorOpen(!inspectorOpen)}>{t(inspectorOpen ? 'Hide configuration' : 'Show configuration')}</button><button onClick={() => void toggleFullscreen()}>{fullscreen ? '↙' : '↗'} {t(fullscreen ? 'Exit fullscreen' : 'Expand workspace')}</button><button aria-label={t('Undo')} title={t('Undo')} disabled={!editable || busy || !past.length} onClick={undo}>↶</button><button aria-label={t('Redo')} title={t('Redo')} disabled={!editable || busy || !future.length} onClick={redo}>↷</button><button disabled={busy || validate.isPending} onClick={() => validate.mutate()}>{t('Check workflow')}</button></div></div>
    {assistant.is_default && <div className="assistant-inline-notice">{t('Copy the default assistant before editing it.')} <button disabled={!writable} onClick={onCopy}>{t('Copy assistant')}</button></div>}
    {[save.error, validate.error, publish.error, trial.error, tab === 'trial' && candidates.error, status.error].filter(Boolean).map((error, i) => <p className="assistant-feedback error" role="alert" key={i}>{t((error as Error).message)}</p>)}
    {validate.data && <p role="status" className={`assistant-feedback ${validate.data.valid ? 'paper-gain' : 'error'}`}>{validate.data.valid ? t('Workflow is valid.') : validate.data.errors.map(message => t(message)).join(' ')}</p>}
    {message && <p role="status" className="assistant-feedback paper-gain">{message}</p>}
    {tab === 'configuration' && <AssistantConfiguration graph={graph} status={status.data} userId={userId} organizationId={organization.id} disabled={!editable || busy} onGraph={changeGraph} onEdit={editNode} />}
    {customizationError && tab !== 'trial' && <p role="alert" className="assistant-feedback error">{t(customizationError)}</p>}
    {tab === 'workflow' && <><div className={`assistant-workbench ${inspectorOpen ? '' : 'inspector-hidden'}`}>
      <AssistantCanvas graph={graph} onChange={changeGraph} selected={selected} onSelect={setSelected} onEdit={editNode} onRemove={removeNode} onUndo={!busy && past.length ? undo : undefined} onRedo={!busy && future.length ? redo : undefined} view={canvasView} readonly={!editable || busy} />
      {inspectorOpen && <div className="assistant-inspector-slot" ref={inspector}>{node ? <AssistantNodeInspector key={`${node.id}-${editRequest.revision}`} initialTab={editRequest.tab} status={status.data} node={node} graph={graph} readonly={!editable || busy} onPatch={patch => patchNode(node.id, patch)} onGraph={changeGraph} onRemove={() => removeNode(node.id)} /> : <aside className="assistant-inspector assistant-inspector-empty"><AssistantIcon kind="team" /><p>{t('Select a node to configure it.')}</p></aside>}</div>}
    </div>
      <details className="assistant-workflow-settings"><summary>{t('Entry signal settings')}<span>{Math.round(graph.entry_change_15m * 10000) / 100} pp · 15 min</span></summary><label>{t('Minimum 15m movement (pp)')}<input type="number" min="2" max="20" step="0.5" value={Math.round(graph.entry_change_15m * 10000) / 100} disabled={!editable || busy} onChange={e => { const value = Number(e.target.value); if (Number.isFinite(value)) changeGraph({ ...graph, entry_change_15m: value / 100 }, 'threshold') }} /></label><p>{t('Additional signal filter. The baseline threshold is 2 pp.')}</p></details></>}
    {tab === 'trial' && <div className="assistant-trial-page"><div className="assistant-section-intro"><span className="assistant-node-icon"><AssistantIcon kind="review" /></span><div><h3>{t('Test your team on a market')}</h3><p>{t('Inspect each agent’s evidence and conclusions before adding the team to an experiment.')}</p></div></div><div className="assistant-trial"><label>{t('Trial market')}<select value={market} onChange={e => setMarket(e.target.value)}><option value="">{t('Choose a market')}</option>{candidates.data?.map(m => <option key={m.id} value={m.id}>{m.title}</option>)}</select></label><div className="assistant-trial-budget"><span>{t('This trial')}<strong>{graph.nodes.length} {t('model calls')}</strong></span><span>{t('Workspace calls remaining')}<strong>{status.data ? Math.max(0, status.data.daily_run_limit - status.data.runs_today) : '—'}</strong></span></div><button className="primary" disabled={!canTrial || busy} onClick={() => trial.mutate()}>{trial.isPending ? t('Starting…') : dirty ? t('Save and run trial') : t('Run saved draft')} →</button><p className="assistant-help">{t('A trial uses your workspace model and creates no simulated orders.')}</p>{status.data && !status.data.can_run && <a href="#/model-settings">{t('Configure and enable a model')}</a>}{status.data?.can_run && status.data.daily_run_limit - status.data.runs_today < graph.nodes.length && <p className="error">{t('Not enough model calls remaining for this workflow.')}</p>}{candidates.data?.length === 0 && <p>{t('No eligible priority markets. Enable collection and wait for fresh two-sided quotes.')}</p>}{customizationError && <p role="alert" className="error">{t(customizationError)}</p>}</div>{runId && <AssistantRunDetail userId={userId} organizationId={organization.id} runId={runId} writable={writable} />}</div>}
    {tab === 'versions' && <div className="assistant-releases"><div className="assistant-section-intro"><span className="assistant-node-icon"><AssistantIcon kind="team" /></span><div><h3>{t('Published versions')}</h3><p>{t('Each version freezes the workflow, prompts and skill files for a reproducible experiment.')}</p></div></div>{versions.length === 0 && <p className="assistant-versions-empty">{t('Publish a version to attach this assistant to an experiment.')}</p>}{versions.map(v => <div className="assistant-release-row" key={v.id}><span className="assistant-version-number">v{v.number}</span><div><strong>{t(v.name)}</strong><small>{new Date(v.created_at).toLocaleString(locale())} · {v.graph.nodes.length} {t('nodes')} · {v.graph.nodes.reduce((count, n) => count + (n.skills?.length ?? 0), 0)} Skills</small></div><button onClick={() => onCompare(v.id)}>{t('Add to comparison')} →</button></div>)}</div>}
  </section>
}
