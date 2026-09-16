import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import { ExpertTeam } from './IntelligenceView'
import { setLanguage } from './i18n'
import type { AgentRun, AgentStep, ResearchSkill } from './agentTypes'

const documentLimit = "Official document passages are bounded excerpts selected by policy terms, not the complete article. Omitted passages may qualify or contradict an interpretation. Captured text covers the source page only; linked articles and PDF attachments are not included. A minutes release is not the full meeting minutes. A speech expresses the speaker's views, not a committee decision."
const evidenceLimit = 'No version-bound, directly relevant event evidence has been reviewed. Event probability estimates must be withheld; background and topic matches are insufficient.'
const skill: ResearchSkill = { id: 'events', name: 'Event intelligence analyst', responsibility: 'Review evidence.', version: '1.4.0', reference_kinds: ['evidence'], dependencies: [] }
const run: AgentRun = { id: 'r1', market_id: 'm1', kind: 'RESEARCH', state: 'SUCCEEDED', stage: 'completed', cutoff: '', configuration_revision: 1, model: 'fixture', prompt_version: 'research-team-v5', usage: {}, error_code: '', created_at: '', finished_at: '', report: null, context: { references: [], limitations: [documentLimit, evidenceLimit] } }

it('translates both screenshot context warnings without altering frozen originals', () => {
  setLanguage('zh')
  render(<ExpertTeam skills={[skill]} run={run} claim={item => <p>{item.text}</p>} />)
  expect(screen.getByText(/官方正文仅提供按政策关键词选取的有限片段/)).toBeVisible()
  expect(screen.getByText(/尚无绑定具体版本的直接相关证据审核/)).toBeVisible()
  expect(screen.queryByText(documentLimit)).not.toBeInTheDocument()
  expect(run.context?.limitations).toEqual([documentLimit, evidenceLimit])
})

it('discloses lossless local formatting and displays every grouped caveat', () => {
  const limitations = Array.from({ length: 11 }, (_, i) => `Caveat ${i + 1}`)
  limitations.push('• Material risk A\n• Material risk B')
  const step: AgentStep = { id: 'events', name: skill.name, skill_version: skill.version, skill, state: 'SUCCEEDED', started_at: '', finished_at: '', error_code: '', usage: {}, input_manifest: { cutoff: '', context_sha256: 'sha', reference_ids: [], omitted_reference_ids: [], reference_bytes: 1, dependencies: [] }, output: { summary: { text: 'Event evidence summary.', kind: 'HYPOTHESIS', references: ['market'] }, findings: [], challenges: [], limitations, watch_for: [] }, format_adjustments: [{ field: 'limitations', original_count: 13, grouped_count: 12, method: 'consecutive_text_grouping_v1' }] }
  render(<ExpertTeam skills={[skill]} run={{ ...run, steps: [step] }} claim={item => <p>{item.text}</p>} />)
  fireEvent.click(screen.getByText(skill.name))
  expect(screen.getByText(/13 items arranged into 12 groups/)).toBeVisible()
  expect(screen.getByText(/Material risk A/)).toHaveTextContent('Material risk B')
  expect(screen.getByText(/13 items arranged into 12 groups/)).toHaveTextContent('no extra model request')
})
