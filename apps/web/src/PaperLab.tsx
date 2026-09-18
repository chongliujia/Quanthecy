import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, type Organization } from './api'
import { t, locale, useLanguage } from './i18n'
import PaperEquityChart from './PaperEquityChart'
import PaperReviewPanel from './PaperReviewPanel'
import TerminalDialog from './TerminalDialog'
import { paperReasons, strategyNames, type PaperLabData, type PaperCandidate, type PaperOrderDetail } from './paperTypes'
import './paper.css'
import './assistants.css'
import AssistantBuilder from './AssistantBuilder'
import AssistantRuns from './AssistantRuns'
import AssistantComparison from './AssistantComparison'

function cash(value: string | number | null | undefined) { return value == null ? '—' : Number(value).toLocaleString(locale(), { minimumFractionDigits: 2, maximumFractionDigits: 2 }) }
function time(value: string | null | undefined) { return value ? new Date(value).toLocaleString(locale()) : '—' }
function reason(value: string) { return t(paperReasons[value] ?? value) }

export default function PaperLab({ userId, organization }: { userId: string; organization?: Organization }) {
  useLanguage()
  if (!organization) return <p>{t('Select a workspace to use paper trading.')}</p>
  return <LabWorkspace key={organization.id} userId={userId} organization={organization} />
}

function LabWorkspace({ userId, organization }: { userId: string; organization: Organization }) {
  const [tab, setTab] = useState('experiments')
  const [version, setVersion] = useState<string | null>(null)
  const [builderOpened, setBuilderOpened] = useState(false)
  return <div className={`paper-lab ${tab === 'assistants' ? 'paper-studio-active' : ''}`}><nav className="directory-tabs" aria-label={t('Paper laboratory sections')}>{[['experiments', 'Experiment comparison'], ['assistants', 'My assistants'], ['runs', 'Run history']].map(([id, title]) => <button key={id} aria-pressed={tab === id} onClick={() => { setTab(id); if (id === 'assistants') setBuilderOpened(true) }}>{t(title)}</button>)}</nav>
    {tab === 'experiments' && <WorkspacePaper userId={userId} organization={organization} preselected={version} />}
    {builderOpened && <div hidden={tab !== 'assistants'}><AssistantBuilder userId={userId} organization={organization} onCompare={id => { setVersion(id); setTab('experiments') }} /></div>}
    {tab === 'runs' && <AssistantRuns userId={userId} organizationId={organization.id} writable={organization.role !== 'VIEWER'} />}
  </div>
}

function WorkspacePaper({ userId, organization, preselected }: { userId: string; organization: Organization; preselected: string | null }) {
  const client = useQueryClient()
  const path = `/organizations/${organization.id}/paper`
  const [experimentId, setExperimentId] = useState<string | null>(null)
  const [reviewLimit, setReviewLimit] = useState('10')
  const key = ['paper', userId, organization.id, experimentId ?? 'latest']
  const lab = useQuery({ queryKey: key, queryFn: () => api<PaperLabData | null>(`${path}${experimentId ? `?experiment_id=${experimentId}` : ''}`), refetchInterval: 10000 })
  const candidates = useQuery({ queryKey: [...key, 'candidates'], queryFn: () => api<PaperCandidate[]>(`${path}/candidates`), enabled: lab.data === null })
  const [selected, setSelected] = useState<string[] | null>(null)
  const [capital, setCapital] = useState('10000')
  const [platform, setPlatform] = useState('polymarket')
  const [orderId, setOrderId] = useState<string | null>(null)
  const ids = selected ?? candidates.data?.map(c => c.id) ?? []
  const writable = organization.role !== 'VIEWER'
  const create = useMutation({ mutationFn: () => api<PaperLabData>(path, 'POST', { name: t('Paper trading experiment'), market_ids: ids, initial_cash: capital, version: 'paper-v2', daily_review_limit: Number(reviewLimit) }), onSuccess: data => client.setQueryData(key, data) })
  const toggle = useMutation({ mutationFn: (running: boolean) => api<PaperLabData>(path, 'PATCH', { running, experiment_id: lab.data?.id }), onSuccess: data => client.setQueryData(key, data) })
  const upgrade = useMutation({ mutationFn: () => api<PaperLabData>(`${path}/upgrade`, 'POST', { daily_review_limit: Number(reviewLimit) }), onSuccess: data => { setExperimentId(null); client.setQueryData(['paper', userId, organization.id, 'latest'], data); void client.invalidateQueries({ queryKey: ['paper', userId, organization.id] }) } })
  const detail = useQuery({ queryKey: [...key, 'order', orderId], queryFn: () => api<PaperOrderDetail>(`${path}/orders/${orderId}`), enabled: !!orderId })
  const data = lab.data
  const availablePlatforms = [...new Set(data?.accounts.map(a => a.platform) ?? [])]
  const activePlatform = availablePlatforms.includes(platform) ? platform : availablePlatforms[0]
  const accounts = data?.accounts.filter(a => a.platform === activePlatform) ?? []
  const accountIds = new Set(accounts.map(a => a.id))
  const accountLabel = (id: string) => { const account = data?.accounts.find(a => a.id === id); return account?.label || t(strategyNames[account?.strategy ?? ''] ?? '') }
  const delayed = !!data && (!data.checked_at || Date.now() - Date.parse(data.checked_at) > 90000 || !!data.error_code)
  return <div className="paper-lab">
    <div className="paper-intro"><div><span className="eyebrow">{t('VIRTUAL CAPITAL · REAL MARKET DATA')}</span><h2>{t('Paper trading lab')}</h2><p>{t('Build research assistants and compare their simulated decisions, fills and costs.')}</p></div><span className="badge">{t('Simulation only')}</span></div>
    <p className="paper-notice">{t('No real orders. Fills use later order-book snapshots, at most 10% of visible depth, observed fees and 10 bps of adverse slippage. Results are estimates.')}</p>
    {lab.isPending && <p role="status">{t('Loading paper accounts…')}</p>}
    {[lab.error, candidates.error, create.error, toggle.error, upgrade.error].filter(Boolean).map((error, i) => <p className="error" role="alert" key={i}>{t(error!.message)}</p>)}
    {lab.error && <button onClick={() => void lab.refetch()}>{t('Retry')}</button>}
    {data !== undefined && data?.is_latest !== false && !lab.error && <AssistantComparison key={preselected ?? 'comparison'} userId={userId} organization={organization} current={data} preselected={preselected} onCreated={result => { setExperimentId(null); client.setQueryData(['paper', userId, organization.id, 'latest'], result); void client.invalidateQueries({ queryKey: ['paper', userId, organization.id] }) }} />}
    {data === null && <section className="panel paper-setup"><h3>{t('Start a prospective experiment')}</h3><p>{t('Each platform gets three independent accounts: momentum, momentum with an Agent risk filter, and buy-and-hold. A cash benchmark is also shown.')}</p>
      <label>{t('Initial virtual capital per account')}<input aria-label={t('Initial virtual capital per account')} type="number" min="100" max="1000000" step="100" value={capital} onChange={e => setCapital(e.target.value)} disabled={!writable} /></label>
      <label>{t('Automatic reviews per day')}<input type="number" min="1" max="20" value={reviewLimit} disabled={!writable} onChange={e => setReviewLimit(e.target.value)} /></label><p>{t('Eligible signals automatically request one model review. Workspace model limits also apply; missing configuration prevents calls.')}</p>
      <p>{t('Select up to 20 markets. The universe and strategy rules are frozen when the experiment starts.')}</p>
      {candidates.isPending && <p role="status">{t('Loading eligible markets…')}</p>}
      <div className="paper-candidates">{candidates.data?.map(m => <label key={m.id}><input type="checkbox" checked={ids.includes(m.id)} disabled={!writable} onChange={e => setSelected(e.target.checked ? [...ids, m.id] : ids.filter(id => id !== m.id))} /><span>{m.title}<small>{m.platform} · {cash(m.bid * 100)} / {cash(m.ask * 100)} ¢</small></span></label>)}</div>
      {candidates.data?.length === 0 && <p>{t('No eligible priority markets. Enable collection and wait for fresh two-sided quotes.')}</p>}
      <button className="primary" disabled={!writable || create.isPending || ids.length === 0 || ids.length > 20 || Number(capital) < 100 || Number(capital) > 1000000 || !Number.isInteger(Number(reviewLimit)) || Number(reviewLimit) < 1 || Number(reviewLimit) > 20} onClick={() => create.mutate()}>{create.isPending ? t('Starting…') : t('Start paper experiment')}</button>
      {!writable && <p>{t('Viewer access is read-only.')}</p>}
    </section>}
    {data && <>
      {data.experiments && <label className="paper-history">{t('Experiment history')}<select aria-label={t('Experiment history')} value={experimentId ?? ''} onChange={e => { setExperimentId(e.target.value || null); setOrderId(null) }}><option value="">{t('Latest experiment')}</option>{data.experiments.map(e => <option key={e.id} value={e.id}>{e.version} · {time(e.created_at)}</option>)}</select></label>}
      {data.is_latest === false && <p className="paper-notice">{t('Historical experiment: new entries are stopped. Existing positions continue valuation and verified settlement.')}</p>}
      {data.version === 'paper-v1' && data.is_latest !== false && <section className="panel paper-upgrade"><h3>{t('Enable automatic entry reviews')}</h3><p>{t('Start v2 with the same markets and initial capital. The old experiment stops new entries and keeps its complete ledger and positions.')}</p><label>{t('Automatic reviews per day')}<input type="number" min="1" max="20" value={reviewLimit} disabled={!writable} onChange={e => setReviewLimit(e.target.value)} /></label><button disabled={!writable || upgrade.isPending || !Number.isInteger(Number(reviewLimit)) || Number(reviewLimit) < 1 || Number(reviewLimit) > 20} onClick={() => upgrade.mutate()}>{t('Start v2 and preserve v1')}</button></section>}

      <section className="paper-toolbar"><div><strong>{data.name}</strong><small>{data.market_count} {t('markets')} · {t('Started')} {time(data.created_at)}</small></div><span className={`badge ${delayed ? 'paper-warning' : ''}`}>{delayed ? t('Processing delayed') : data.running ? t('Running') : t('Paused')}</span><button disabled={!writable || toggle.isPending || data.is_latest === false} onClick={() => toggle.mutate(!data.running)}>{data.running ? t('Pause experiment') : t('Resume experiment')}</button></section>
      {delayed && <p role="status" className="paper-notice">{t('The worker has not completed a recent cycle. Displayed balances are historical; inspect the last update time.')}</p>}
      {data.review_summary && <PaperReviewPanel key={data.id} userId={userId} organizationId={organization.id} experiment={data} />}
      <div className="directory-tabs" role="group" aria-label={t('Platform')}>{availablePlatforms.map(p => <button key={p} aria-pressed={activePlatform === p} onClick={() => setPlatform(p)}>{p === 'polymarket' ? 'Polymarket' : 'Kalshi'}</button>)}</div>
      <p className="quiet">{t('Platform balances are separate. Every strategy starts with the same virtual capital and market universe.')}</p>
      <div className="paper-accounts">{accounts.map(a => <article className="panel paper-account" key={a.id}><h3>{a.label || t(strategyNames[a.strategy])}</h3><span className="quiet">{t('Estimated liquidation equity')}</span><strong className="paper-equity">{cash(a.equity)}</strong><span className={a.equity != null && Number(a.equity) < Number(a.initial_cash) ? 'paper-loss' : 'paper-gain'}>{a.equity == null ? t('Valuation unavailable') : `${cash(Number(a.equity) - Number(a.initial_cash))} (${((Number(a.equity) / Number(a.initial_cash) - 1) * 100).toFixed(2)}%)`}</span>
        <dl><dt>{t('Available cash')}</dt><dd>{cash(Number(a.cash) - Number(a.reserved_cash))}</dd><dt>{t('Realized P&L')}</dt><dd>{cash(a.realized_pnl)}</dd><dt>{t('Unrealized P&L')}</dt><dd>{cash(a.unrealized_pnl)}</dd><dt>{t('Trading fees')}</dt><dd>{cash(a.fees)}</dd><dt>{t('Maximum drawdown')}</dt><dd>{(Number(a.max_drawdown) * 100).toFixed(2)}%</dd><dt>{t('Orders / fill records')}</dt><dd>{a.orders} / {a.fills}</dd></dl>
        {a.review_summary && <dl><dt>{t('Participation in matched baseline entries')}</dt><dd>{a.review_summary.participation == null ? '—' : `${(a.review_summary.participation * 100).toFixed(1)}%`}</dd><dt>{t('Average signal-to-report time')}</dt><dd>{a.review_summary.average_latency_seconds == null ? '—' : `${a.review_summary.average_latency_seconds.toFixed(1)} s`}</dd><dt>{t('Provider calls attempted')}</dt><dd>{a.review_summary.provider_calls}</dd><dt>{t('Input / output tokens reported')}</dt><dd>{a.review_summary.prompt_tokens} / {a.review_summary.completion_tokens}</dd></dl>}
        <small>{t('Valued at')} {time(a.equity_at)}{a.unpriced_positions > 0 && ` · ${a.unpriced_positions} ${t('positions awaiting valuation')}`}</small></article>)}</div>
      <section className="panel"><h3>{t('Equity comparison')}</h3><PaperEquityChart accounts={accounts} /><p className="quiet">{t('Latest 720 equity samples. Gaps mean a complete liquidation estimate was unavailable; unpriced positions are not valued at zero.')}</p></section>
      <details className="panel paper-rules"><summary>{t('Strategy rules and assumptions')}</summary><p>{t('Momentum buys YES after a valid 15m rise of at least 2 pp, then exits after one hour or non-positive momentum. Decisions are evaluated every five minutes. Buy-and-hold waits for verified settlement.')}</p>{data.version !== 'paper-v1' ? <><p>{t('The Agent account uses dedicated ALLOW, REJECT or WAIT reviews. General cautions are separated from blocking risks. Entry signals, price drift, contract rules and capital limits are checked again after each review.')}</p>{data.version === 'paper-v3' && <p>{t('Each assistant account uses its frozen published workflow. Model calls share the workspace queue and allowance. Failed or expired reviews never bypass entry checks.')}</p>}<p>{t('One review per candidate, a 15-minute market cooldown, a 10-minute validity window and at most 2,048 output tokens per call. Price drift above 2 cents invalidates the review. Calls share the workspace daily quota.')}</p></> : <><p>{t('Each order uses at most 1% of initial capital; exposure to one exchange event is capped at 2%. The Agent variant applies the same rules and accepts only a completed report from the last 24h with WATCH or INVESTIGATE and no risk flags. Confidence is not used as a probability.')}</p><p>{t('Agent reports are reused from this workspace. This experiment does not automatically request paid model calls. Missing reports cause abstention.')}</p></>}<p>{t('Paused experiments cancel pending orders but retain positions, valuations and settlement checks. Unsupported or unverified settlement stays unresolved.')}</p></details>
      <section className="panel table-scroll"><h3>{t('Open simulated positions')}</h3><table><thead><tr><th>{t('Market')}</th><th>{t('Strategy')}</th><th>{t('Shares')}</th><th>{t('Cost including entry fees')}</th></tr></thead><tbody>{data.positions.filter(p => accountIds.has(p.account_id)).map(p => <tr key={p.id}><td><a href={`#/markets/${p.market_id}`}>{p.title}</a></td><td>{accountLabel(p.account_id)}</td><td>{cash(p.quantity)}</td><td>{cash(p.cost_basis)}</td></tr>)}</tbody></table>{!data.positions.some(p => accountIds.has(p.account_id)) && <p>{t('No open simulated positions.')}</p>}</section>
      <section className="panel table-scroll"><h3>{t('Recent simulated orders')}</h3><table><thead><tr><th>{t('Market')}</th><th>{t('Strategy')}</th><th>{t('Side / status')}</th><th>{t('Filled / requested')}</th><th>{t('Details')}</th></tr></thead><tbody>{data.recent_orders.filter(o => accountIds.has(o.account_id)).map(o => <tr key={o.id}><td>{o.title}<small>{time(o.created_at)}</small></td><td>{accountLabel(o.account_id)}</td><td>{t(o.side)} · {t(o.status)}<small>{reason(o.reason)}</small></td><td>{cash(o.filled_quantity)} / {cash(o.quantity)}</td><td><button onClick={() => setOrderId(o.id)}>{t('Inspect simulated fill')}</button></td></tr>)}</tbody></table>{!data.recent_orders.some(o => accountIds.has(o.account_id)) && <p>{t('No orders yet. Waiting is recorded and does not imply a worker failure.')}</p>}</section>
      <section className="panel table-scroll"><h3>{t('Recent decisions and abstentions')}</h3><table><thead><tr><th>{t('Market')}</th><th>{t('Strategy')}</th><th>{t('Decision')}</th><th>{t('Reason')}</th></tr></thead><tbody>{data.recent_decisions.filter(d => accountIds.has(d.account_id)).map(d => <tr key={d.id}><td>{d.title}<small>{time(d.created_at)}</small></td><td>{accountLabel(d.account_id)}</td><td>{t(d.action)}</td><td>{reason(d.reason)}</td></tr>)}</tbody></table></section>
      <p className="quiet">{t('Worker updated')} {time(data.checked_at)} · {t('Order books updated')} {time(data.collector.checked_at)} · {data.collector.successful ?? 0}/{data.collector.markets ?? data.market_count} {t('book snapshots succeeded')}</p>
    </>}
    <TerminalDialog open={!!orderId} onClose={() => setOrderId(null)} title={t('Simulated fill details')} className="paper-dialog">{detail.isPending && <p role="status">{t('Loading…')}</p>}{detail.error && <p role="alert">{t(detail.error.message)}</p>}{detail.data && <><p>{detail.data.title}</p><p>{t('Decision at')} {time(detail.data.created_at)}<br />{t('Execution book at')} {time(detail.data.execution_quote?.received_at)}</p><p>{t('Replay check')}: {detail.data.replay_matches == null ? t('Awaiting execution') : detail.data.replay_matches ? t('Matches the frozen inputs') : t('Replay mismatch')}</p><table><thead><tr><th>{t('Shares')}</th><th>{t('Price')}</th><th>{t('Fee')}</th><th>{t('Cash change')}</th></tr></thead><tbody>{detail.data.fills.map((f, i) => <tr key={i}><td>{cash(f.quantity)}</td><td>{Number(f.price).toFixed(6)}</td><td>{Number(f.fee).toFixed(6)}</td><td>{cash(f.cash_delta)}</td></tr>)}</tbody></table><details><summary>{t('Frozen decision and execution evidence')}</summary><pre>{JSON.stringify({ inputs: detail.data.inputs, execution: detail.data.execution_quote }, null, 2)}</pre></details></>}</TerminalDialog>
  </div>
}
