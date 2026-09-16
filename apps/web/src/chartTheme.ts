import type { Theme } from './theme'

// Canvas charts need actual colors; CSS variables cannot be painted by ECharts.
const palettes = {
  dark: {
    text: '#dce6f4', muted: '#a9b4c7', grid: '#272c39', gridMinor: '#202632',
    surface: '#162130', border: '#334659', crosshair: '#75859d', pointer: '#344255',
    positive: '#50d6c5', line: '#38c9b1', negative: '#f47f88', warning: '#f0bd66',
    news: '#8dacf6', volume: '#3c827d', spread: '#b8a0ec', onAccent: '#0b151c',
    areaTop: '#38cdb038', areaBottom: '#38cdb000', zoom: '#121b27',
    zoomFill: '#41cbbb20', zoomLine: '#37676d', zoomArea: '#1b3f46', lastLine: '#50d6c570',
  },
  light: {
    text: '#24354b', muted: '#52657d', grid: '#dce4ee', gridMinor: '#e9eef5',
    surface: '#ffffff', border: '#cbd5e3', crosshair: '#728198', pointer: '#435875',
    positive: '#087f73', line: '#087f73', negative: '#c43c50', warning: '#a76a12',
    news: '#456cc0', volume: '#76a9a0', spread: '#8754b7', onAccent: '#ffffff',
    areaTop: '#0b9c8528', areaBottom: '#0b9c8500', zoom: '#f1f5fa',
    zoomFill: '#087f7320', zoomLine: '#6b9e96', zoomArea: '#cce8df', lastLine: '#087f7380',
  },
}
export function chartColors(theme: Theme) { return palettes[theme] }
