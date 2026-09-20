# Financial terminal visual update · 2026-09-20

The customer workspace uses a graphite palette, amber navigation and actions, and green/red market changes. Shared tokens live in `apps/web/src/workstation.css`; ECharts uses the corresponding canvas palette in `chartTheme.ts`.

New visitors start in dark mode. Saved light/dark/system choices still apply, including cross-tab synchronization and system-theme changes. The pre-render theme script follows the same default to avoid a light flash. Desktop navigation starts expanded, mobile navigation collapsed; an existing saved layout takes precedence.

The overview brings coverage totals, the six largest qualified 15-minute movements, reviewed comparisons, and news into one workspace. Rankings come from the existing Django `/api/v1/markets?limit=6&sort=movement` API. Missing prices remain unavailable; empty rankings explain why data is absent. No browser-side exchange access or fabricated history is introduced.

Tables, account cards, chart controls, login and settings share the palette and spacing. The paper-equity legend now scrolls independently above the plot on narrow screens.

## Validation

- Production build (including TypeScript), ESLint, and all 106 frontend tests passed.
- Isolated Chrome checks covered 1440 px and 1920 px desktops and a 390 px mobile viewport, light/dark switching, navigation, market charts and simulated accounts.
- The production Web container was rebuilt and replaced independently; all 11 local services remained healthy. The deployed bundle passed the same fixture-based layout checks.
- No page-level horizontal overflow or browser runtime exceptions occurred in these checks. Wide data tables retain their own horizontal scrolling.
- The in-app browser runtime failed to initialize because it referenced a missing plugin version; visual QA used a fresh, isolated local Chrome context instead.

## Visual references

These screenshots use browser-intercepted QA fixtures, **not live quotes, portfolio results, or current coverage counts**. The application itself has no fixture data or demo fallback.

- [Dark overview](screenshots/workstation-2026-09-20/overview-dark.png)
- [Light overview](screenshots/workstation-2026-09-20/overview-light.png)
- [Market terminal](screenshots/workstation-2026-09-20/terminal.png)
- [Mobile overview](screenshots/workstation-2026-09-20/mobile-default.png)

## Refinement after authenticated review

The real logged-in workspace exposed a much longer source list and review panel than the initial fixtures. The overview now summarizes healthy, attention-needed and paused sources; full diagnostics remain in a bounded, keyboard-accessible disclosure. The simulated-account page puts account equity and its chart before review history and configuration. Model unavailability and processing delays remain visible near the accounts.

Movement colors now share the displayed rounding rule across the overview, directory and terminal: upward green, downward red, and neutral for zero, rounded zero, stale or missing values. Unavailable or unchanged account equity is also neutral. Chinese comparison and running-state labels were completed.

Validation: 114 frontend tests and ESLint passed; the production image built successfully. The deployed bundle was checked at 1440, 1920 and 390 px without page-level overflow or runtime errors. The actual authenticated account page was also inspected after deployment: account balances appear before the review panel and zero returns remain neutral. Real account screenshots stay outside the repository.
