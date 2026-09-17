import { useState, type FormEvent } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import { locale, t, useLanguage } from './i18n'

type Entry = {
  id: string; platform: string; exchange_id: string; title: string; status: string
  volume_24h: number | null; volume_unit: string; last_seen_at: string; stale: boolean
  collection: string; has_history: boolean
}
type Page = { items: Entry[]; total: number; offset: number; limit: number }
const tierLabels: Record<string, string> = { priority: 'Priority collection', standard: 'Standard collection', history: 'Saved history', directory: 'Directory only' }

export default function MarketDirectory({ userId, onOpen }: { userId: string; onOpen: (id: string) => void }) {
  useLanguage()
  const [platform, setPlatform] = useState('')
  const [draft, setDraft] = useState('')
  const [search, setSearch] = useState('')
  const [offset, setOffset] = useState(0)
  const query = useQuery({ queryKey: ['market-directory', userId, platform, search, offset],
    queryFn: () => api<Page>(`/market-directory?limit=20&offset=${offset}&platform=${platform}&search=${encodeURIComponent(search)}`), refetchInterval: 30000 })
  function submit(e: FormEvent) { e.preventDefault(); setSearch(draft); setOffset(0) }
  return <>
    <p className="coverage-note">{t('Browse discovered markets. Directory entries do not include continuous price history until collection is enabled by an operator.')}</p>
    <div className="market-controls"><form onSubmit={submit}><label className="sr-only" htmlFor="directory-search">{t('Search directory')}</label><input id="directory-search" value={draft} onChange={e => setDraft(e.target.value)} maxLength={200} placeholder={t('Search titles or market IDs')} /><button>{t('Search')}</button></form>
      <label>{t('Platform')}<select value={platform} onChange={e => { setPlatform(e.target.value); setOffset(0) }}><option value="">{t('All platforms')}</option><option value="polymarket">Polymarket</option><option value="kalshi">Kalshi</option></select></label>
    </div>
    <p className="quiet">{t('Open-market discovery is paginated and may be incomplete. Activity is ranked within each exchange; volume units are different.')}</p>
    {query.isPending && <p role="status">{t('Loading directory…')}</p>}
    {query.error && <p role="alert">{t('Market directory is unavailable.')} <button onClick={() => void query.refetch()}>{t('Retry')}</button></p>}
    {query.data && <><p className="quiet">{query.data.total.toLocaleString(locale())} {t('discovered markets')}</p>
      <div className="panel table-scroll" tabIndex={0} role="region" aria-label={t('Market directory')}><table className="market-table"><thead><tr><th>{t('Market')}</th><th>{t('Collection coverage')}</th><th>{t('24h volume')}</th><th>{t('Metadata observed')}</th></tr></thead><tbody>
        {query.data.items.map(row => <tr key={row.id}><td>{row.has_history ? <button className="market-link" onClick={() => onOpen(row.id)}>{row.title}</button> : <strong>{row.title}</strong>}<small>{row.platform} · {row.exchange_id} · {t(row.status)}</small></td><td><span className="badge">{t(tierLabels[row.collection] ?? 'Directory only')}</span>{!row.has_history && <small>{t('Price history not collected yet')}</small>}</td><td>{row.volume_24h == null ? '—' : row.volume_24h.toLocaleString(locale(), { maximumFractionDigits: 0 })}<small>{t(row.volume_unit)}</small></td><td>{new Date(row.last_seen_at).toLocaleString(locale())}{row.stale && <small>{t('Metadata older than 24h')}</small>}</td></tr>)}
        {!query.data.items.length && <tr><td colSpan={4}>{t('No matching directory entries. Discovery must be enabled in the operations console.')}</td></tr>}
      </tbody></table></div>
      <div className="pagination"><button disabled={!offset} onClick={() => setOffset(Math.max(0, offset-20))}>{t('Previous')}</button><span>{query.data.total ? offset+1 : 0}–{Math.min(offset+20, query.data.total)} {t('of')} {query.data.total}</span><button disabled={offset+20 >= query.data.total} onClick={() => setOffset(offset+20)}>{t('Next')}</button></div>
    </>}
  </>
}
