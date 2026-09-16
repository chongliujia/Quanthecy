import { t } from './i18n'
export type ModelConfiguration = {
  revision: number; provider: 'openai' | 'openai_compatible' | 'anthropic'; base_url: string; model: string;
  has_api_key: boolean; encryption_available: boolean; enabled: boolean;
  daily_run_limit: number; max_output_tokens: number; allowed_endpoints: string[];
}
export type AgentStatus = { enabled: boolean; model: string; can_manage: boolean; can_run: boolean; runs_today: number; daily_run_limit: number; configuration_issue?: string }
export type Claim = { kind: 'OBSERVATION' | 'HYPOTHESIS' | 'EXPLANATION'; text: string; references: string[] }
export type Forecast = { status: 'ESTIMATE' | 'ABSTAIN'; target: 'YES_AT_CONTRACT_RESOLUTION'; probability: number | null; lower: number | null; upper: number | null; rationale: Claim; assumptions: string[]; invalidation_triggers: string[]; calibration: 'UNCALIBRATED' }
export type Report = { action: 'IGNORE' | 'WATCH' | 'INVESTIGATE'; confidence: number; thesis: Claim; claims: Claim[]; counter_evidence: Claim[]; key_signals: string[]; risk_flags: string[]; follow_up: string[]; disagreements?: Claim[]; forecast?: Forecast }
export type ResearchSkill = { id: string; name: string; responsibility: string; reference_kinds: string[]; dependencies: string[]; checklist?: string[]; version: string }
export type SpecialistOutput = { summary: Claim; findings: Claim[]; challenges: Claim[]; limitations: string[]; watch_for: string[] }
export type ValidationIssue = { field: string; code: string }
export type AgentStep = { id: string; name: string; skill_version: string; skill?: ResearchSkill | null; state: string; output: SpecialistOutput | Report | null; started_at: string; finished_at: string | null; error_code: string; validation_errors?: ValidationIssue[]; usage: Record<string, number>; input_manifest: { cutoff: string; context_sha256: string; reference_ids: string[]; omitted_reference_ids: string[]; reference_bytes: number; dependencies: string[] } }
export type ResearchReference = { id: string; kind: string; label: string; value?: unknown; url?: string }
export type AgentRun = { id: string; market_id: string | null; kind: string; state: string; stage: string; cutoff: string; configuration_revision: number; model: string; prompt_version: string; workflow?: 'single' | 'team'; language?: 'zh' | 'en'; reserved_calls?: number; steps?: AgentStep[]; report: Report | null; usage: Record<string, number>; error_code: string; validation_errors?: ValidationIssue[]; created_at: string; finished_at: string | null; context?: { references: ResearchReference[]; limitations: string[]; quality?: { history_ready: boolean; stale: boolean; forecast_eligible: boolean }; manifest?: { sha256: string; reference_count: number; observation_count: number; window_minutes: number } } }
export const activeRun = (run: AgentRun) => ['PENDING', 'RUNNING'].includes(run.state)
export function runError(code: string) {
  const messages: Record<string, string> = {
    provider_auth: 'Authentication failed (401/403). Check the API key and its provider permissions.',
    provider_not_found: 'The endpoint or model was not found (404). Check the base URL and exact model ID.',
    provider_bad_request: 'The provider rejected the request (400). Check the model ID and supported protocol or parameters.',
    provider_quota: 'The provider reported insufficient balance or quota (402).',
    provider_rate_limit: 'The provider rate or quota limit was reached (429). Try later or check your account limits.',
    provider_network: 'The server could not connect to the model provider. Check server connectivity or proxy settings.',
    provider_unavailable: 'The model provider is temporarily unavailable (5xx). Try again later.',
    provider_output_limit: 'The model reached the output token limit. Increase the limit or use a model with a shorter response.',
    provider_invalid_response: 'The provider returned an unsupported response. Check the API protocol and JSON output support.',
    provider_failed: 'The model request failed. Check the endpoint, model and credentials in Model settings.',
    invalid_report: 'The response failed report or evidence validation. No report was published.',
    context_unavailable: 'The historical context could not be assembled. Check data availability.',
    configuration_changed: 'Model settings changed. Start a new analysis with the saved configuration.',
    interrupted: 'The worker was interrupted or timed out. This request will not be retried automatically.',
    provider_timeout: 'The model exceeded the time limit. This request will not be retried automatically.',
    context_too_large: 'The research context exceeds the input limit.',
  }
  return t(messages[code] ?? 'This request could not be completed. You can start a new request.')
}
