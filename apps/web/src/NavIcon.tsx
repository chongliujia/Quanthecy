const shapes: Record<string, string> = {
  overview: 'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',
  markets: 'M3 3v18h18 M6 15l4-6 4 3 6-8',
  watchlists: 'M4 4h16v17l-8-4-8 4z M8 8h8 M8 12h5',
  signals: 'M2 12h4l3-8 6 16 3-8h4',
  comparisons: 'M4 7h16l-4-4 M20 17H4l4 4 M20 7l-4 4 M4 17l4-4',
  events: 'M4 5h16v16H4z M8 2v6 M16 2v6 M4 10h16 M8 14h3 M14 14h3',
  evidence: 'M4 3h16v18H4z M8 7h8 M8 11h8 M8 15h5',
  workspace: 'M9 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8 M2 21v-3a7 7 0 0 1 14 0v3 M17 4a4 4 0 0 1 0 7 M19 14a5 5 0 0 1 3 4v3',
  'model-settings': 'M4 4v16 M12 4v16 M20 4v16 M1 8h6 M9 16h6 M17 10h6',
}
export default function NavIcon({ page }: { page: string }) { return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={shapes[page]} /></svg> }
