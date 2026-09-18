import type { AgentStep, Claim } from './agentTypes'

export type NodeKind = 'quant' | 'events' | 'pricing' | 'risk' | 'review'
export type NodeSkillFile = { name: string; content: string; enabled: boolean }
export type AssistantNode = { id: string; kind: NodeKind; label: string; instructions: string; prompt?: string; skills?: NodeSkillFile[]; x: number; y: number }
export type AssistantGraph = { schema_version: 1; nodes: AssistantNode[]; edges: { source: string; target: string }[]; entry_change_15m: number }
export type AssistantVersion = { id: string; assistant_id: string; number: number; name: string; graph: AssistantGraph; graph_hash: string; runtime_version: string; created_at: string }
export type Assistant = { id: string; name: string; revision: number; is_default: boolean; draft: AssistantGraph; versions: AssistantVersion[]; updated_at: string }
export type EntryReview = { decision: 'ALLOW' | 'REJECT' | 'WAIT'; rationale: Claim; blocking_risks: Claim[]; cautions: Claim[]; missing_evidence: string[] }
export type AssistantStep = Omit<AgentStep, 'output'> & { output: AgentStep['output'] | EntryReview; input_packet?: Record<string, unknown> }
export type AssistantRun = {
  id: string; kind: string; state: string; stage: string; model: string; assistant_id: string
  assistant_version_id: string | null; assistant_graph_hash: string; assistant_graph?: AssistantGraph
  assistant_name?: string; reserved_calls: number; steps: AssistantStep[]; report: EntryReview | null; usage: Record<string, number>
  error_code: string; created_at: string; finished_at: string | null; cutoff: string
  context?: { references: { id: string; label: string; value?: unknown; url?: string }[] }
}
export const nodeNames: Record<NodeKind, string> = { quant: 'Quantitative analyst', events: 'Event intelligence analyst', pricing: 'Investment research analyst', risk: 'Risk reviewer', review: 'Entry reviewer' }

export const nodeDescriptions: Record<NodeKind, string> = {
  quant: 'Interpret price movement, liquidity and deterministic signals.',
  events: 'Connect new evidence with event timing and market expectations.',
  pricing: 'Examine contract wording, settlement rules and valuation assumptions.',
  risk: 'Challenge upstream findings and surface unresolved risks.',
  review: 'Combine reviewed evidence into an ALLOW, REJECT or WAIT decision.',
}

export type AssistantRunSummary = Pick<AssistantRun, 'id' | 'kind' | 'state' | 'stage' | 'model' | 'assistant_id' | 'assistant_version_id' | 'assistant_name' | 'reserved_calls' | 'usage' | 'error_code' | 'created_at' | 'finished_at'>
