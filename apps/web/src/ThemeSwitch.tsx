import { t } from './i18n'
import { setThemePreference, useTheme, type ThemePreference } from './theme'

export default function ThemeSwitch() {
  const { preference, theme } = useTheme()
  return <label className="theme-switch">
    <svg aria-hidden="true" width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      {theme === 'light' ? <><circle cx="12" cy="12" r="4" /><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.4 1.4m11.2 11.2L19 19M5 19l1.4-1.4M17.6 6.4 19 5" /></> : <path d="M20.8 13A9 9 0 0 1 11 3.2 9 9 0 1 0 20.8 13Z" />}
    </svg>
    <span className="sr-only">{t('Color theme')}</span>
    <select value={preference} onChange={(event) => setThemePreference(event.target.value as ThemePreference)}>
      <option value="system">{t('System theme')}</option>
      <option value="light">{t('Light mode')}</option>
      <option value="dark">{t('Dark mode')}</option>
    </select>
  </label>
}
