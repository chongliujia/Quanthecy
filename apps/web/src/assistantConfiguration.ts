import type { AssistantNode, NodeKind } from './assistantTypes'
import { skillError } from './assistantGraph'

export const roleChecklists: Record<NodeKind, string[]> = {
  quant: [
    'Assess supplied movement, spread and liquidity metrics; do not recalculate them.',
    'Separate sustained signals from stale observations and isolated price changes.',
    'Cite the relevant metrics and state which data gaps weaken the signal.',
  ],
  events: [
    'Check when each source was published and whether it was known at the cutoff.',
    'Distinguish new evidence from repeated coverage of the same source.',
    'Identify contradictory evidence and explain its relevance to this contract.',
  ],
  pricing: [
    'Check the exact YES outcome, resolution source and settlement deadline.',
    'Compare related markets only when their wording and settlement conditions match.',
    'State unresolved contract ambiguities without treating price differences as arbitrage.',
  ],
  risk: [
    'Challenge each upstream conclusion against its cited evidence.',
    'Preserve disagreements, missing evidence and conditions that invalidate the thesis.',
    'Separate blocking risks from ordinary cautions; agreement between agents is not independent evidence.',
  ],
  review: [
    'Use ALLOW only when the evidence supports entry with no unresolved blocking risks or required evidence gaps.',
    'Use REJECT for cited blocking risks and WAIT when necessary evidence is missing or inconclusive.',
    'Do not infer win rates from confidence or override deterministic execution checks.',
  ],
}

export function nodeConfigurationError(node: AssistantNode): string | null {
  const cap = node.max_output_tokens
  if (cap != null && (!Number.isInteger(cap) || cap < 256 || cap > 65536)) return 'Choose a whole-number output limit between 256 and 65,536, or inherit the workspace limit.'
  return skillError(node.skills ?? [], node.prompt ?? '', node.instructions)
}

export function effectiveOutputLimit(node: AssistantNode, workspaceLimit: number | null | undefined, paper = false): number | null {
  if (workspaceLimit == null || nodeConfigurationError(node)) return null
  return Math.min(workspaceLimit, node.max_output_tokens ?? workspaceLimit, paper ? 2048 : Infinity)
}
