import { expect, it } from 'vitest'
import { change, changeTone, valueTone } from './format'

it.each([
  [0, '0.00 pp', ''], [.001, '+0.10 pp', 'positive'], [-.001, '-0.10 pp', 'negative'],
  [.000001, '0.00 pp', ''], [-.000001, '0.00 pp', ''],
  [null, 'Unavailable', ''], [NaN, 'Unavailable', ''],
] as const)('formats change %s with a matching display tone', (value, label, tone) => {
  expect(change(value)).toBe(label)
  expect(changeTone(value)).toBe(tone)
})
it('keeps stale changes and unavailable or unchanged equity neutral', () => {
  expect(changeTone(.05, true)).toBe('')
  expect(valueTone(null)).toBe('')
  expect(valueTone(0)).toBe('')
  expect(valueTone(-.00001)).toBe('')
  expect(valueTone(-23.51)).toBe('negative')
})
