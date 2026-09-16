# Application foundation

This milestone implements the application and data-contract foundation. The
[product scope](product-scope.md) remains the complete MVP target.

## Implemented behavior

- UUID/email User, password hashing through Django, database-level case-insensitive
  email uniqueness, and email normalization in the manager and Admin creation form.
- Transactional registration with one personal Organization and OWNER membership.
- Organization creation, listing, rename, member listing, role changes, and removal.
  A user may belong to multiple workspaces. Lists accept `limit` (1–100) and `offset`.
- Organization-scoped authorization, parent-row locking for membership mutations,
  and last-owner protection under concurrent requests. Platform staff are not
  automatically organization members.
- Browser sessions with CSRF on anonymous registration/login as well as authenticated
  mutations. Production cookies are Secure; session cookies are HttpOnly.
- React registration/login, workspace creation/switching, member display, and
  explicit loading, failure, empty, and future-research states.
- Django Admin user management and read-only organization/membership inspection.
- AuthIdentity's provider/subject uniqueness boundary; provider login/linking is
  not implemented.
- A versioned [market observation contract](../contracts/README.md), validated by
  Python and Rust against the same generated JSON Schema and shared fixtures.
- Separate backend, worker, collector, web, and database services with health checks
  and graceful shutdown. ClickHouse access has a dedicated repository boundary.

## Identity and authorization decisions

The database has both a unique email field (for Django's identifier contract) and
a functional `LOWER(email)` unique constraint (for case-insensitive uniqueness).
Authentication resolves natural keys case-insensitively. UUIDs identify accounts
and workspaces in API responses and relationships.

OWNER can manage workspace settings and membership roles. ADMIN can rename a
workspace and manage MEMBER/VIEWER roles, while owner/admin role management stays
with OWNER. Members may leave their own workspace; the final OWNER must first
promote another active member. VIEWER cannot manage organization settings.

Membership mutations use application services that lock the Organization before
checking membership and owner count. These are application workflow invariants;
database uniqueness and valid-role checks do not themselves enforce owner counts.
Do not bypass these services with direct ORM/SQL membership updates. Admin disables
organization/membership edits and bulk deletion. User foreign keys are protected
while memberships remain, and Admin does not provide user deletion/deactivation
or email changes until their dedicated workflows are implemented.

Creating a platform user in Admin or with `createsuperuser` creates only identity.
Customer registration creates the personal workspace. Invitations and membership
addition workflows remain future work; a second workspace can currently be created
and owned by the same user through the application.

Session authentication and anonymous CSRF checks use Django/Ninja's existing
mechanisms. Implementation references:
[Django custom users](https://docs.djangoproject.com/en/5.2/topics/auth/customizing/)
and [Django Ninja CSRF](https://django-ninja.dev/reference/csrf/).

## API surface

| Method | Path | Access |
| --- | --- | --- |
| GET | `/health`, `/ready` | Liveness / dependency status |
| GET | `/api/v1/auth/csrf` | Issue CSRF cookie and masked token |
| POST | `/api/v1/auth/register`, `/api/v1/auth/login` | Anonymous, CSRF required |
| POST | `/api/v1/auth/logout` | Session and CSRF required |
| GET | `/api/v1/me` | Session required |
| GET / POST | `/api/v1/organizations` | List memberships / create an owned team workspace |
| GET / PATCH | `/api/v1/organizations/{id}` | Membership / OWNER or ADMIN |
| GET | `/api/v1/organizations/{id}/members` | Membership required |
| PATCH / DELETE | `/api/v1/organizations/{id}/members/{membership_id}` | Centralized role and last-owner policy |

All state-changing session routes require a CSRF token. Fetch a fresh token after
login/registration, which rotates the CSRF secret. Requests for another tenant's
workspace or a membership outside the URL workspace return 404. Explicit schemas
prevent password hashes and platform permissions from leaking through model dumps.

## Container workflow

See [README](../README.md) for startup. `compose.yaml` builds production-style
images with development application settings and loopback-only host ports.
`compose.dev.yaml` selects development image targets and mounts source for Vite
and backend hot reload. All databases stay on the Compose network.

The original foundation worker and collector only exposed health checks. They have
since been extended with the [market research pipeline](market-research.md), its
historical tables, migrations, current-state cache and deterministic analytics.

The `migrate` job runs separately from request processes and must succeed before
backend/worker startup. `make migrate` reruns the explicit deployment step safely.
Never run concurrent migration deployments. Named volumes survive `compose down`.

## Optional host development

Install Python 3.12, uv, Node 22, and Rust 1.91.1 if using host tools. Configure
PostgreSQL connection variables for a development database before integration
tests; do not point tests at a production database.

```bash
uv sync --frozen
uv run ruff check .
uv run ruff format --check .
PYTHONPATH=apps/backend:python uv run mypy
uv run pytest
PYTHONPATH=python uv run python scripts/export_contracts.py --check

cargo fmt --manifest-path services/market-data/Cargo.toml --check
cargo clippy --locked --manifest-path services/market-data/Cargo.toml --all-targets --all-features -- -D warnings
cargo test --locked --manifest-path services/market-data/Cargo.toml

cd apps/web
npm ci
npm run lint
npm run test
npm run build
```

Python dependencies, frontend dependencies, and Rust dependencies have checked-in
lockfiles. Normal tests use synthetic fixtures and mocked external dependencies.
The shared contract is a wire-format foundation. Source-adapter semantic validation
and real exchange parsing are covered by the market research implementation.

## Production configuration

Production configuration is provided for a future single-server deployment; this
milestone does not deploy to a public host. Set `QUANTHECY_DOMAIN` to the intended
DNS name and replace `DJANGO_SECRET_KEY`, `POSTGRES_PASSWORD`, and
`CLICKHOUSE_PASSWORD` with independent secrets. Store them outside version control.
Production settings reject a missing, short, or development Django secret.

```bash
docker compose -f compose.yaml -f compose.prod.yaml config --quiet
docker compose -f compose.yaml -f compose.prod.yaml build
docker compose -f compose.yaml -f compose.prod.yaml run --rm migrate
docker compose -f compose.yaml -f compose.prod.yaml up -d --wait
```

Caddy terminates HTTPS for the configured domain and forwards the original host
and scheme. Only ports 80/443 are published. Backend trusts the proxy scheme header
because it is reachable only on the private container network. PostgreSQL, Redis,
ClickHouse, and Rust operational endpoints have no public host ports. Production
settings enable secure cookies, HTTPS redirects, and HSTS.

Before a public research launch, implement and verify backup/restore procedures,
authentication rate limiting, account recovery/verification, monitoring, and the
remaining product milestones. The production image/configuration alone does not
complete those workflows.

## Verification record

Verified locally on 2026-09-15:

- 56 Python tests against PostgreSQL, both on the host and inside the development
  image; includes case-insensitive uniqueness, transaction rollback, CSRF/origin
  protection, tenant isolation, and concurrent last-owner protection.
- 6 frontend tests, lint, TypeScript checking, and production build, also exercised
  inside the frontend Docker checks target.
- 3 Rust tests, including both platform fixtures and 16 shared invalid cases;
  formatting, Clippy, release image build, and the Docker checks target passed.
- Ruff lint/format, mypy, schema drift, initial migrations, migration consistency,
  and Django's production security checks passed.
- All seven long-running Compose services reported healthy. Both default and
  hot-reload configurations started successfully with a separate migration job.
- HTTP smoke checks exercised registration/session/CSRF and workspace APIs through
  Vite and Nginx; the production static frontend and Django Admin were served.
- Redis interruption left backend liveness available, made readiness fail, and
  readiness recovered when Redis returned.
- Backend, worker, and Rust containers exited with code 0 on shutdown. Account
  data survived PostgreSQL restart and the full stack returned to healthy status.
- Production configuration validation confirmed that only the reverse proxy
  publishes host ports. Backend and Rust production processes use non-root users.

The machine's Docker Hub authentication/rate limit was worked around using the
public image cache for the same upstream images and an isolated Docker client
configuration. A Rust build was also checked using the host's existing proxy via
standard Docker build proxy arguments; application runtime settings were unchanged.

This record describes milestone 1, before exchange ingestion was implemented;
see the market research guide for subsequent verification. LLM analysis remains
pending. Public HTTPS deployment and real-browser visual inspection were not performed; no browser
connection was available. Component tests and live HTTP checks cover different
behavior and do not establish visual correctness.
