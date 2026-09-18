import { useEffect, useRef, useState } from 'react'
import { t } from './i18n'
import { nodeDescriptions, nodeNames, type AssistantGraph, type AssistantNode, type NodeSkillFile } from './assistantTypes'
import { canConnect, skillError } from './assistantGraph'
import AssistantIcon from './AssistantIcon'
import TerminalDialog from './TerminalDialog'

function readMarkdown(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(new Error('Unable to read this file.'))
    reader.onload = () => {
      try { resolve(new TextDecoder('utf-8', { fatal: true }).decode(reader.result as ArrayBuffer)) }
      catch { reject(new Error('Upload a UTF-8 Markdown file.')) }
    }
    reader.readAsArrayBuffer(file)
  })
}
function download(file: NodeSkillFile) {
  const url = URL.createObjectURL(new Blob([file.content], { type: 'text/markdown;charset=utf-8' }))
  const a = document.createElement('a'); a.href = url; a.download = file.name; a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export default function AssistantNodeInspector({ node, graph, readonly, onPatch, onGraph, onRemove, initialTab = 'prompt' }: {
  node: AssistantNode; graph: AssistantGraph; readonly: boolean
  onPatch: (patch: Partial<AssistantNode>) => void; onGraph: (graph: AssistantGraph) => void; onRemove: () => void
  initialTab?: 'prompt' | 'skills'
}) {
  const [tab, setTab] = useState(initialTab as string), [fileIndex, setFileIndex] = useState(0)
  const [expanded, setExpanded] = useState(false), [uploading, setUploading] = useState(false), [error, setError] = useState('')
  const fileInput = useRef<HTMLInputElement>(null), alive = useRef(true)
  const latest = useRef({ node, onPatch, readonly })
  useEffect(() => { latest.current = { node, onPatch, readonly } }, [node, onPatch, readonly])
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  const files = node.skills ?? [], file = files[fileIndex], prompt = node.prompt ?? node.instructions
  const disabled = readonly || uploading
  const patchFiles = (next: NodeSkillFile[]) => { setError(''); onPatch({ skills: next }) }
  const patchFile = (patch: Partial<NodeSkillFile>) => patchFiles(files.map((s, i) => i === fileIndex ? { ...s, ...patch } : s))
  const problem = skillError(files, node.prompt ?? '', node.instructions)
  const upload = async (incoming: FileList | null) => {
    if (!incoming?.length || disabled) return
    setError(''); setUploading(true)
    try {
      if (files.length + incoming.length > 5) throw new Error('Each node supports up to 5 skill files.')
      const additions: NodeSkillFile[] = []
      for (const item of Array.from(incoming)) {
        if (!/\.md$/i.test(item.name)) throw new Error('Upload Markdown files with the .md extension.')
        if (item.size > 16000) throw new Error('Each skill file is limited to 12,000 characters and 16 KB.')
        additions.push({ name: item.name, content: await readMarkdown(item), enabled: true })
      }
      if (!alive.current) return
      const current = latest.current
      if (current.readonly) throw new Error('Upload interrupted. Please try again.')
      const next = [...current.node.skills ?? [], ...additions], issue = skillError(next, current.node.prompt ?? '', current.node.instructions)
      if (issue) throw new Error(issue)
      current.onPatch({ skills: next }); setFileIndex(current.node.skills?.length ?? 0)
    } catch (err) { if (alive.current) setError(err instanceof Error ? err.message : 'Unable to read this file.') }
    finally { if (alive.current) setUploading(false); if (fileInput.current) fileInput.current.value = '' }
  }
  const promptEditor = (large = false) => <label className={`assistant-code-field ${large ? 'expanded' : ''}`}><span>{t('Node prompt')}<small>{prompt.length.toLocaleString()} / 8,000</small></span><textarea aria-label={t('Node prompt')} spellCheck={false} value={prompt} maxLength={8000} disabled={disabled} placeholder={t('Define this agent’s objective, research method and decision criteria…')} onChange={e => onPatch({ prompt: e.target.value, instructions: '' })} /></label>
  const skillEditor = (large = false) => file && <label className={`assistant-code-field ${large ? 'expanded' : ''}`}><span>{t('Markdown content')}<small>{file.content.length.toLocaleString()} / 12,000</small></span><textarea aria-label={t('Skill file content')} spellCheck={false} value={file.content} maxLength={12000} disabled={disabled} placeholder={'---\nname: market-research\ndescription: Your research method\n---\n\n# Instructions\n'} onChange={e => patchFile({ content: e.target.value })} /></label>
  return <aside className={`assistant-inspector kind-${node.kind}`}>
    <div className="assistant-inspector-heading"><span className="assistant-node-icon"><AssistantIcon kind={node.kind} /></span><div><small>{t('Node configuration')}</small><strong>{t(nodeNames[node.kind])}</strong></div><span className="badge">{t(['risk', 'review'].includes(node.kind) ? 'Required' : 'Agent')}</span></div>
    <label className="assistant-node-name">{t('Node name')}<input value={t(node.label)} maxLength={80} disabled={disabled} onChange={e => onPatch({ label: e.target.value })} /></label>
    <div className="assistant-inspector-tabs" role="tablist" aria-label={t('Node configuration')}>
      {[['prompt', 'Prompt'], ['skills', 'Skills'], ['inputs', 'Inputs']].map(([id, title]) => <button key={id} role="tab" id={`node-tab-${id}`} aria-controls={`node-panel-${id}`} aria-selected={tab === id} onClick={() => setTab(id)}>{t(title)}{id === 'skills' && <span>{files.length}</span>}</button>)}
    </div>
    <div className="assistant-inspector-content" role="tabpanel" id={`node-panel-${tab}`} aria-labelledby={`node-tab-${tab}`}>
      {tab === 'prompt' && <><p className="assistant-role-note">{t(nodeDescriptions[node.kind])}</p><div className="assistant-field-toolbar"><span>{t('Instructions for this agent')}</span><button onClick={() => setExpanded(true)}>{t('Expand editor')} ↗</button></div>{!expanded && promptEditor()}{!prompt && <button className="assistant-text-button" disabled={disabled} onClick={() => onPatch({ instructions: '', prompt: `${t(nodeDescriptions[node.kind])}\n\n${t('Separate observations from hypotheses. Cite the supplied evidence, challenge assumptions and state what would change your conclusion.')}` })}>{t('Insert starter prompt')}</button>}<p className="assistant-help">{t('Your prompt supplements the role. Structured output and evidence rules are applied automatically.')}</p>{node.prompt && node.instructions && <p className="assistant-help">{t('Legacy research focus')}: {node.instructions}</p>}</>}
      {tab === 'skills' && <><p className="assistant-help">{t('Attach reusable research methods. Enabled files are included in this node’s model input.')}</p><div className="assistant-skill-actions"><button disabled={disabled || files.length >= 5} onClick={() => { let name = 'SKILL.md'; for (let n = 2; files.some(s => s.name.toLowerCase() === name.toLowerCase()); n++) name = `skill-${n}.md`; patchFiles([...files, { name, content: '', enabled: true }]); setFileIndex(files.length) }}>＋ {t('New skill')}</button><button disabled={disabled || files.length >= 5} onClick={() => fileInput.current?.click()}><AssistantIcon kind="upload" />{t(uploading ? 'Importing…' : 'Upload .md')}</button><input ref={fileInput} type="file" accept=".md,text/markdown" multiple hidden aria-label={t('Upload skill files')} disabled={disabled} onChange={e => void upload(e.target.files)} /></div>
        {error && <p role="alert" className="error">{t(error)}</p>}
        {files.length === 0 ? <div className="assistant-skill-empty"><AssistantIcon kind="file" /><strong>{t('Give this agent a playbook')}</strong><p>{t('Write a SKILL.md file or upload your own Markdown instructions.')}</p><small>{t('Up to 5 files · 16 KB per file · UTF-8 Markdown')}</small></div> : <><div className="assistant-file-tabs" aria-label={t('Skill files')}>{files.map((f, i) => <button key={i} aria-pressed={fileIndex === i} onClick={() => setFileIndex(i)}><AssistantIcon kind="file" />{f.name || t('Untitled file')}{!f.enabled && <small>{t('Off')}</small>}</button>)}</div>{file && <><div className="assistant-file-meta"><label>{t('Filename')}<input value={file.name} maxLength={100} disabled={disabled} onChange={e => patchFile({ name: e.target.value })} /></label><label className="assistant-switch"><input type="checkbox" checked={file.enabled} disabled={disabled} onChange={e => patchFile({ enabled: e.target.checked })} />{t('Enabled')}</label></div><div className="assistant-field-toolbar"><span>{t('Markdown instructions')}</span><button onClick={() => setExpanded(true)}>{t('Expand editor')} ↗</button></div>{!expanded && skillEditor()}<div className="assistant-file-footer"><button onClick={() => download(file)} disabled={!!problem}>{t('Download')}</button><button className="assistant-danger" disabled={disabled} onClick={() => { patchFiles(files.filter((_, i) => i !== fileIndex)); setFileIndex(Math.max(0, fileIndex - 1)) }}>{t('Remove file')}</button></div></>}</>}
        <p className="assistant-help">{t('Skills provide instructions; scripts and linked files are not executed or fetched.')}</p></>}
      {tab === 'inputs' && <><h4>{t('Upstream findings')}</h4><p className="assistant-help">{t('Choose which agents share their conclusions with this node.')}</p><div className="assistant-inputs">{graph.nodes.filter(n => n.id !== node.id).map(n => {
        const checked = graph.edges.some(e => e.source === n.id && e.target === node.id)
        return <label key={n.id}><input type="checkbox" checked={checked} disabled={disabled || (!checked && !canConnect(graph, n.id, node.id))} onChange={() => onGraph({ ...graph, edges: checked ? graph.edges.filter(e => e.source !== n.id || e.target !== node.id) : [...graph.edges, { source: n.id, target: node.id }] })} /><AssistantIcon kind={n.kind} /><span>{t(n.label)}</span></label>
      })}</div><p className="assistant-role-note">{t('All agents receive the market evidence. Connections add upstream findings; analysis must pass through risk review.')}</p></>}
      {problem && <p role="alert" className="error">{t(problem)}</p>}
    </div>
    <footer className="assistant-inspector-footer"><small>{t('Changes are saved with the assistant draft.')}</small><button className="assistant-danger" disabled={disabled || ['risk', 'review'].includes(node.kind)} onClick={onRemove}>{t('Remove node')}</button></footer>
    <TerminalDialog open={expanded} onClose={() => setExpanded(false)} title={`${t(node.label)} · ${tab === 'skills' ? file?.name ?? 'Skills' : 'Prompt'}`} className="assistant-code-dialog">{tab === 'skills' ? skillEditor(true) : promptEditor(true)}<div className="assistant-dialog-footer"><span>{t('Edits are applied to the draft immediately.')}</span><button onClick={() => setExpanded(false)}>{t('Done')}</button></div></TerminalDialog>
  </aside>
}
