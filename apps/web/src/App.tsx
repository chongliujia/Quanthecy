import { useLanguage, setLanguage, t } from './i18n'
import { lazy, Suspense, useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, ApiError, type User, type Organization, type Member } from './api'
import NavIcon from './NavIcon'
import CollectionStatus from './CollectionStatus'
import ThemeSwitch from './ThemeSwitch'
import { useLayoutPreference } from './terminalLayout'
import { useRoute, navigate } from './navigation'
import { ResearchOverview, ComparisonList, ComparisonView, EvidenceList, EvidenceView, SignalFeed } from './ResearchPages'
const EventPages = lazy(() => import('./EventPages'))
const ModelSettings = lazy(() => import('./ModelSettings'))
const MarketExplorer = lazy(() => import('./MarketExplorer'))

function AuthForm() {
  const client = useQueryClient()
  const [register, setRegister] = useState(false)
  const mutation = useMutation({
    mutationFn: (credentials: { email: string; password: string }) =>
      api<User>(register ? '/auth/register' : '/auth/login', 'POST', credentials),
    onSuccess: async (user) => { await client.cancelQueries(); client.removeQueries({ predicate: (query) => query.queryKey[0] !== 'me' }); client.setQueryData(['me'], user) },
  })
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const values = new FormData(event.currentTarget)
    mutation.mutate({ email: String(values.get('email')), password: String(values.get('password')) })
  }
  return <section className="auth-layout">
    <div className="intro"><span className="eyebrow">{t("PREDICTION-MARKET RESEARCH")}</span>
      <h1>{t("A clearer view of")}<br />{t("what markets believe.")}</h1>
      <p>{t("A shared workspace for your questions, evidence, and research.")}</p>
      <div className="research-topics"><span>{t("Market activity")}</span><span>{t("Cross-market comparisons")}</span><span>{t("News & events")}</span></div>
    </div>
    <form className="panel auth-form" onSubmit={submit}>
      <h2>{register ? t("Create your workspace") : t("Welcome back")}</h2>
      <p>{register ? t("Start with a personal workspace. Teams can come later.") : t("Sign in to your research workspace.")}</p>
      <label htmlFor="email">{t("Email")}</label>
      <input id="email" name="email" type="email" autoComplete="email" maxLength={254} required />
      <label htmlFor="password">{t("Password")}</label>
      <input id="password" name="password" type="password" autoComplete={register ? 'new-password' : 'current-password'} minLength={register ? 8 : 1} maxLength={128} required />
      {register && <small>{t("Use at least 8 characters and avoid common passwords.")}</small>}
      {mutation.error && <p role="alert" className="error">{t(mutation.error.message)}</p>}
      <button className="primary" disabled={mutation.isPending}>{mutation.isPending ? t("Please wait…") : register ? t("Create account") : t("Sign in")}</button>
      <button type="button" className="text-button" disabled={mutation.isPending} onClick={() => { setRegister(!register); mutation.reset() }}>
        {register ? t("Already have an account? Sign in") : t("New to Quanthecy? Create an account")}
      </button>
    </form>
  </section>
}

function Workspace({ user }: { user: User }) {
  const client = useQueryClient()
  const [selected, setSelected] = useState('')
  const [name, setName] = useState('')
  const [showCreate, setShowCreate] = useState(false)
  const route = useRoute()
  const [navCollapsed, setNavCollapsed] = useLayoutPreference(`quanthecy.nav.${user.id}`, true, (value): value is boolean => typeof value === 'boolean')
  const cutoff = route.params.get('cutoff') ?? ''
  const navigation = [['overview', t("Research overview"), '01'], ['markets', t("Market explorer"), '02'], ['signals', t("Signal feed"), '03'], ['comparisons', t("Cross-platform"), '04'], ['evidence', t("News & evidence"), '05'], ['events', t('Event dossiers'), '08'], ['workspace', t("Workspace & members"), '06'], ['model-settings', t("Model settings"), '07']]
  const heading = navigation.find(([path]) => path === route.page)?.[1] ?? t("Page not found")
  const organizations = useQuery({ queryKey: ['organizations', user.id], queryFn: () => api<Organization[]>('/organizations?limit=100') })
  const active = organizations.data?.find((org) => org.id === selected) ?? organizations.data?.[0]
  const members = useQuery({ queryKey: ['members', user.id, active?.id], enabled: !!active,
    queryFn: () => api<Member[]>(`/organizations/${active!.id}/members?limit=100`) })
  const create = useMutation({ mutationFn: () => api<Organization>('/organizations', 'POST', { name }),
    onSuccess: async (org) => { setSelected(org.id); setName(''); setShowCreate(false); await client.invalidateQueries({ queryKey: ['organizations', user.id] }) } })
  const logout = useMutation({ mutationFn: () => api('/auth/logout', 'POST'),
    onSuccess: async () => { await client.cancelQueries(); client.removeQueries({ predicate: (query) => query.queryKey[0] !== 'me' }); client.setQueryData(['me'], null) } })
  return <div className={`workspace-layout ${route.page === 'markets' && route.id ? 'terminal-mode' : ''} ${navCollapsed ? 'nav-collapsed' : ''} ${route.page === 'model-settings' ? 'settings-mode' : ''}`}>
    <aside><button className="nav-toggle" aria-label={navCollapsed ? t("Expand navigation") : t("Collapse navigation")} aria-expanded={!navCollapsed} onClick={() => setNavCollapsed(!navCollapsed)}>{navCollapsed ? '☰' : '‹'}<span>{t("Workspace")}</span></button><span className="eyebrow">{t("YOUR WORKSPACE")}</span>
      <label className="sr-only" htmlFor="organization">{t("Active workspace")}</label>
      <select id="organization" value={active?.id ?? ''} onChange={(event) => setSelected(event.target.value)} disabled={!organizations.data?.length}>
        {!organizations.data?.length && <option value="">{t("No workspace selected")}</option>}
        {organizations.data?.map((org) => <option key={org.id} value={org.id}>{org.name}</option>)}
      </select>
      <button className="secondary" onClick={() => setShowCreate(!showCreate)}>{t("+ New workspace")}</button>
      <nav aria-label={t("Research navigation")}>{navigation.map(([path, label]) => <a key={path} title={label} aria-label={label} href={`#/${path}`} aria-current={route.page === path ? 'page' : undefined} className={route.page === path ? 'nav-current' : 'nav-link'}><span className="nav-icon"><NavIcon page={path} /></span><span className="nav-label">{label}</span></a>)}</nav>
      <div className="sidebar-focus"><span className="eyebrow">{t("CURRENT RESEARCH")}</span><p>{t("Macro & rates")}</p><small>{t("Market data → rules → evidence")}</small></div>
      <div className="account"><span>{user.email}</span><button className="text-button" onClick={() => logout.mutate()} disabled={logout.isPending}>{t("Sign out")}</button></div>
      {logout.error && <p role="alert" className="error">{t(logout.error.message)}</p>}
    </aside>
    <main id="main-content" tabIndex={-1} className="workspace-content">
      <div className="page-heading"><div><span className="eyebrow">{active?.name ?? t("YOUR RESEARCH WORKSPACE")}</span><h1>{t(heading)}</h1></div>{active && <span className="badge">{t(active.role)}</span>}</div>
      {organizations.isPending && <p role="status">{t("Loading workspaces…")}</p>}
      {organizations.error && <div role="alert" className="error">{t(organizations.error.message)} <button onClick={() => void organizations.refetch()}>{t("Retry")}</button></div>}
      {showCreate && <form className="panel create-form" onSubmit={(event) => { event.preventDefault(); create.mutate() }}>
        <label htmlFor="workspace-name">{t("Workspace name")}</label>
        <input id="workspace-name" value={name} onChange={(event) => setName(event.target.value)} maxLength={120} required />
        <button className="primary" disabled={create.isPending || !name.trim()}>{t("Create workspace")}</button>
        {create.error && <p role="alert" className="error">{t(create.error.message)}</p>}
      </form>}
      {organizations.data?.length === 0 && <p>{t("Create a workspace to begin organizing your research.")}</p>}
      {route.page === 'overview' && <ResearchOverview userId={user.id} />}
      {route.page === 'markets' && <Suspense fallback={<p role="status">{t("Loading market explorer…")}</p>}><MarketExplorer organization={active} cutoff={cutoff} userId={user.id} selectedId={route.id ?? null} onSelect={(id) => navigate(id ? `/markets/${id}` : '/markets')} /></Suspense>}
      {route.page === 'model-settings' && <Suspense fallback={<p role="status">{t("Loading model settings…")}</p>}><ModelSettings key={active?.id} userId={user.id} organization={active} /></Suspense>}
      {route.page === 'events' && <Suspense fallback={<p role="status">{t('Loading event research…')}</p>}><EventPages key={`${route.id}-${cutoff}`} userId={user.id} slug={route.id} cutoff={cutoff} /></Suspense>}
      {route.page === 'signals' && <SignalFeed userId={user.id} />}
      {route.page === 'comparisons' && (route.id ? <ComparisonView key={route.id} userId={user.id} id={route.id} cutoff={cutoff} /> : <ComparisonList userId={user.id} cutoff={cutoff} />)}
      {route.page === 'evidence' && (route.id ? <EvidenceView key={route.id} userId={user.id} id={route.id} cutoff={cutoff} /> : <EvidenceList key={cutoff} userId={user.id} cutoff={cutoff} />)}
      {!navigation.some(([path]) => path === route.page) && <section className="panel"><p>{t("This research page does not exist.")}</p><a className="text-button" href="#/overview">{t("Return to overview →")}</a></section>}
      {active && route.page === 'workspace' && <>
        <section className="panel"><span className="eyebrow">{t("ACTIVE WORKSPACE")}</span><h2>{active.name}</h2><p>{t("Your role is")} {t(active.role)}{t(". Market observations and official evidence are shared research data; memberships belong to this workspace.")}</p></section>
        <section className="panel members"><h2>{t("Workspace members")}</h2><p>{t("Access is managed separately for each workspace.")}</p>
          {members.isPending && <p role="status">{t("Loading members…")}</p>}
          {members.error && <div role="alert" className="error">{t(members.error.message)} <button onClick={() => void members.refetch()}>{t("Retry")}</button></div>}
          {members.data && <ul>{members.data.map((member) => <li key={member.id}><span>{member.email}{member.user_id === user.id && <small> {t("· You")}</small>}</span><span className="role">{t(member.role)}</span></li>)}</ul>}
        </section>
      </>}
    </main>
  </div>
}

export default function App() {
  const language = useLanguage()
  const me = useQuery({ queryKey: ['me'], queryFn: async () => {
    try { return await api<User>('/me') } catch (error) {
      if (error instanceof ApiError && error.status === 401) return null
      throw error
    }
  }, retry: false })
  return <><button className="skip-link" onClick={() => document.getElementById('main-content')?.focus()}>{t("Skip to content")}</button><header className="topbar"><a className="brand" href="#/overview" aria-label={t("Quanthecy home")}><span className="brand-mark">{t("Q")}</span>{t("Quanthecy")}</a>{me.data ? <CollectionStatus userId={me.data.id} /> : <span className="topbar-note">{t("PREDICTION MARKET INTELLIGENCE")}</span>}<div className="topbar-actions"><ThemeSwitch /><div className="language-switch" role="group" aria-label={t("Language / 语言")}><button lang="zh-CN" aria-pressed={language === 'zh'} onClick={() => setLanguage('zh')}>中文</button><button lang="en" aria-pressed={language === 'en'} onClick={() => setLanguage('en')}>{"English"}</button></div></div></header>
    {me.isPending ? <p className="page-message" role="status">{t("Loading your workspace…")}</p>
      : me.error ? <div className="page-message" role="alert"><h1>{t("Unable to reach your workspace")}</h1><p>{t(me.error.message)}</p><button className="primary" onClick={() => void me.refetch()}>{t("Try again")}</button></div>
        : me.data ? <Workspace user={me.data} /> : <AuthForm />}
  </>
}
