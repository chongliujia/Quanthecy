import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api, type Organization } from './api'
import { t } from './i18n'
import type { Watchlist } from './watchlistTypes'
import TerminalDialog from './TerminalDialog'
import { useWatchlists } from './watchlistQueries'
import { ErrorNotice } from './ResearchUI'

export function WatchMarketButton({ userId, organization, marketId }: { userId: string; organization?: Organization; marketId: string }) {
  const [open, setOpen] = useState(false)
  if (!organization || organization.role === 'VIEWER') return null
  return <><button className="watch-market-button" onClick={() => setOpen(true)}>{t('☆ Watch market')}</button>
    <TerminalDialog open={open} onClose={() => setOpen(false)} title={t('Add to watchlist')} className="watch-dialog">
      <AddMarket key={`${organization.id}-${marketId}`} userId={userId} organizationId={organization.id} marketId={marketId} close={() => setOpen(false)} />
    </TerminalDialog></>
}

function AddMarket({ userId, organizationId, marketId, close }: { userId: string; organizationId: string; marketId: string; close: () => void }) {
  const client = useQueryClient()
  const lists = useWatchlists(userId, organizationId)
  const [chosen, setChosen] = useState('')
  const [name, setName] = useState('')
  const [createNew, setCreateNew] = useState(false)
  const creating = createNew || lists.data?.length === 0
  const selected = chosen || lists.data?.[0]?.id || ''
  const mutation = useMutation({ mutationFn: async () => {
    let id = selected
    if (creating) {
      const list = await api<Watchlist>(`/organizations/${organizationId}/watchlists`, 'POST', { name })
      id = list.id
      // If adding fails, the newly created list remains selectable for an idempotent retry.
      client.setQueryData<Watchlist[]>(['watchlists', userId, organizationId], current => [...(current ?? []), list])
      setChosen(id); setCreateNew(false)
    }
    await api(`/organizations/${organizationId}/watchlists/${id}/items`, 'POST', { market_id: marketId })
  }, onSuccess: async () => {
    await Promise.all([client.invalidateQueries({ queryKey: ['watchlists', userId, organizationId] }), client.invalidateQueries({ queryKey: ['watchlist', userId, organizationId] })])
    close()
  } })
  return <form className="watch-form" onSubmit={event => { event.preventDefault(); mutation.mutate() }}>
    <p>{t('Watchlists follow saved markets. Adding a market does not change collection coverage.')}</p>
    {lists.isPending && <p role="status">{t('Loading watchlists…')}</p>}
    {lists.error && <ErrorNotice error={lists.error} retry={() => void lists.refetch()} />}
    {lists.data && <>{!creating ? <label>{t('Watchlist')}<select value={selected} onChange={e => setChosen(e.target.value)}>{lists.data.map(list => <option key={list.id} value={list.id}>{list.name}</option>)}</select></label>
      : <label>{t('Watchlist name')}<input value={name} onChange={e => setName(e.target.value)} maxLength={80} required /></label>}
      {!!lists.data.length && <button type="button" className="text-button" onClick={() => setCreateNew(!createNew)}>{creating ? t('Use existing watchlist') : t('Create another watchlist')}</button>}
      <button className="primary" disabled={mutation.isPending || (creating ? !name.trim() : !selected)}>{mutation.isPending ? t('Saving…') : t('Add market')}</button></>}
    {mutation.error && <p className="error" role="alert">{t(mutation.error.message)}</p>}
  </form>
}
