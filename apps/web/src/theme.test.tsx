import { act, fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'

const changes = new Set<() => void>()
const media = { matches: false, addEventListener: (_: string, callback: () => void) => changes.add(callback), removeEventListener: (_: string, callback: () => void) => changes.delete(callback) }
vi.spyOn(window, 'matchMedia').mockReturnValue(media as unknown as MediaQueryList)
const { setThemePreference } = await import('./theme')
const { default: ThemeSwitch } = await import('./ThemeSwitch')

beforeEach(() => { media.matches = false; setThemePreference('system') })
function systemDark(matches: boolean) { act(() => { media.matches = matches; changes.forEach((callback) => callback()) }) }

it('defaults to dark for a new visitor even when the OS is light', () => {
  localStorage.removeItem('quanthecy.theme')
  render(<ThemeSwitch />)
  expect(screen.getByRole('combobox')).toHaveValue('dark')
  expect(document.documentElement.dataset.theme).toBe('dark')
})

it('follows OS changes only when the system option is selected', () => {
  render(<ThemeSwitch />)
  expect(document.documentElement.dataset.theme).toBe('light')
  systemDark(true)
  expect(document.documentElement.dataset.theme).toBe('dark')
  fireEvent.change(screen.getByRole('combobox', { name: 'Color theme' }), { target: { value: 'light' } })
  systemDark(false)
  systemDark(true)
  expect(document.documentElement.dataset.theme).toBe('light')
  expect(localStorage.getItem('quanthecy.theme')).toBe('light')
  fireEvent.change(screen.getByRole('combobox'), { target: { value: 'system' } })
  expect(document.documentElement.dataset.theme).toBe('dark')
})

it('restores a stored choice on remount and synchronizes changes from other tabs', () => {
  const mounted = render(<ThemeSwitch />)
  fireEvent.change(screen.getByRole('combobox'), { target: { value: 'dark' } })
  mounted.unmount()
  render(<ThemeSwitch />)
  expect(screen.getByRole('combobox')).toHaveValue('dark')
  act(() => window.dispatchEvent(new StorageEvent('storage', { key: 'quanthecy.theme', newValue: 'light' })))
  expect(screen.getByRole('combobox')).toHaveValue('light')
  expect(document.documentElement.dataset.theme).toBe('light')
  act(() => window.dispatchEvent(new StorageEvent('storage', { key: 'quanthecy.theme', newValue: 'invalid' })))
  expect(screen.getByRole('combobox')).toHaveValue('system')
  expect(document.documentElement.style.colorScheme).toBe('light')
})

it('still switches when browser storage is unavailable', () => {
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked') })
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked') })
  render(<ThemeSwitch />)
  fireEvent.change(screen.getByRole('combobox'), { target: { value: 'dark' } })
  expect(screen.getByRole('combobox')).toHaveValue('dark')
  expect(document.documentElement.dataset.theme).toBe('dark')
})
