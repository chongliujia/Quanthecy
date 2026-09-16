import type { ReactNode } from 'react'
import { t } from './i18n'
import { probability, readable } from './format'
import { activeRun, runError, type AgentRun, type Claim, type ResearchSkill } from './agentTypes'
import ValidationNotice from './ValidationNotice'

type Claims = (item: Claim, index: number) => ReactNode

export function ExpertTeam({ skills, run, claim }: { skills: ResearchSkill[]; run?: AgentRun; claim: Claims }) {
  return <section className="expert-team" aria-label={t('Expert team')}>
    <div className="intelligence-heading"><h3>{t('Expert team')}</h3><span>{t('Independent analysis → review → synthesis')}</span></div>
    <div className="expert-grid">{skills.map((definition, index) => {
      const step = run?.steps?.find(item => item.id === definition.id)
      const skill = step?.skill ?? definition
      const state = step?.state === 'RUNNING' && run && !activeRun(run) ? run.state : step?.state ?? (run && !activeRun(run) ? 'NOT_RUN' : 'PENDING')
      const output = step?.output && 'summary' in step.output ? step.output : null
      return <details className={`expert-card expert-${state.toLowerCase()}`} key={skill.id}>
        <summary><span className="expert-number">0{index + 1}</span><span><strong>{t(skill.name)}</strong><small>{t(state.toLowerCase().replaceAll('_', ' '))} · {t('Skill')} {step?.skill_version ?? skill.version}</small></span><span className="expert-indicator" /></summary>
        <div className="expert-body"><p>{t(skill.responsibility)}</p>
          <details className="skill-method"><summary>{t('Research method')}</summary><ol>{skill.checklist?.map(item => <li key={item}>{t(item)}</li>)}</ol></details>
          <small>{t('Reads')}: {skill.reference_kinds.map(readable).join(' · ')}</small>
          {output && <><h4>{t('Expert conclusion')}</h4>{claim(output.summary, 0)}{output.findings.map(claim)}
            {!!output.challenges.length && <><h4>{t('Challenges')}</h4>{output.challenges.map(claim)}</>}
            <h4>{t('Research limitations')}</h4><ul>{output.limitations.map((item, i) => <li key={i}>{item}</li>)}</ul>
            <h4>{t('Next observations')}</h4><ul>{output.watch_for.map((item, i) => <li key={i}>{item}</li>)}</ul></>}
          {step?.format_adjustments?.map(adjustment => <p className="format-note" key={adjustment.field}>{t('Local formatting: {field}, {before} items arranged into {after} groups. All original text retained; no extra model request.', { field: t(['limitations', 'risk_flags'].includes(adjustment.field) ? 'Research limitations' : 'Next observations'), before: adjustment.original_count, after: adjustment.grouped_count })}</p>)}
          {step?.error_code && (step.error_code === 'invalid_report' ? <ValidationNotice issues={step.validation_errors} /> : <p className="error">{runError(step.error_code)}</p>)}
          {step && <details className="step-context"><summary>{t('Context manifest')} · {step.input_manifest.reference_ids.length} {t('references')}</summary>
            <p>{t('Scoped evidence; validated peer findings only. Raw observation history is not sent to the model.')}</p>
            <small>{t('Dependencies')}: {step.input_manifest.dependencies.map(readable).join(' · ') || t('Independent')}</small>
            <small>{t('Input bytes')}: {step.input_manifest.reference_bytes.toLocaleString()}</small>
            {!!step.input_manifest.omitted_reference_ids.length && <p>{t('Omitted by context budget')}: {step.input_manifest.omitted_reference_ids.join(', ')}</p>}
            <code>{step.input_manifest.context_sha256}</code>
          </details>}
        </div>
      </details>
    })}</div>
    {run?.context?.manifest && <div className="context-summary"><span>{t('Frozen context')}</span><strong>{run.context.manifest.reference_count} {t('references')}</strong><strong>{run.context.manifest.observation_count} {t('observations')}</strong><small>{run.context.manifest.window_minutes} {t('minute window')}</small></div>}
    {run?.context?.limitations?.map((item, i) => <p className="context-limitation" key={i}>{t(item)}</p>)}
    {run && run.state !== 'SUCCEEDED' && !!run.steps?.some(step => step.state === 'SUCCEEDED') && <p className="data-warning">{t('Intermediate expert findings are not a completed report.')}</p>}
  </section>
}

export function ForecastView({ run, claim }: { run: AgentRun; claim: Claims }) {
  const forecast = run.report?.forecast
  if (!forecast) return null
  const reference = run.context?.references.find(item => item.id === 'market')
  const value = reference?.value as { probability?: { value?: number; basis?: string } } | undefined
  const market = value?.probability
  return <section className="forecast-card" aria-label={t('Conditional forecast')}>
    <div className="intelligence-heading"><h3>{t('Conditional forecast')}</h3><span className="badge badge-amber">{t('Uncalibrated')}</span></div>
    <p>{t('YES outcome at contract resolution')}</p>
    <div className="forecast-values"><div><small>{t('Market-implied probability')}</small><strong>{probability(market?.value)}</strong><small>{market?.basis ? readable(market.basis) : t('Unavailable')}</small></div>
      <div><small>{t('Agent estimate')}</small><strong>{forecast.status === 'ABSTAIN' ? t('Abstain') : probability(forecast.probability)}</strong><small>{forecast.status === 'ESTIMATE' ? `${probability(forecast.lower)} – ${probability(forecast.upper)}` : t('Insufficient support')}</small></div></div>
    {claim(forecast.rationale, 0)}
    {!!forecast.assumptions.length && <><h4>{t('Assumptions')}</h4><ul>{forecast.assumptions.map((item, i) => <li key={i}>{item}</li>)}</ul></>}
    {!!forecast.invalidation_triggers.length && <><h4>{t('Invalidation triggers')}</h4><ul>{forecast.invalidation_triggers.map((item, i) => <li key={i}>{item}</li>)}</ul></>}
    <p className="confidence-note">{t('Subjective scenario range, not a statistical confidence interval. Forecast accuracy has not been measured.')}</p>
  </section>
}
