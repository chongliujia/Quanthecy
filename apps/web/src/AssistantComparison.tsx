import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type Organization } from './api'
import type { Assistant } from './assistantTypes'
import type { PaperCandidate, PaperLabData } from './paperTypes'
import { t } from './i18n'

export default function AssistantComparison({ userId, organization, current, preselected, onCreated }: { userId: string; organization: Organization; current: PaperLabData | null; preselected: string | null; onCreated: (data: PaperLabData) => void }) {
  const client = useQueryClient()
  const [open, setOpen] = useState(!!preselected)
  const [selected, setSelected] = useState<string[]>(preselected ? [preselected] : [])
  const [markets, setMarkets] = useState<string[] | null>(null)
  const [name, setName] = useState(t('Assistant comparison'))
  const [capital, setCapital] = useState(current?.accounts[0]?.initial_cash ?? '10000')
  const [daily, setDaily] = useState(10)
  const versions = useQuery({ queryKey: ['assistants', userId, organization.id], queryFn: () => api<Assistant[]>(`/organizations/${organization.id}/assistants`), enabled: open })
  const candidates = useQuery({ queryKey: ['assistant-candidates', userId, organization.id], queryFn: () => api<PaperCandidate[]>(`/organizations/${organization.id}/paper/candidates`), enabled: open && !current })
  const options = versions.data?.filter(a => !a.is_default).flatMap(a => a.versions) ?? []
  const ids = current?.market_ids ?? markets ?? candidates.data?.map(m => m.id) ?? []
  const create = useMutation({ mutationFn: () => api<PaperLabData>(`/organizations/${organization.id}/paper`, 'POST', { version: 'paper-v3', name, market_ids: ids, initial_cash: capital, daily_review_limit: daily, assistant_version_ids: selected }), onSuccess: data => { void client.invalidateQueries({ queryKey: ['assistants', userId, organization.id] }); onCreated(data) } })
  const writable = organization.role !== 'VIEWER'
  return <details className="panel assistant-comparison" open={open} onToggle={e => setOpen(e.currentTarget.open)}><summary>{t('Start an assistant comparison')}</summary>{open && <><p>{t('Compare the default team and up to three published versions against momentum, buy-and-hold and cash. Each account has separate virtual capital.')}</p>
    {current && <p className="paper-notice">{t('Starting a new comparison stops new trading in the current experiment. Its ledger and positions remain available. The new comparison reuses its market universe.')}</p>}
    <div className="assistant-actions"><label>{t('Experiment name')}<input value={name} maxLength={120} disabled={!writable} onChange={e => setName(e.target.value)} /></label><label>{t('Initial virtual capital per account')}<input type="number" min="100" max="1000000" value={capital} disabled={!writable} onChange={e => setCapital(e.target.value)} /></label><label>{t('Automatic reviews per day')}<input type="number" min="1" max="20" value={daily} disabled={!writable} onChange={e => setDaily(Number(e.target.value))} /></label></div>
    <p><strong>{t('Default assistant')}</strong> · 5 {t('model calls per review')} · {t('Always included')}</p>
    <div className="assistant-version-options">{options.map(v => <label key={v.id}><input type="checkbox" checked={selected.includes(v.id)} disabled={!writable || (!selected.includes(v.id) && selected.length >= 3)} onChange={e => setSelected(e.target.checked ? [...selected, v.id] : selected.filter(id => id !== v.id))} /><span>{t(v.name)} · v{v.number}<small>{v.graph.nodes.length} {t('model calls per review')}</small></span></label>)}</div>
    {!current && <div className="paper-candidates">{candidates.data?.map(m => <label key={m.id}><input type="checkbox" checked={ids.includes(m.id)} disabled={!writable} onChange={e => setMarkets(e.target.checked ? [...ids, m.id] : ids.filter(id => id !== m.id))} /><span>{m.title}<small>{m.platform}</small></span></label>)}</div>}
    <p className="quiet">{ids.length} {t('markets')} · {t('A team review reserves one call per node. Workspace model limits also apply. Calls execute in a shared queue, so waiting time is measured in the results.')}</p>
    {[create.error, versions.error, candidates.error].filter(Boolean).map((error, i) => <p key={i} role="alert">{t(error!.message)}</p>)}
    <button className="primary" disabled={!writable || create.isPending || !ids.length || !name.trim() || Number(capital) < 100 || Number(capital) > 1000000 || !Number.isInteger(daily) || daily < 1 || daily > 20} onClick={() => create.mutate()}>{create.isPending ? t('Starting…') : t('Start comparison with virtual capital')}</button>
  </>}</details>
}
