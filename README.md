# Quanthecy

Prediction-market data, quantitative research, and automated Agent analysis for
Polymarket and Kalshi.

Quanthecy is designed for personal research and other quantitative researchers,
with accessible summaries and charts for general users. Its research workflow is:

> Discover market changes → compare related markets → inspect news and evidence →
> develop and verify research hypotheses.

## Project status

**Market activity, cross-platform comparison and news research implemented.** Rust collects selected
public Polymarket/Kalshi REST snapshots; ClickHouse preserves history, Redis caches
current state, and the Python worker calculates explainable signals. The React
research workspace provides market detail, probability history, rankings,
CSV/Parquet exports, a signal feed, reviewed comparisons and official news evidence
through Django APIs. The first comparison topic is **macroeconomics and interest rates**.
A chart-centered research terminal and on-demand intelligence pipeline are implemented.
The [single-market expert team](docs/intelligence-team.md) combines quantitative,
event, investment and risk research with a synthesis stage, scoped context,
versioned skills and conditional forecasts. Quick single-Agent research remains
available; each collaborative run reserves up to five explicitly initiated model calls.
Workspace owners configure model connections in the web UI; models start disabled.
Signal-triggered research and daily digests remain future work.

See [foundation implementation and verification](docs/foundation.md) for current
identity capabilities, and [market research](docs/market-research.md) for source
semantics, bounded coverage, recovery, signal definitions and reproduction.
See [cross-platform and evidence research](docs/cross-market-evidence.md) for the
selected Fed feeds, comparison reviews, cutoff semantics and setup.

## Local setup

Requires Docker Engine and Docker Compose **2.24.4 or newer**. No host Python,
Rust, Node.js, or database installation is required for the container workflow.

```bash
cp .env.example .env
docker compose up --build -d --wait
```

The dedicated `migrate` service applies Django and ClickHouse migrations before
backend, worker and collector startup. The application uses PostgreSQL, ClickHouse,
Redis and a durable collector journal with named
volumes. Initial image builds require access to the public image and package
registries.

| Surface | Local URL |
| --- | --- |
| Workspace / registration / login | http://localhost:3000 |
| API documentation | http://localhost:8000/api/v1/docs |
| Django Admin | http://localhost:8000/admin/ |
| Backend liveness / dependency readiness | http://localhost:8000/health / http://localhost:8000/ready |

There is no default account or password. Register in the web application to create
a personal workspace and its OWNER membership, then open **Market explorer**.
The navigation also includes **Research overview**, **Signal feed**, **Cross-platform**,
**News & evidence**, **Workspace & members**, and **Model settings**. Detail links support reload,
browser back navigation and shareable historical cutoffs.
By default, up to 10 markets per exchange are sampled every 60 seconds. Collection
starts at startup; 15-minute analytics appear once sufficient history exists.
An independent news worker polls two official Federal Reserve feeds every 15 minutes.
Comparisons appear only after selected markets have been collected and reviewed;
use the [review manifest workflow](docs/cross-market-evidence.md#initial-pair-setup)
to load the first two September 2026 Fed pairs. Their dates are explicit and should
be reselected after expiry.
To create a separate platform operator account:

```bash
docker compose exec backend python apps/backend/manage.py createsuperuser
```

For frontend/backend hot reload:

```bash
make dev
```

For Linux environments whose outbound proxy listens only on host loopback, see
the [optional local proxy configuration](docs/market-research.md#optional-local-proxy).

Changes to dependencies require rebuilding the images. Rust changes require a
collector image rebuild. To stop services while preserving named volumes:

```bash
docker compose down
```

## Validation

The Python integration tests use PostgreSQL, including real uniqueness constraints
and a concurrent last-owner test. Normal tests do not contact exchanges or LLMs.

```bash
make test-python
make check-python
make test-rust
make test-web
make check-contracts
```

These commands use containers. Optional host workflows and production setup are
documented in [the foundation guide](docs/foundation.md).

See [research terminal and model setup](docs/research-terminal.md) for chart interactions,
workspace credentials, the on-demand worker and current limits. The top bar supports persistent Chinese / English switching. Model settings include
common provider presets and native Anthropic Messages support. Saving model settings
does not call a model; tests and analysis require explicit actions.

## Planned MVP

- **Market activity:** probability history, rankings, and explainable signals for
  price movements, unusual volume, and widening spreads.
- **Cross-platform research:** curated Polymarket/Kalshi market pairs, price
  comparisons, and visible differences in contract and settlement rules.
- **News and events:** selected news and announcement sources, a shared timeline
  with market activity, and traceable evidence links.
- **Intelligence research:** on-demand specialist collaboration or quick analysis
  with frozen evidence, scoped context and conditional forecasts. Signal triggers
  and scheduled summaries remain planned.
- **Research access:** historical APIs, CSV/Parquet exports, and a reproducible
  notebook example.
- **Workspaces:** UUID/email-based users, organizations, memberships, and explicit
  organization authorization.

All three research areas are included in the planned MVP. Initial coverage will
be bounded by selected markets, reviewed market pairs, and selected news sources.
Automated activity covers research, explanations, and in-app updates. Trade
execution and wallet management are outside the MVP.

## Architecture

```text
Polymarket / Kalshi
        │
        ▼
Rust + Tokio collectors
        │
        ├── ClickHouse: analytical history
        └── Redis: current state and transient coordination

Selected news / announcements
        │
        ▼
Python worker source adapters ── Django ORM ── PostgreSQL: evidence metadata

Historical data + evidence
        │
        ▼
Python worker: metrics → signals → selection → Agent research
        │
        ▼
Django + Django Ninja ── PostgreSQL: application state and research runs
        │
        ▼
React + TypeScript + Vite
```

Django is the canonical application API and owns PostgreSQL schemas through
migrations. ClickHouse has a dedicated analytical repository layer. Backend and
worker processes may share a Python image. Docker Compose is the planned local
development and initial single-server deployment path.

## Design documents

- [Product scope](docs/product-scope.md): audience, research workflows, data
  requirements, and MVP boundaries.
- [Research terminal and model setup](docs/research-terminal.md): chart workspace, web model
  configuration, encrypted credentials, on-demand jobs, and verification.
- [Automated research](docs/automated-research.md): triggers, evidence, structured
  output, task lifecycle, and workspace controls.
- [Implementation roadmap](docs/roadmap.md): milestones and acceptance criteria.
- [Foundation guide](docs/foundation.md): development, identity/API behavior,
  validation, and production configuration.
- [Market research](docs/market-research.md): implemented ingestion, history,
  signals, data limitations and reproducible exports.
- [Cross-platform and evidence research](docs/cross-market-evidence.md): reviewed
  pairs, official feeds, immutable revisions, historical cutoffs and frontend workflow.
- [Architecture and contributor instructions](AGENTS.md): technology ownership,
  identity boundaries, storage, deployment, and engineering requirements.

## License

[Apache License 2.0](LICENSE).
