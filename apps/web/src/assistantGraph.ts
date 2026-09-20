import type { AssistantGraph, NodeSkillFile } from './assistantTypes'

export function connectionError(graph: AssistantGraph, source: string, target: string): string | null {
  const from = graph.nodes.find(n => n.id === source), to = graph.nodes.find(n => n.id === target)
  if (!from || !to) return 'Choose two existing nodes.'
  if (source === target) return 'A node cannot connect to itself.'
  if (from.kind === 'review') return 'Entry review is the final node.'
  if (to.kind === 'review' && from.kind !== 'risk') return 'Connect analysts to risk review first.'
  if (from.kind === 'risk' && to.kind !== 'review') return 'Risk review connects only to entry review.'
  if (graph.edges.some(e => e.source === source && e.target === target)) return 'These nodes are already connected.'
  const pending = [target], seen = new Set<string>()
  while (pending.length) {
    const id = pending.pop()!
    if (id === source) return 'This connection would create a cycle.'
    if (seen.has(id)) continue
    seen.add(id)
    pending.push(...graph.edges.filter(e => e.source === id).map(e => e.target))
  }
  return null
}

export function canConnect(graph: AssistantGraph, source: string, target: string) {
  return connectionError(graph, source, target) === null
}

export type FlowDirection = 'vertical' | 'horizontal'
export function graphDirection(graph: AssistantGraph): FlowDirection {
  let x = 0, y = 0
  for (const e of graph.edges) {
    const source = graph.nodes.find(n => n.id === e.source), target = graph.nodes.find(n => n.id === e.target)
    if (source && target) { x += target.x - source.x; y += target.y - source.y }
  }
  return x > y ? 'horizontal' : 'vertical'
}

export function arrangeGraph(graph: AssistantGraph, direction: FlowDirection = 'vertical'): AssistantGraph {
  const levels = new Map<string, number>(), pending = new Set(graph.nodes.map(n => n.id))
  while (pending.size) {
    const ready = [...pending].filter(id => graph.edges.filter(e => e.target === id).every(e => levels.has(e.source)))
    if (!ready.length) { for (const id of pending) levels.set(id, 0); break }
    for (const id of ready) {
      levels.set(id, Math.max(-1, ...graph.edges.filter(e => e.target === id).map(e => levels.get(e.source)!)) + 1)
      pending.delete(id)
    }
  }
  const counts = new Map<number, number>(), slots = new Map<number, number>()
  for (const level of levels.values()) counts.set(level, (counts.get(level) ?? 0) + 1)
  const max = Math.max(1, ...counts.values())
  return { ...graph, nodes: graph.nodes.map(n => {
    const level = levels.get(n.id)!, slot = slots.get(level) ?? 0
    slots.set(level, slot + 1)
    const cross = (max - counts.get(level)!) / 2 + slot
    return direction === 'horizontal'
      ? { ...n, x: 40 + level * 280, y: 40 + cross * 190 }
      : { ...n, x: 40 + cross * 270, y: 40 + level * 220 }
  }) }
}

export const clampCoordinate = (value: number) => Math.max(-100000, Math.min(100000, value))

export function freeNodePosition(graph: AssistantGraph, preferred: { x: number; y: number }) {
  const x = clampCoordinate(Math.round(preferred.x / 10) * 10), y = clampCoordinate(Math.round(preferred.y / 10) * 10)
  const candidates = [{ x, y }]
  for (let row = -8; row <= 8; row++) for (let col = -8; col <= 8; col++) candidates.push({ x: clampCoordinate(x + col * 270), y: clampCoordinate(y + row * 190) })
  candidates.sort((a, b) => Math.hypot(a.x - x, a.y - y) - Math.hypot(b.x - x, b.y - y))
  return candidates.find(p => graph.nodes.every(n => Math.abs(n.x - p.x) >= 250 || Math.abs(n.y - p.y) >= 168)) ?? { x, y }
}

export type GraphIssue = { nodeId: string; message: string }
export function graphIssues(graph: AssistantGraph): GraphIssue[] {
  const issues: GraphIssue[] = [], risk = graph.nodes.find(n => n.kind === 'risk'), review = graph.nodes.find(n => n.kind === 'review')
  if (!risk || !review || !graph.nodes.some(n => !['risk', 'review'].includes(n.kind))) return [{ nodeId: graph.nodes[0]?.id ?? '', message: 'Include at least one analyst, one risk reviewer and one entry reviewer.' }]
  for (const n of graph.nodes) {
    if (n.kind === 'review') continue
    const goal = n.kind === 'risk' ? review.id : risk.id
    const pending = [n.id], seen = new Set<string>()
    while (pending.length) {
      const id = pending.pop()!
      if (seen.has(id)) continue
      seen.add(id); pending.push(...graph.edges.filter(e => e.source === id).map(e => e.target))
    }
    if (!seen.has(goal)) issues.push({ nodeId: n.id, message: n.kind === 'risk' ? 'Connect this node to entry review.' : 'This analyst has no path to risk review.' })
  }
  for (const [i, e] of graph.edges.entries()) {
    const error = connectionError({ ...graph, edges: graph.edges.filter((_, index) => index !== i) }, e.source, e.target)
    if (error && !issues.some(issue => issue.nodeId === e.source && issue.message === error)) issues.push({ nodeId: e.source, message: error })
  }
  return issues
}

export function skillError(skills: NodeSkillFile[], prompt = '', focus = ''): string | null {
  if (skills.length > 5) return 'Each node supports up to 5 skill files.'
  if (prompt.length > 8000) return 'The node prompt is limited to 8,000 characters.'
  const names = new Set<string>()
  for (const file of skills) {
    if (file.name.length > 100 || !/^[\p{L}\p{N}_][\p{L}\p{N}_ .-]*\.md$/iu.test(file.name)) return 'Use a Markdown filename without folders, such as SKILL.md.'
    if (names.has(file.name.toLocaleLowerCase())) return 'Skill filenames must be unique within a node.'
    names.add(file.name.toLocaleLowerCase())
    if (file.content.length > 12000 || new TextEncoder().encode(file.content).length > 16000) return 'Each skill file is limited to 12,000 characters and 16 KB.'
    if ([...file.content].some(c => c.charCodeAt(0) < 32 && !'\n\r\t'.includes(c))) return 'Skill files must contain plain Markdown text.'
  }
  // Conservative allowance for JSON escaping and separators, matching the backend.
  if (new TextEncoder().encode(JSON.stringify([focus, prompt, skills])).length + 100 > 32000) return 'Node prompt and skill files must fit within 32 KB.'
  return null
}
