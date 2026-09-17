import { useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type Organization } from './api'
import { t } from './i18n'
import { directionLabels } from './watchlistTypes'
import { change, probability, time } from './format'
import { ErrorNotice } from './ResearchUI'
import { useWatchlist, useWatchlists } from './watchlistQueries'
import AlertInbox from './AlertInbox'
import { useCollectionStatus } from './collectionHealth'
import { qualityReasons } from './qualityReasons'
import type { AlertRule, AlertRuleInput, Watchlist } from './watchlistTypes'
import './watchlists.css'

export default function WatchlistsPage({ userId, organization }: { userId: string; organization?: Organization }) {
  if (!organization) return <p>{t('Select a workspace to manage watchlists.')}</p>
  return <WorkspaceWatchlists key={organization.id} userId={userId} organization={organization} />
}

function WorkspaceWatchlists({ userId, organization }: { userId: string; organization: Organization }) {
  const client = useQueryClient()
  const lists = useWatchlists(userId, organization.id)
  const [chosen, setChosen] = useState('')
  const [name, setName] = useState('')
  const [renaming, setRenaming] = useState(false)
  const [confirmArchive, setConfirmArchive] = useState(false)
  const [view, setView] = useState('lists')
  const selected = lists.data?.find(list => list.id === chosen) ?? lists.data?.[0]
  const detail = useWatchlist(userId, organization.id, selected?.id)
  const health = useCollectionStatus(userId)
  const canWrite = organization.role !== 'VIEWER'
  async function refresh() {
    await Promise.all([client.invalidateQueries({ queryKey: ['watchlists', userId, organization.id] }), client.invalidateQueries({ queryKey: ['watchlist', userId, organization.id] }), client.invalidateQueries({ queryKey: ['alert-rules', userId, organization.id] })])
  }
  const save = useMutation({ mutationFn: () => api<Watchlist>(`/organizations/${organization.id}/watchlists${renaming && selected ? `/${selected.id}` : ''}`, renaming ? 'PATCH' : 'POST', { name }),
    onSuccess: async list => { setName(''); setRenaming(false); setChosen(list.id); await refresh() } })
  const archive = useMutation({ mutationFn: () => api(`/organizations/${organization.id}/watchlists/${selected!.id}`, 'DELETE'), onSuccess: async () => { setChosen(''); setConfirmArchive(false); await refresh() } })
  const remove = useMutation({ mutationFn: (id: string) => api(`/organizations/${organization.id}/watchlists/${selected!.id}/items/${id}`, 'DELETE'), onSuccess: refresh })
  const reorder = useMutation({ mutationFn: (ids: string[]) => api(`/organizations/${organization.id}/watchlists/${selected!.id}/order`, 'PUT', { market_ids: ids }), onSuccess: refresh })
  function move(index: number, delta: number) {
    const ids = detail.data?.items.map(item => item.market.id) ?? []
    ;[ids[index], ids[index + delta]] = [ids[index + delta], ids[index]]
    reorder.mutate(ids)
  }
  return <section className="watch-workspace">
    <div className="watch-heading"><div className="watch-view-switch" role="group" aria-label={t('Watchlist workspace view')}><button aria-pressed={view === 'lists'} onClick={() => setView('lists')}>{t('Watchlists')}</button><button aria-pressed={view === 'inbox'} onClick={() => setView('inbox')}>{t('Alert inbox')}</button></div><span className="quiet">{t('Shared lists · Personal read status')}</span></div>
    {health.data?.analytics_state !== 'active' && <p className="watch-health" role="status">{health.error ? t('Collection diagnostics are unavailable.') : health.isPending ? t('Checking alert processing…') : t('Alert processing heartbeat is unavailable. A stopped or delayed worker cannot evaluate new observations.')}</p>}
    {view === 'inbox' ? <AlertInbox userId={userId} organizationId={organization.id} /> : <>
      <div className="watch-list-toolbar"><label>{t('Watchlist')}<select value={selected?.id ?? ''} onChange={event => { setChosen(event.target.value); setRenaming(false); setName(''); setConfirmArchive(false) }} disabled={!lists.data?.length}><option value="" disabled>{t('Choose a watchlist')}</option>{lists.data?.map(list => <option key={list.id} value={list.id}>{list.name} ({list.count})</option>)}</select></label>
        {canWrite && <form onSubmit={e => { e.preventDefault(); save.mutate() }}><label className="sr-only" htmlFor="watchlist-name">{t('Watchlist name')}</label><input id="watchlist-name" aria-label={t('Watchlist name')} placeholder={t('Watchlist name')} value={name} maxLength={80} onChange={event => setName(event.target.value)} required /><button disabled={save.isPending || !name.trim()}>{renaming ? t('Save name') : t('Create watchlist')}</button>{renaming && <button type="button" onClick={() => { setRenaming(false); setName('') }}>{t('Cancel')}</button>}</form>}
        {selected && canWrite && <div className="watch-actions"><button onClick={() => { setRenaming(true); setName(selected.name) }}>{t('Rename')}</button><button onClick={() => setConfirmArchive(!confirmArchive)}>{t('Archive')}</button></div>}
      </div>
      {confirmArchive && selected && <div className="watch-health"><p>{t('Archive this watchlist and pause its rules? Existing alert history will remain.')}</p><button disabled={archive.isPending} onClick={() => archive.mutate()}>{t('Archive watchlist')}</button><button onClick={() => setConfirmArchive(false)}>{t('Cancel')}</button></div>}
      {lists.isPending && <p role="status">{t('Loading watchlists…')}</p>}{lists.error && <ErrorNotice error={lists.error} retry={() => void lists.refetch()} />}
      {[save.error, archive.error, remove.error, reorder.error].filter(Boolean).map((error, index) => <p role="alert" className="error" key={index}>{t(error!.message)}</p>)}
      {!selected && lists.data && <div className="watch-empty"><h2>{t('Start with the markets you follow')}</h2><p>{t('Create a list, then use “Watch market” in the research terminal. Each list can have its own alert rules.')}</p><a href="#/markets">{t('Explore markets →')}</a></div>}
      {selected && <div className="watch-columns"><div className="watch-markets">
        <div className="watch-heading"><h2>{selected.name}</h2><a href={`#/markets?watchlist=${selected.id}`}>{t('Open in market scanner →')}</a></div>
        <p className="quiet">{t('Saved quotes · Adding markets does not expand collection coverage.')}</p>
        {detail.isPending && <p role="status">{t('Loading markets…')}</p>}{detail.error && <ErrorNotice error={detail.error} retry={() => void detail.refetch()} />}
        <div className="watch-scroll table-scroll"><table><thead><tr><th>{t('Market · YES')}</th><th>{t('Midpoint')}</th><th>{t('15m change')}</th>{canWrite && <th>{t('Manage')}</th>}</tr></thead><tbody>{detail.data?.items.map(({ market }, index) => <tr key={market.id}><td><a href={`#/markets/${market.id}`}>{market.title}</a><small>{market.platform} · {t(market.status)} · {market.stale ? t('Stale') : t('Recent')}<br />{time(market.last_observed_at)}</small></td><td className="numeric">{probability(market.probability)}</td><td className="numeric">{change(market.metrics.probability_change_15m)}</td>{canWrite && <td><div className="watch-actions"><button aria-label={t('Move up: {market}', { market: market.title })} disabled={!index || reorder.isPending} onClick={() => move(index, -1)}>↑</button><button aria-label={t('Move down: {market}', { market: market.title })} disabled={index === detail.data!.items.length - 1 || reorder.isPending} onClick={() => move(index, 1)}>↓</button><button className="text-button" disabled={remove.isPending} onClick={() => remove.mutate(market.id)} aria-label={t('Remove from watchlist: {market}', { market: market.title })}>{t('Remove')}</button></div></td>}</tr>)}</tbody></table>
          {detail.data?.count === 0 && <p className="watch-empty">{t('This watchlist is empty. Add collected markets from the research terminal.')} <a href="#/markets">{t('Explore markets →')}</a></p>}
        </div>
      </div><RulesPanel key={selected.id} userId={userId} organization={organization} listId={selected.id} /></div>}
    </>}
  </section>
}

const stateLabels: Record<string, string> = { WAITING: 'Waiting for a new observation', ARMED: 'Watching', TRIGGERED: 'Alert recorded', LATCHED: 'Waiting for condition to clear', COOLDOWN: 'Cooldown', INELIGIBLE: 'Data not eligible', PAUSED: 'Paused' }
function RulesPanel({ userId, organization, listId }: { userId: string; organization: Organization; listId: string }) {
  const client = useQueryClient()
  const [editing, setEditing] = useState<AlertRule | null | undefined>()
  const query = useQuery({ queryKey: ['alert-rules', userId, organization.id, listId], queryFn: () => api<AlertRule[]>(`/organizations/${organization.id}/watchlists/${listId}/rules`), refetchInterval: 30000 })
  const canWrite = organization.role !== 'VIEWER'
  const toggle = useMutation({ mutationFn: (rule: AlertRule) => api(`/organizations/${organization.id}/watchlists/${listId}/rules/${rule.id}`, 'PUT', ruleInput(rule, !rule.enabled)), onSuccess: () => client.invalidateQueries({ queryKey: ['alert-rules', userId, organization.id, listId] }) })
  return <aside className="watch-rules"><div className="watch-heading"><h2>{t('Alert rules')}</h2>{canWrite && <button disabled={(query.data?.length ?? 0) >= 10} onClick={() => setEditing(null)}>{t('+ Rule')}</button>}</div>
    <p className="quiet">{t('Each rule tracks every market in this list independently.')}</p>
    <div className="watch-scroll">
      {editing !== undefined && <RuleEditor key={editing?.id ?? 'new'} userId={userId} organizationId={organization.id} listId={listId} rule={editing} done={() => setEditing(undefined)} />}
      {query.isPending && <p role="status">{t('Loading rules…')}</p>}{query.error && <ErrorNotice error={query.error} retry={() => void query.refetch()} />}
      {toggle.error && <p role="alert" className="error">{t(toggle.error.message)}</p>}
      {query.data?.length === 0 && editing === undefined && <p>{t('No rules yet. Add a price-change or spread-widening condition.')}</p>}
      {query.data?.map(rule => <article className="watch-rule" key={rule.id}><div className="watch-heading"><strong>{rule.name}</strong><span className="badge">{rule.enabled ? t('Enabled') : t('Paused')}</span></div>
        <p>{t(rule.kind === 'PROBABILITY_MOVE' ? 'Midpoint change' : 'Spread widening')} · {t(directionLabels[rule.direction])} ≥ {rule.threshold_pp} pp</p><small>{t('{minutes} minute window', { minutes: rule.window_minutes })} · {t('{minutes} minute cooldown', { minutes: rule.cooldown_minutes })}</small>
        {canWrite && <div className="watch-actions"><button onClick={() => setEditing(rule)}>{t('Edit')}</button><button disabled={toggle.isPending} onClick={() => toggle.mutate(rule)}>{rule.enabled ? t('Pause rule') : t('Resume rule')}</button></div>}
        <details><summary>{t('Evaluation status')} · {rule.states.length}</summary>{rule.states.length === 0 && <p>{t('Add markets to evaluate this rule.')}</p>}{rule.states.map(state => <div key={state.market_id} className="watch-rule-state"><a href={`#/markets/${state.market_id}`}>{state.title}</a><strong>{t(stateLabels[state.status] ?? state.status)}</strong>{state.reason && <small>{t(qualityReasons[state.reason] ?? (state.reason === 'awaiting_new_observation' ? 'Waiting for a new observation' : state.reason === 'rule_disabled' ? 'Rule disabled' : state.reason))}</small>}<small>{t('Last evaluation:')} {time(state.evaluated_at)}</small></div>)}</details>
      </article>)}
      <p className="quiet">{t('A rule re-arms only after a valid sample no longer meets its condition. Cooldown also applies. Stale or incomplete data never triggers an alert.')}</p>
    </div>
  </aside>
}

function ruleInput(rule: AlertRuleInput, enabled = rule.enabled): AlertRuleInput {
  return { name: rule.name, kind: rule.kind, direction: rule.direction, threshold_pp: rule.threshold_pp, window_minutes: rule.window_minutes, cooldown_minutes: rule.cooldown_minutes, enabled }
}

function RuleEditor({ userId, organizationId, listId, rule, done }: { userId: string; organizationId: string; listId: string; rule: AlertRule | null; done: () => void }) {
  const client = useQueryClient()
  const [value, setValue] = useState<AlertRuleInput>(rule ? ruleInput(rule) : { name: '', kind: 'PROBABILITY_MOVE', direction: 'EITHER', threshold_pp: 3, window_minutes: 15, cooldown_minutes: 30, enabled: true })
  const mutation = useMutation({ mutationFn: () => api(`/organizations/${organizationId}/watchlists/${listId}/rules${rule ? `/${rule.id}` : ''}`, rule ? 'PUT' : 'POST', value), onSuccess: async () => { await client.invalidateQueries({ queryKey: ['alert-rules', userId, organizationId, listId] }); done() } })
  function submit(event: FormEvent) { event.preventDefault(); mutation.mutate() }
  return <form className="watch-form rule-editor" onSubmit={submit}>
    <h3>{rule ? t('Edit alert rule') : t('New alert rule')}</h3>
    <label>{t('Rule name')}<input maxLength={100} required value={value.name} onChange={e => setValue({ ...value, name: e.target.value })} /></label>
    <label>{t('Condition')}<select value={value.kind} onChange={e => setValue({ ...value, kind: e.target.value as AlertRuleInput['kind'], direction: e.target.value === 'SPREAD_WIDENING' ? 'UP' : 'EITHER' })}><option value="PROBABILITY_MOVE">{t('Midpoint change')}</option><option value="SPREAD_WIDENING">{t('Spread widening')}</option></select></label>
    {value.kind === 'PROBABILITY_MOVE' && <label>{t('Direction')}<select value={value.direction} onChange={e => setValue({ ...value, direction: e.target.value as AlertRuleInput['direction'] })}>{['EITHER', 'UP', 'DOWN'].map(direction => <option key={direction} value={direction}>{t(directionLabels[direction])}</option>)}</select></label>}
    <div className="rule-fields"><label>{t('Threshold (pp)')}<input type="number" min="0.01" max="100" step="0.01" required value={value.threshold_pp} onChange={e => setValue({ ...value, threshold_pp: e.target.value })} /></label><label>{t('Window')}<select value={value.window_minutes} onChange={e => setValue({ ...value, window_minutes: Number(e.target.value) })}>{[5, 15, 60].map(minutes => <option key={minutes} value={minutes}>{t('{minutes} minutes', { minutes })}</option>)}</select></label></div>
    <label>{t('Cooldown (minutes)')}<input type="number" min="1" max="1440" step="1" required value={value.cooldown_minutes} onChange={e => setValue({ ...value, cooldown_minutes: Number(e.target.value) })} /></label>
    <p className="quiet">{t('Saving starts a new rule revision for future observations. No historical alerts are generated.')}</p>
    {mutation.error && <p role="alert" className="error">{t(mutation.error.message)}</p>}
    <div className="watch-actions"><button className="primary" disabled={mutation.isPending || !value.name.trim()}>{t('Save rule')}</button><button type="button" onClick={done}>{t('Cancel')}</button></div>
  </form>
}
