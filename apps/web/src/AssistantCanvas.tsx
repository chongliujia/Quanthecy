import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { Background, BaseEdge, EdgeLabelRenderer, Handle, MarkerType, MiniMap, Position, ReactFlow, getBezierPath, useUpdateNodeInternals, type Edge, type EdgeProps, type Node, type NodeProps, type ReactFlowInstance, type Viewport } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { t } from './i18n'
import { nodeDescriptions, nodeNames, type AssistantGraph, type AssistantNode, type NodeKind } from './assistantTypes'
import { arrangeGraph, canConnect, connectionError, freeNodePosition, graphDirection, graphIssues, type FlowDirection } from './assistantGraph'
import AssistantIcon from './AssistantIcon'
import TerminalDialog from './TerminalDialog'

export type CanvasView = { viewport: Viewport; width: number; height: number }
type FlowNode = Node<{
  node: AssistantNode; select: () => void; edit: (tab: 'prompt' | 'skills') => void
  move: (dx: number, dy: number) => void; readonly: boolean; direction: FlowDirection
  connect: (type: 'source' | 'target') => void; connecting: boolean; targetValid: boolean; isSource: boolean; issue?: string
}, 'assistant'>
type FlowEdge = Edge<{ remove: () => void; readonly: boolean }, 'assistant'>
const WIDTH = 240, HEIGHT = 150
// Leave room for the floating navigation controls when fitting the graph.
const FIT_OPTIONS = { padding: { top: '36px', right: '32px', bottom: '88px', left: '32px' }, maxZoom: 1.15 } as const
const clamp = (value: number) => Math.max(0, Math.min(2000, value))
function AgentNode({ id, data, selected }: NodeProps<FlowNode>) {
  const n = data.node, skills = n.skills?.filter(s => s.enabled).length ?? 0
  const updateInternals = useUpdateNodeInternals()
  useEffect(() => { updateInternals(id) }, [id, data.direction, updateInternals])
  const keyConnect = (event: KeyboardEvent, type: 'source' | 'target') => {
    if (['Enter', ' '].includes(event.key)) { event.preventDefault(); event.stopPropagation(); data.connect(type) }
  }
  return <article className={`assistant-node kind-${n.kind} ${selected ? 'selected' : ''} ${data.issue ? 'has-issue' : ''} ${data.isSource ? 'connection-source' : ''} ${data.connecting && data.targetValid ? 'connection-target' : ''}`}>
    <Handle type="target" position={data.direction === 'horizontal' ? Position.Left : Position.Top} isConnectable={!data.readonly} isConnectableStart={false}
      role="button" tabIndex={data.readonly ? -1 : 0} aria-disabled={data.readonly} aria-label={`${t('Connect to')} ${t(n.label)}`} title={t('Input: receives upstream findings')}
      onClick={e => { e.stopPropagation(); data.connect('target') }} onKeyDown={e => keyConnect(e, 'target')} />
    <button className="assistant-node-handle" aria-label={`${t('Select node')} ${t(n.label)}`} onClick={data.select} onKeyDown={e => {
      const directions: Record<string, [number, number]> = { ArrowRight: [20, 0], ArrowLeft: [-20, 0], ArrowDown: [0, 20], ArrowUp: [0, -20] }
      if (!data.readonly && directions[e.key]) { e.preventDefault(); e.stopPropagation(); data.move(...directions[e.key]) }
    }}><span className="assistant-node-heading"><span className="assistant-node-icon"><AssistantIcon kind={n.kind} /></span><span><small>{t(nodeNames[n.kind])}</small><strong>{t(n.label)}</strong></span>{data.issue && <span className="assistant-node-warning" title={t(data.issue)} aria-label={t(data.issue)}>!</span>}</span><span className="assistant-node-description">{t(nodeDescriptions[n.kind])}</span></button>
    <div className="assistant-node-tags nodrag"><button className={n.prompt || n.instructions ? 'configured' : ''} aria-label={`${t('Edit prompt')} · ${t(n.label)}`} onClick={e => { e.stopPropagation(); data.edit('prompt') }}>{n.prompt || n.instructions ? t('Custom prompt') : t('Role prompt')} ↗</button><button aria-label={`${t('Edit skills')} · ${t(n.label)}`} onClick={e => { e.stopPropagation(); data.edit('skills') }}><AssistantIcon kind="file" />{skills} Skills</button>{['risk', 'review'].includes(n.kind) && <span className="assistant-required">{t('Required')}</span>}</div>
    {n.kind !== 'review' && <Handle type="source" position={data.direction === 'horizontal' ? Position.Right : Position.Bottom} isConnectable={!data.readonly}
      role="button" tabIndex={data.readonly ? -1 : 0} aria-disabled={data.readonly} aria-label={`${t('Connect from')} ${t(n.label)}`} title={t('Output: drag or click to connect')}
      onClick={e => { e.stopPropagation(); data.connect('source') }} onKeyDown={e => keyConnect(e, 'source')} />}
  </article>
}
function AssistantEdge(props: EdgeProps<FlowEdge>) {
  const [path, x, y] = getBezierPath(props)
  return <><BaseEdge id={props.id} path={path} markerEnd={props.markerEnd} style={props.style} interactionWidth={24} />{props.selected && !props.data?.readonly && <EdgeLabelRenderer><button className="assistant-edge-delete nodrag nopan" style={{ transform: `translate(-50%, -50%) translate(${x}px, ${y}px)` }} aria-label={t('Remove connection')} title={t('Remove connection')} onClick={e => { e.stopPropagation(); props.data?.remove() }}>×</button></EdgeLabelRenderer>}</>
}
const nodeTypes = { assistant: AgentNode }, edgeTypes = { assistant: AssistantEdge }

export default function AssistantCanvas({ graph, onChange, selected, onSelect, onEdit, onRemove, onUndo, onRedo, view, readonly = false }: {
  graph: AssistantGraph; onChange: (graph: AssistantGraph, group?: string) => void; selected: string | null
  onSelect: (id: string | null) => void; readonly?: boolean; onEdit?: (id: string, tab: 'prompt' | 'skills') => void
  onRemove?: (id: string) => void; onUndo?: () => void; onRedo?: () => void; view?: { current: CanvasView | null }
}) {
  const [flow, setFlow] = useState<ReactFlowInstance<FlowNode, FlowEdge> | null>(null)
  const surface = useRef<HTMLDivElement>(null), container = useRef<HTMLDivElement>(null), dragGroup = useRef(0)
  const localView = useRef<CanvasView | null>(null), cache = view ?? localView
  const [library, setLibrary] = useState(false), [help, setHelp] = useState(false), [showMap, setShowMap] = useState(false)
  const [showIssues, setShowIssues] = useState(false), [source, setSource] = useState<string | null>(null)
  const [edgeId, setEdgeId] = useState<string | null>(null), [feedback, setFeedback] = useState('')
  const [zoom, setZoom] = useState(cache.current?.viewport.zoom ?? 1)
  const direction = graphDirection(graph), issues = graphIssues(graph)
  const fit = () => void flow?.fitView({ ...FIT_OPTIONS, duration: 180 })
  const remember = (viewport: Viewport) => {
    const rect = surface.current?.getBoundingClientRect()
    if (rect?.width && rect.height) cache.current = { viewport, width: rect.width, height: rect.height }
  }
  useEffect(() => {
    if (!flow || !surface.current) return
    let width = cache.current?.width ?? 0, height = cache.current?.height ?? 0, frame = 0
    const observer = new ResizeObserver(entries => {
      const size = entries[0]?.contentRect
      if (!size?.width || !size.height) return
      if (width && height && (width !== size.width || height !== size.height)) {
        const viewport = flow.getViewport(), dx = (size.width - width) / 2, dy = (size.height - height) / 2
        cancelAnimationFrame(frame)
        frame = requestAnimationFrame(() => void flow.setViewport({ ...viewport, x: viewport.x + dx, y: viewport.y + dy }))
      }
      width = size.width; height = size.height
    })
    observer.observe(surface.current)
    return () => { observer.disconnect(); cancelAnimationFrame(frame) }
  }, [flow, cache])
  const focusNode = (id: string) => {
    const node = graph.nodes.find(n => n.id === id)
    if (!node) return
    onSelect(id); setEdgeId(null)
    void flow?.setCenter(node.x + WIDTH / 2, node.y + HEIGHT / 2, { zoom: Math.max(.85, flow.getZoom()), duration: 180 })
  }
  const edit = (id: string, tab: 'prompt' | 'skills') => { onSelect(id); onEdit?.(id, tab) }
  const changeNode = (id: string, x: number, y: number) => onChange({ ...graph, nodes: graph.nodes.map(n => n.id === id ? { ...n, x: clamp(x), y: clamp(y) } : n) }, `move-${id}`)
  const add = (kind: NodeKind, position?: { x: number; y: number }) => {
    if (readonly || graph.nodes.length >= 8 || (['risk', 'review'].includes(kind) && graph.nodes.some(n => n.kind === kind))) return
    const id = `${kind}_${crypto.randomUUID().slice(0, 8)}`, rect = surface.current?.getBoundingClientRect()
    const center = flow && rect ? flow.screenToFlowPosition({ x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 }) : { x: 160, y: 160 }
    const point = freeNodePosition(graph, position ?? { x: center.x - WIDTH / 2, y: center.y - HEIGHT / 2 })
    onChange({ ...graph, nodes: [...graph.nodes, { id, kind, label: nodeNames[kind], instructions: '', ...point }] })
    edit(id, 'prompt'); setLibrary(false); setFeedback('Node added. Connect it to the research workflow.')
    void flow?.setCenter(point.x + WIDTH / 2, point.y + HEIGHT / 2, { zoom: Math.max(.85, flow.getZoom()), duration: 180 })
  }
  const connect = (from: string, to: string) => {
    if (readonly) return
    const error = connectionError(graph, from, to)
    if (error) { setFeedback(error); return }
    onChange({ ...graph, edges: [...graph.edges, { source: from, target: to }] })
    setSource(null); setFeedback('Connection added.'); setEdgeId(`${from}:${to}`)
  }
  const removeEdge = (id: string) => { if (readonly) return; onChange({ ...graph, edges: graph.edges.filter(e => `${e.source}:${e.target}` !== id) }); setEdgeId(null); setFeedback('Connection removed. Undo to restore it.') }
  const keyboard = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.target instanceof HTMLElement && (event.target.closest('input, textarea, select, [contenteditable="true"], dialog'))) return
    const key = event.key.toLowerCase(), command = event.metaKey || event.ctrlKey
    if (command && ['z', 'y'].includes(key) && !readonly) { event.preventDefault(); if (key === 'y' || event.shiftKey) onRedo?.(); else onUndo?.(); return }
    if (command || event.altKey) return
    if (key === 'escape') { setSource(null); setLibrary(false); setShowIssues(false); setEdgeId(null); setFeedback(''); return }
    if (key === 'f') { event.preventDefault(); fit() }
    if (key === '?') { event.preventDefault(); setHelp(true) }
    if (['delete', 'backspace'].includes(key) && !readonly) {
      event.preventDefault()
      if (edgeId) removeEdge(edgeId)
      else if (selected) {
        const node = graph.nodes.find(n => n.id === selected)
        if (node && ['risk', 'review'].includes(node.kind)) setFeedback('Required review nodes cannot be removed.')
        else if (onRemove) { onRemove(selected); setFeedback('Node removed. Undo to restore it.') }
      }
    }
  }
  const nodes: FlowNode[] = graph.nodes.map(n => ({ id: n.id, type: 'assistant', position: { x: n.x, y: n.y }, width: WIDTH, height: HEIGHT, selected: selected === n.id, dragHandle: '.assistant-node-handle', data: {
    node: n, readonly, direction, connecting: !!source, isSource: source === n.id, targetValid: !!source && canConnect(graph, source, n.id), issue: issues.find(i => i.nodeId === n.id)?.message,
    select: () => { onSelect(n.id); setEdgeId(null) }, edit: tab => edit(n.id, tab), move: (dx, dy) => changeNode(n.id, n.x + dx, n.y + dy),
    connect: type => { if (readonly) return; if (type === 'source') { setSource(source === n.id ? null : n.id); setFeedback('') } else if (source) connect(source, n.id); else setFeedback('Choose an output port first.') },
  } }))
  const edges: FlowEdge[] = graph.edges.map(e => {
    const id = `${e.source}:${e.target}`, related = selected === e.source || selected === e.target
    return { ...e, id, type: 'assistant', selected: edgeId === id, markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16, color: related || edgeId === id ? 'var(--theme-accent)' : 'var(--theme-muted)' }, style: { strokeWidth: related || edgeId === id ? 2.2 : 1.5, ...(related || edgeId === id ? { stroke: 'var(--theme-accent)' } : {}) }, data: { remove: () => removeEdge(id), readonly } }
  })
  const layout = (value: FlowDirection) => { onChange(arrangeGraph(graph, value)); setFeedback('Layout updated. Connections are unchanged.'); requestAnimationFrame(() => requestAnimationFrame(fit)) }
  return <div className="assistant-flow" ref={container} tabIndex={0} aria-label={t('Workflow canvas')} onKeyDown={keyboard}>
    <div className="assistant-canvas-toolbar"><span><AssistantIcon kind="team" /><strong>{t('Workflow')}</strong><small>{graph.nodes.length} / 8</small><button className={`assistant-graph-status ${issues.length ? 'has-issues' : ''}`} aria-expanded={showIssues} onClick={() => setShowIssues(!showIssues)}>{issues.length ? t('{count} connection issues', { count: issues.length }) : t('Connections ready')}</button></span><div><button disabled={readonly || graph.nodes.length >= 8} aria-expanded={library} onClick={() => { setLibrary(!library); setShowIssues(false) }}>＋ {t('Add node')}</button><div className="assistant-layout-controls"><button disabled={readonly} onClick={() => layout(direction)}>{t('Auto arrange')}</button><select aria-label={t('Layout direction')} disabled={readonly} value={direction} onChange={e => layout(e.target.value as FlowDirection)}><option value="vertical">{t('Top to bottom')}</option><option value="horizontal">{t('Left to right')}</option></select></div></div></div>
    {showIssues && <div className="assistant-issues-popover"><strong>{t('Connection checks')}</strong>{issues.length ? issues.map((issue, i) => <button key={`${issue.nodeId}-${i}`} onClick={() => { focusNode(issue.nodeId); setShowIssues(false) }}><span>!</span><div><strong>{t(graph.nodes.find(n => n.id === issue.nodeId)?.label ?? '')}</strong><small>{t(issue.message)}</small></div>→</button>) : <p>{t('Every analyst reaches risk review, followed by entry review.')}</p>}</div>}
    {library && <aside className="assistant-palette" aria-label={t('Node library')}><div><strong>{t('Add a specialist')}</strong><button aria-label={t('Close node library')} onClick={() => setLibrary(false)}>×</button></div><p>{t('Click to add in view, or drag to choose a position.')}</p>{(Object.keys(nodeNames) as NodeKind[]).map(kind => <button key={kind} className={`kind-${kind}`} draggable={!readonly} disabled={readonly || (['risk', 'review'].includes(kind) && graph.nodes.some(n => n.kind === kind))} onDragStart={e => { e.dataTransfer.setData('application/quanthecy-node', kind); e.dataTransfer.effectAllowed = 'move' }} onClick={() => add(kind)}><span className="assistant-node-icon"><AssistantIcon kind={kind} /></span><span><strong>{t(nodeNames[kind])}</strong><small>{t(nodeDescriptions[kind])}</small></span><span>＋</span></button>)}</aside>}
    <div ref={surface} className="assistant-flow-surface" onDragOver={e => { if (!readonly) { e.preventDefault(); e.dataTransfer.dropEffect = 'move' } }} onDrop={e => {
      e.preventDefault(); const kind = e.dataTransfer.getData('application/quanthecy-node') as NodeKind
      if (flow && Object.hasOwn(nodeNames, kind)) { const point = flow.screenToFlowPosition({ x: e.clientX, y: e.clientY }); add(kind, { x: point.x - WIDTH / 2, y: point.y - 30 }) }
    }}>
      <ReactFlow<FlowNode, FlowEdge> nodes={nodes} edges={edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes} onInit={setFlow} fitView={!cache.current} defaultViewport={cache.current?.viewport} fitViewOptions={FIT_OPTIONS} minZoom={.15} maxZoom={1.75} snapToGrid snapGrid={[10, 10]} nodeExtent={[[0, 0], [2000 + WIDTH, 2000 + HEIGHT]]}
        nodesDraggable={!readonly} nodesConnectable={!readonly} connectOnClick={false} connectionRadius={28} deleteKeyCode={null} nodesFocusable={false} edgesFocusable={!readonly} zoomOnDoubleClick={false} panActivationKeyCode="Space"
        onMove={(_, v) => setZoom(v.zoom)} onMoveEnd={(_, v) => remember(v)} onNodeDragStart={() => { dragGroup.current += 1 }}
        onNodesChange={changes => { if (readonly) return; const moved = changes.filter(c => c.type === 'position' && c.position); if (!moved.length) return; onChange({ ...graph, nodes: graph.nodes.map(n => { const c = moved.find(c => c.type === 'position' && c.id === n.id); return c?.type === 'position' && c.position ? { ...n, x: clamp(c.position.x), y: clamp(c.position.y) } : n }) }, `drag-${dragGroup.current}`) }}
        onNodeClick={(_, n) => { onSelect(n.id); setEdgeId(null) }} onNodeDoubleClick={(_, n) => edit(n.id, 'prompt')}
        onPaneClick={() => { onSelect(null); setEdgeId(null); setSource(null); setLibrary(false); setShowIssues(false); container.current?.focus({ preventScroll: true }) }} onEdgeClick={(_, e) => { setEdgeId(e.id); container.current?.focus({ preventScroll: true }) }}
        isValidConnection={e => canConnect(graph, e.source, e.target)} onConnect={e => connect(e.source, e.target)} onConnectStart={(_, params) => { if (params.handleType === 'source') { setSource(params.nodeId); setFeedback('') } }}
        onConnectEnd={(_, connection) => { setSource(null); if (!connection.isValid && connection.fromNode && connection.toNode) setFeedback(connectionError(graph, connection.fromNode.id, connection.toNode.id) ?? '') }}>
        <Background gap={22} size={1} />
        {showMap && <MiniMap ariaLabel={t('Workflow overview')} position="bottom-right" pannable zoomable nodeColor="var(--theme-accent)" maskColor="color-mix(in srgb, var(--theme-page) 75%, transparent)" bgColor="var(--theme-surface)" nodeBorderRadius={5} />}
      </ReactFlow>
      {source && <div className="assistant-connection-guide" role="status"><span>{t('Connecting from {name}. Choose a highlighted input.', { name: t(graph.nodes.find(n => n.id === source)?.label ?? '') })}</span><button onClick={() => setSource(null)}>{t('Cancel')}</button></div>}
      <div className="assistant-viewport-controls"><div className="assistant-zoom-controls"><button aria-label={t('Zoom out')} disabled={zoom <= .151} onClick={() => void flow?.zoomOut({ duration: 120 })}>−</button><button className="assistant-zoom-value" aria-label={t('Reset zoom to 100%')} title={t('Reset zoom to 100%')} onClick={() => void flow?.zoomTo(1, { duration: 180 })}>{Math.round(zoom * 100)}%</button><button aria-label={t('Zoom in')} disabled={zoom >= 1.749} onClick={() => void flow?.zoomIn({ duration: 120 })}>＋</button><button onClick={fit}>{t('Fit workflow')}</button></div><select aria-label={t('Locate node')} value={selected ?? ''} onChange={e => focusNode(e.target.value)}><option value="">{t('Locate node')}</option>{graph.nodes.map(n => <option key={n.id} value={n.id}>{t(n.label)}</option>)}</select><button aria-pressed={showMap} onClick={() => setShowMap(!showMap)}>{t('Overview map')}</button></div>
    </div>
    <div className="assistant-board-hint"><span className="assistant-status-dot" /><span role="status" aria-live="polite">{feedback ? t(feedback) : readonly ? t('Read-only workflow') : t('Drag to move · Click or drag ports to connect')}</span>{feedback && <button aria-label={t('Dismiss message')} onClick={() => setFeedback('')}>×</button>}<button className="assistant-shortcut-button" onClick={() => setHelp(true)}>{t('Shortcuts')} ?</button></div>
    <TerminalDialog open={help} onClose={() => setHelp(false)} title={t('Canvas shortcuts')} className="assistant-shortcuts-dialog"><dl>{[['F', 'Fit workflow'], ['Space + drag', 'Pan canvas'], ['Ctrl / ⌘ + Z', 'Undo'], ['Ctrl / ⌘ + Shift + Z', 'Redo'], ['Delete', 'Remove selected node or connection'], ['Esc', 'Cancel connection or close a menu']].map(([keys, label]) => <div key={keys}><dt>{t(label)}</dt><dd><kbd>{keys}</kbd></dd></div>)}</dl><p>{t('Shortcuts apply while the canvas is focused. Text editors keep their normal shortcuts.')}</p></TerminalDialog>
  </div>
}
