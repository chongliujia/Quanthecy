import type { ValidationIssue } from './agentTypes'
import { t } from './i18n'

const reasons: Record<string, string> = {
  invalid_json: 'The response is not one complete JSON object, or contains duplicate fields.',
  invalid_shape: 'The response has an unexpected object structure.',
  missing_field: 'A required field is missing.',
  extra_field: 'The response includes an unsupported field.',
  invalid_type: 'The field has the wrong value type.',
  invalid_value: 'The field value is outside the allowed choices or range.',
  too_long: 'The text exceeds the length allowed by the report schema.',
  too_many: 'The list contains more items than the report schema allows.',
  unknown_reference: 'A citation does not match the evidence IDs available to this expert.',
  unknown_signal: 'A cited signal is not in the supplied signal list.',
  output_size: 'The structured result exceeds the context memory budget.',
  forecast_not_supported: 'The forecast is not supported by eligible event evidence.',
  forecast_bounds: 'The forecast bounds or abstention fields are inconsistent.',
}

export default function ValidationNotice({ issues = [], stage }: { issues?: ValidationIssue[]; stage?: string }) {
  return <div className="validation-notice" role="alert">
    <strong>{t('The model responded, but this result did not pass validation.')}</strong>
    {stage && <p>{t('Failed stage')}: {t(stage)}</p>}
    {issues.length ? <ul>{issues.map((issue, index) => <li key={index}><code>{issue.field}</code><span>{t(reasons[issue.code] ?? 'The report field could not be validated.')}</span></li>)}</ul>
      : <p>{t('This older run did not record the specific validation issue. New analyses now record the field and reason.')}</p>}
    <small>{t('No report was published and no automatic model retry was made.')}</small>
  </div>
}
