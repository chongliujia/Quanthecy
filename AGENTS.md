# AGENTS.md

## Project Overview

**Quanthecy** is an open-source prediction-market intelligence platform for **Polymarket** and **Kalshi**.

Quanthecy collects public prediction-market data, normalizes data across exchanges, stores high-volume historical time-series data, detects market signals and anomalies, compares related markets, and provides an Agent-based intelligence layer.

Quanthecy is designed as both:

1. a prediction-market data and research platform;
2. a foundation that may later evolve into a multi-user SaaS product.

Potential future product capabilities include:

- user accounts;
- organizations and teams;
- role-based access;
- API keys;
- watchlists;
- alerts;
- internal administration;
- subscriptions;
- billing;
- usage limits;
- entitlements;
- audit logs;
- external identity providers;
- enterprise authentication.

The architecture must support these capabilities without requiring a future backend rewrite.

The initial product goal is:

> **Prediction-market data infrastructure + quantitative analytics + explainable Agent intelligence.**

The initial product goal is **not autonomous trading**.

---

# Core Technology Decisions

The default technology stack is:

```text
Frontend
    React + TypeScript + Vite
                │
                ▼
Application / Control Plane
    Django + Django Ninja
                │
       ┌────────┼──────────┐
       ▼        ▼          ▼
 PostgreSQL   Redis    ClickHouse
       ▲        ▲          ▲
       │        │          │
       └────────┼──────────┘
                │
Intelligence Plane
           Python
                ▲
                │
Data Plane
       Rust + Tokio
                │
        ┌───────┴───────┐
        ▼               ▼
   Polymarket          Kalshi
```

Primary responsibility boundaries:

```text
Rust
    ingestion
    normalization
    realtime market data
    stream processing

Django
    application backend
    authentication
    organizations
    authorization
    admin
    application APIs
    SaaS domain

Django Ninja
    typed REST APIs
    OpenAPI schemas

Python
    analytics
    signals
    anomaly detection
    agents
    backtesting

ClickHouse
    historical analytical market data

PostgreSQL
    transactional application data

Redis
    realtime state
    cache
    coordination

React
    presentation layer

Docker
    packaging

Docker Compose
    development and initial deployment
```

These boundaries must not be changed without a documented architectural reason.

---

# Architectural Planes

Quanthecy is divided conceptually into four planes.

## Data Plane

Implemented primarily in Rust.

```text
Polymarket ─┐
            ├──► Rust Collector
Kalshi ─────┘
                    │
                    ├──► ClickHouse
                    ├──► Redis
                    └──► PostgreSQL metadata when necessary
```

The Data Plane is optimized for:

- high throughput;
- low latency;
- reliable ingestion;
- exchange WebSocket handling;
- event normalization;
- data integrity;
- deduplication;
- batching;
- reconnect logic.

---

## Application / Control Plane

Implemented with Django and Django Ninja.

```text
React
  │
  ▼
Django Ninja API
  │
  ├── Users
  ├── Organizations
  ├── Memberships
  ├── Permissions
  ├── Watchlists
  ├── Alerts
  ├── API Keys
  ├── Admin
  ├── Subscriptions
  └── Billing
```

This is the canonical public application backend.

---

## Intelligence Plane

Implemented in Python.

```text
Historical Data
      ↓
Features
      ↓
Signals
      ↓
Anomaly Detection
      ↓
Market Selection
      ↓
Agent Context
      ↓
Agent Decision
```

LLMs operate on structured analytical context.

LLMs must not be treated as the primary numerical computation engine.

---

## Presentation Plane

Implemented in React.

Potential product surfaces include:

```text
Market Explorer
Market Detail
Movers
Signals
Anomalies
Cross-Market Comparison
Agent Analysis
Watchlists
Alerts
Account
Organization
Billing
```

---

# Backend Technology Decision

## Django Is the Primary Backend

The main application backend MUST use:

```text
Python
Django
Django Ninja
Pydantic
```

Do not introduce FastAPI as a parallel public backend.

There must be one canonical application API:

> **Django + Django Ninja**

This decision exists because Quanthecy may evolve into a SaaS application requiring:

- authentication;
- authorization;
- users;
- organizations;
- teams;
- administration;
- subscriptions;
- billing;
- audit trails;
- relational business models.

Choosing Django from the beginning avoids a future migration of the application domain into Django after significant product logic already exists.

---

# Django Ninja

Use Django Ninja for public JSON APIs.

Django Ninja owns:

- typed API inputs;
- typed API outputs;
- request validation;
- response validation;
- OpenAPI generation;
- API versioning.

Preferred request flow:

```text
React
  ↓
Django Ninja
  ↓
Application Service
  ↓
Repository / Analytics
  ↓
PostgreSQL / ClickHouse / Redis
```

API handlers must remain thin.

Do not expose arbitrary Django model objects directly.

Use explicit request and response schemas.

---

# Fundamental Identity Model

The following model boundaries are architectural decisions.

```text
User
    identity

Organization
    tenant / workspace

OrganizationMembership
    organization-level authorization

AuthIdentity
    external identity provider linkage

UserProfile
    optional human-facing profile data

UserPreference
    product preferences

Subscription
    organization billing relationship

Entitlement
    product capabilities

APIKey
    organization-scoped machine authentication
```

The foundational rule is:

> **User = identity, Organization = tenant, Membership = authorization.**

Do not collapse these concepts.

---

# Custom Django User Model

A custom User model MUST exist before the first production migration.

Do not begin with Django's default User model and attempt to replace it later.

Configure:

```python
AUTH_USER_MODEL = "accounts.User"
```

from project creation.

---

# User Primary Key

User IDs must use UUIDs.

Conceptually:

```python
class User(...):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
```

Do not expose sequential database IDs as long-term public identifiers.

Use the UUID when other application entities need a stable reference to a user.

Never use email as a foreign-key-like identifier.

---

# Email-Based Authentication

Quanthecy does not require usernames.

The User model should use email as its primary human authentication identifier.

Conceptually:

```python
class User(AbstractUser):
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    username = None

    email = models.EmailField()

    email_verified_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()
```

Exact implementation may evolve, but these semantics should remain.

---

# Email Uniqueness

Email addresses must be unique in a case-insensitive manner.

The system must not allow:

```text
alice@example.com
Alice@example.com
ALICE@example.com
```

to represent separate users.

Enforce uniqueness at the database layer.

For PostgreSQL-backed Django models, an acceptable approach is a functional unique constraint such as:

```python
UniqueConstraint(
    Lower("email"),
    name="accounts_user_email_ci_unique",
)
```

Application-level validation alone is insufficient.

The custom UserManager must also normalize email consistently.

---

# Custom User Manager

A custom UserManager must implement the expected Django user creation semantics.

At minimum:

```text
create_user
create_superuser
```

The manager must:

- normalize email;
- require a valid email;
- correctly hash passwords;
- set staff/superuser flags correctly;
- reject invalid superuser state.

Do not manually create password hashes.

Use Django password APIs.

---

# User Model Scope

Keep the User model small and stable.

The User model may contain fields directly related to identity and authentication, such as:

```text
id
email
password

is_active
is_staff
is_superuser

email_verified_at

date_joined
last_login
```

Do not allow the User model to become a dumping ground for unrelated product data.

Avoid fields such as:

```text
company
job_title
theme
dashboard_layout
newsletter_preferences
trading_preferences
default_market_filters
avatar_configuration
billing_plan
stripe_customer_id
```

on the User model itself.

---

# User Profile

Human-facing metadata should live in a separate model when required.

Conceptually:

```text
User
 │
 ▼
UserProfile
```

Potential fields:

```text
display_name
avatar
timezone
locale
job_title
```

Do not create profile fields until the product needs them.

Avoid speculative fields.

---

# User Preferences

Product preferences belong outside authentication identity.

Conceptually:

```text
User
 │
 ▼
UserPreference
```

Potential examples:

```text
default_timezone
theme
dashboard_preferences
notification_preferences
default_market_filters
```

Do not mix product settings into the core User model.

---

# External Authentication

Future authentication may include:

```text
Google
GitHub
Apple
Microsoft
OIDC
Enterprise SSO
```

Do not add provider-specific fields to User.

Avoid:

```text
google_id
github_id
microsoft_id
apple_id
```

inside the User table.

Use an external identity model.

Conceptually:

```text
User
 │
 └── AuthIdentity
        provider
        subject
        email
        created_at
        updated_at
```

Example:

```text
User
    581...

AuthIdentity
    provider = "google"
    subject = "10928374029384"

AuthIdentity
    provider = "github"
    subject = "829104"
```

A user may have multiple identities.

---

# AuthIdentity Constraints

At minimum, AuthIdentity must enforce:

```text
UNIQUE(provider, subject)
```

Provider subject identifiers are the authoritative external identity keys.

The email returned by an external provider may be stored for reference, but must not replace the provider subject as the identity key.

Do not automatically merge accounts solely because two external providers return the same email without a deliberate account-linking policy.

---

# Email Verification

Email verification state must be explicit.

Prefer:

```text
email_verified_at
```

over a loosely managed boolean when practical.

A non-null timestamp means the address has been verified.

Do not infer email verification merely because the user authenticated through a provider unless that provider's verification guarantees are explicitly trusted.

---

# Email Changes

Email may change over the lifetime of a user.

Therefore:

- internal references must use UUID;
- audit-sensitive flows should record relevant email changes;
- verification may need to be re-established after an email change;
- changing email must not create a new user identity implicitly.

---

# User Deletion

Do not implement naive destructive cascading deletion of important analytical or billing history.

User deletion semantics must distinguish between:

```text
authentication account deletion
personal data deletion
organization ownership
billing records
audit/legal records
historical Agent executions
```

Before deleting a user who owns organizations, ownership must be transferred or the organization must be intentionally closed.

Do not silently delete an Organization because its creator deletes their personal account.

---

# Django Platform Permissions

Django built-in platform permissions have different semantics from customer organization permissions.

The fields:

```text
is_staff
is_superuser
```

mean:

> permissions to operate the Quanthecy platform itself.

They do NOT mean:

> permissions inside a customer's Organization.

Example:

```text
User: alice@example.com

Django:
    is_staff = False
    is_superuser = False

Organization: Acme Research
    role = OWNER

Organization: Example Capital
    role = VIEWER
```

This is valid.

Never derive Organization permissions from `is_staff`.

Never make every Organization owner a Django staff user.

---

# Organization Model

Organization is the primary SaaS tenant and workspace boundary.

Conceptually:

```python
class Organization(models.Model):
    id
    name
    slug
    kind
    created_at
    updated_at
```

Use UUID primary keys.

Potential organization kinds:

```text
PERSONAL
TEAM
```

Do not create fundamentally separate architecture for individual users and teams.

A personal user can simply own a personal Organization.

---

# Personal Organizations

When appropriate, a newly registered user may receive a personal Organization.

Example:

```text
User
    alice@example.com

Organization
    Alice's Workspace
    kind = PERSONAL

Membership
    user = Alice
    role = OWNER
```

This allows both B2C and B2B workflows to share the same application model.

A personal workspace can later subscribe to a paid plan just like a team workspace.

---

# Organization Membership

User and Organization must have a many-to-many relationship through an explicit Membership model.

Do not use:

```python
user.organization = ...
```

A user may belong to multiple organizations.

Conceptually:

```text
User
   │
   ▼
OrganizationMembership
   │
   ▼
Organization
```

Potential model:

```text
OrganizationMembership

id
user_id
organization_id
role
created_at
updated_at
```

Enforce:

```text
UNIQUE(user_id, organization_id)
```

Use UUID primary keys where appropriate.

---

# Organization Roles

Keep initial organization roles deliberately simple.

Initial roles:

```text
OWNER
ADMIN
MEMBER
VIEWER
```

Expected semantics:

## OWNER

May:

- manage organization settings;
- manage members;
- manage billing;
- manage API keys;
- manage subscriptions;
- delete or transfer organization ownership where allowed.

## ADMIN

May generally:

- manage most organization resources;
- manage members where permitted;
- configure alerts;
- configure integrations.

Should not automatically have destructive ownership or billing rights unless explicitly allowed.

## MEMBER

May:

- use normal product functionality;
- create permitted resources;
- access organization data according to product rules.

## VIEWER

Read-only access by default.

Do not introduce a complex arbitrary permission matrix during the MVP.

---

# Organization Authorization

Organization authorization must be explicit and centralized.

Avoid authorization logic scattered across route handlers.

Prefer constructs such as:

```text
require_org_member(...)
require_org_role(...)
require_org_permission(...)
```

or an equivalent service/policy layer.

Every organization-scoped object must be accessed within an explicit Organization context.

---

# Tenant Isolation

Tenant isolation is a critical requirement.

Any organization-owned PostgreSQL entity should contain an explicit organization relationship where appropriate.

Examples:

```text
Watchlist
    organization_id

Alert
    organization_id

APIKey
    organization_id

AgentConfiguration
    organization_id
```

Queries for organization-scoped resources must always constrain by the active Organization.

Avoid:

```python
Watchlist.objects.get(id=watchlist_id)
```

when handling customer-facing requests.

Prefer semantics equivalent to:

```python
Watchlist.objects.get(
    id=watchlist_id,
    organization=active_organization,
)
```

Never rely on the frontend to enforce tenant isolation.

---

# Organization Context

Customer-facing APIs should have a clear active Organization context.

Possible mechanisms include:

```text
URL organization identifier

authenticated active organization

organization-scoped API key
```

The mechanism should be consistent.

Do not infer the Organization from arbitrary resource ownership when the request can specify it explicitly.

---

# Organization Creation

Organization creation should be transactional.

When creating an Organization:

1. create the Organization;
2. create the initial OWNER membership;
3. initialize required defaults;
4. optionally initialize billing/customer state;
5. commit as one logical workflow.

Do not allow an Organization to exist without an owner because a partial request failed.

---

# Organization Invitations

Future team invitations should use an explicit invitation model.

Conceptually:

```text
OrganizationInvite

id
organization_id
email
role
token_hash
expires_at
accepted_at
invited_by
created_at
```

Do not create a placeholder User merely because someone was invited.

The invitation is converted into a Membership when accepted.

---

# Organization Ownership

Organizations must have at least one owner.

If the last owner attempts to leave:

- transfer ownership first;
- promote another valid member;
- or explicitly close/delete the Organization.

Do not allow an active Organization to accidentally reach zero owners.

---

# Billing Boundary

Billing belongs to the Organization.

Do not attach primary subscription ownership directly to User.

Preferred model:

```text
Organization
    │
    ├── BillingCustomer
    ├── Subscription
    ├── Entitlements
    └── Usage
```

This design supports:

```text
individual customer
team
enterprise
```

using the same underlying model.

---

# Billing Models

Billing does not need to be fully implemented during the initial MVP.

The architectural boundary should support future models such as:

```text
Plan

BillingCustomer

Subscription

Entitlement

UsageRecord
```

Provider-specific integration details must remain isolated.

---

# Billing Provider Boundary

Do not scatter payment-provider logic through Django models and route handlers.

Preferred structure:

```text
billing/
├── models.py
├── services.py
├── entitlements.py
├── webhooks.py
└── providers/
    └── stripe.py
```

Core domain code should work with internal abstractions such as:

```text
BillingCustomer
Subscription
Plan
Entitlement
```

rather than directly depending everywhere on:

```text
stripe_customer_id
stripe_subscription_id
stripe_price_id
```

Provider IDs may exist inside provider-specific integration records.

---

# Subscription Ownership

Subscription belongs to Organization.

Conceptually:

```text
Organization
    │
    ▼
Subscription
    │
    ▼
Plan
```

Potential plans:

```text
FREE
PRO
TEAM
ENTERPRISE
```

The exact commercial model is not yet fixed.

Do not hardcode product logic around these example names.

---

# Entitlements

Product access should eventually be expressed through an entitlement layer.

Examples:

```text
max_watchlists
max_alerts
api_access
agent_requests_per_month
realtime_data_access
historical_retention_days
team_members
advanced_cross_market
```

Do not scatter checks such as:

```python
if subscription.plan == "PRO":
```

through route handlers.

Prefer:

```text
entitlement_service.can(...)
entitlement_service.limit(...)
```

or equivalent.

---

# Usage Tracking

Usage tracking should be Organization-scoped.

Examples:

```text
agent requests
API requests
historical data queries
alert executions
export volume
```

Usage events should be designed so they can later support:

- plan limits;
- dashboards;
- billing;
- abuse protection.

Do not block the MVP on a sophisticated usage metering system.

---

# API Keys

Programmatic API keys should belong to Organizations.

Conceptually:

```text
Organization
    │
    └── APIKey
```

Potential fields:

```text
id
organization_id
name
prefix
secret_hash
created_by
last_used_at
expires_at
revoked_at
created_at
```

Never store raw API-key secrets after creation.

Store only a cryptographic hash.

Display the raw secret once.

API keys should be revocable.

---

# API-Key Scopes

If API-key scopes become necessary, model them explicitly.

Examples:

```text
markets:read
signals:read
alerts:read
alerts:write
agent:run
```

Do not build a complex scope system before product requirements demand it.

---

# Browser Authentication

The React application should use secure application authentication provided through Django.

Do not implement a custom cryptographic authentication protocol.

If cookie/session authentication is used:

- enable secure cookie settings in production;
- protect state-changing requests with CSRF;
- configure SameSite appropriately;
- never expose session secrets to JavaScript unnecessarily.

JWT should not be introduced solely because the frontend is React.

Use JWT only when there is a concrete deployment or integration reason.

---

# Password Security

Use Django's password hashing framework.

Do not implement password hashing manually.

Do not log:

```text
password
password reset token
session token
API key secret
OAuth token
```

Password-reset tokens must expire according to appropriate policy.

---

# Authentication Rate Limiting

Sensitive authentication endpoints should eventually support rate limiting.

Examples:

```text
login
password reset
email verification
invite acceptance
API key creation
```

The exact rate-limiting architecture may be implemented later.

---

# Django Admin

Django Admin is a first-class internal operations interface.

Potential Admin areas:

```text
Users
Organizations
Memberships
Organization Invites

Markets
Events
Market Mappings

Watchlists
Alerts

Agent Configurations
Agent Runs

Plans
Subscriptions
Billing Customers

API Keys

Audit Logs
```

Do not build a custom React admin interface for functionality Django Admin already handles adequately.

React is primarily for customer-facing product functionality.

Django Admin is primarily for Quanthecy operators.

---

# Audit Logging

Important administrative actions should eventually generate audit events.

Potential events:

```text
organization.created
organization.deleted

member.invited
member.joined
member.removed
member.role_changed

api_key.created
api_key.revoked

subscription.changed

user.email_changed

admin.user_modified
```

Audit records should contain stable identifiers rather than depending solely on mutable names or emails.

Do not log secrets.

---

# Django ORM Boundary

Django ORM is authoritative for PostgreSQL application data.

Use Django ORM for:

```text
users
organizations
memberships
auth identities

watchlists
alerts

API keys

billing
subscriptions
entitlements

market metadata

agent configuration
agent execution metadata
```

Do NOT use Django ORM as the primary abstraction for ClickHouse.

Do not attempt to make PostgreSQL and ClickHouse look identical through one generic ORM.

---

# ClickHouse Access

ClickHouse should be accessed through a dedicated analytical repository layer.

Conceptually:

```python
class MarketHistoryRepository:
    async def get_probability_history(...):
        ...

    async def get_volume_history(...):
        ...

    async def get_market_candles(...):
        ...

    async def get_signals(...):
        ...
```

Preferred flow:

```text
Django Ninja Route
        ↓
Application Service
        ↓
MarketHistoryRepository
        ↓
ClickHouse
```

Do not put large ClickHouse SQL queries directly inside route handlers.

---

# Redis Access

Redis stores ephemeral live state.

Use Redis for:

```text
latest market state

latest probability

best bid / ask

order-book summary

latest signals

short-lived application cache

distributed coordination

live-update fan-out
```

Redis is not the authoritative historical store.

Loss of Redis must not permanently destroy historical market data.

---

# Rust Data Plane

Rust owns exchange ingestion and real-time market processing.

Responsibilities include:

- Polymarket REST;
- Polymarket WebSocket;
- Kalshi REST;
- Kalshi WebSocket;
- reconnect handling;
- rate limiting;
- event parsing;
- market normalization;
- trade normalization;
- order-book normalization;
- deduplication;
- snapshot generation;
- batch persistence;
- live-state updates;
- health reporting;
- ingestion metrics.

Preferred libraries:

```text
tokio
reqwest
serde
serde_json
tokio-tungstenite
tracing
clickhouse
redis
```

Use PostgreSQL from Rust only when genuinely required.

Do not reproduce Django application logic inside Rust.

---

# Rust HTTP Boundary

Rust is not the public application backend.

If operational HTTP endpoints are needed, use Axum.

Typical internal endpoints:

```text
GET /health

GET /ready

GET /metrics

GET /status
```

Do not duplicate customer-facing Django endpoints inside Rust.

---

# Python Analytics

Python owns the analytical and intelligence layer.

Responsibilities include:

```text
probability changes

probability velocity

probability acceleration

volatility

market ranking

volume analysis

liquidity analysis

spread analysis

order-book imbalance

anomaly detection

cross-market comparison

feature engineering

backtesting

signal generation

Agent context construction

Agent prompts

structured Agent output
```

Preferred libraries:

```text
Python 3.12+

Pydantic v2

Polars

NumPy

SciPy

ClickHouse client

Redis client
```

Pandas may be used where appropriate.

Prefer Polars for larger analytical workloads.

---

# Analytics Worker

Long-running analytical work must not run inside HTTP request handlers.

Run analytics as independent processes/containers.

Example:

```text
quanthecy-backend
    Django / HTTP

quanthecy-worker
    analytics
    anomalies
    signals
    Agent jobs
```

The backend and worker may share the same Python project and Docker image.

Possible worker jobs include:

```text
market scanning

feature calculation

anomaly detection

signal generation

cross-market matching

Agent analysis

maintenance
```

Do not introduce Celery automatically.

Begin with simple workers and Redis/database-backed coordination.

Introduce a job queue only when the workload requires one.

---

# Agent Layer

The Agent layer is downstream from deterministic analytics.

Preferred pipeline:

```text
Market Data
    ↓
Normalized Historical Data
    ↓
Deterministic Analytics
    ↓
Signals
    ↓
Market Selection
    ↓
Context Builder
    ↓
Agent
    ↓
Structured Decision
```

Do not ask an LLM to calculate metrics that can be produced deterministically.

Prefer:

```text
raw data
    ↓
Python calculations
    ↓
structured metrics
    ↓
LLM interpretation
```

Avoid:

```text
huge raw API payload
    ↓
LLM
    ↓
unsupported numerical conclusion
```

---

# Structured Agent Output

Agent responses must use schema-validated structured output.

Conceptually:

```python
class AgentDecision(BaseModel):
    action: Literal[
        "IGNORE",
        "WATCH",
        "INVESTIGATE",
    ]

    confidence: float
    thesis: str
    key_signals: list[str]
    risk_flags: list[str]
```

Validate:

```text
0.0 <= confidence <= 1.0
```

Initial actions:

```text
IGNORE
WATCH
INVESTIGATE
```

Do not introduce automatic trade execution into the MVP.

---

# React Frontend

React owns the customer-facing presentation layer.

Default stack:

```text
React
TypeScript
Vite
TanStack Query
Tailwind CSS
ECharts or Lightweight Charts
```

Vite is preferred unless server-side rendering becomes a real requirement.

Potential pages:

```text
Market Explorer
Market Detail
Movers
Signal Feed
Anomaly Feed
Cross-Market Comparison
Agent Analysis

Watchlists
Alerts

Account
Organization
Members
Billing
```

The frontend must never directly access:

```text
Polymarket
Kalshi
ClickHouse
PostgreSQL
Redis
Rust collector
```

Frontend data flows through Django APIs.

---

# Storage Strategy

Each storage engine has a specific responsibility.

```text
PostgreSQL
    transactional truth

ClickHouse
    analytical history

Redis
    ephemeral live state
```

Do not collapse these responsibilities simply to reduce infrastructure count.

---

# ClickHouse

ClickHouse stores high-volume analytical history.

Typical datasets:

```text
market_snapshots

trades

orderbook_events

market_candles_1m

market_candles_5m

market_candles_15m

market_candles_1h

market_candles_1d

signals

features

cross_market_observations
```

Prefer:

- MergeTree-family engines;
- appropriate ORDER BY keys;
- sensible partitions;
- batch insertion;
- materialized views;
- TTL policies;
- rollups.

Avoid scanning raw event tables for every dashboard request.

---

# PostgreSQL

PostgreSQL stores transactional application state.

Typical models:

```text
User
UserProfile
UserPreference
AuthIdentity

Organization
OrganizationMembership
OrganizationInvite

Market
Event
Category
MarketMapping

Watchlist
Alert

APIKey

AgentConfiguration
AgentRun

Plan
BillingCustomer
Subscription
Entitlement

AuditLog
```

Persistent PostgreSQL schema changes MUST use Django migrations.

---

# Redis

Redis stores current state and transient coordination data.

Potential keys:

```text
market:{platform}:{market_id}

signal:latest:{market_id}

orderbook:summary:{market_id}

collector:status:{source}
```

Use TTLs where appropriate.

Do not allow disposable cache keys to accumulate indefinitely.

---

# Normalized Market Model

Polymarket and Kalshi must be normalized before downstream analytics consume their data.

Conceptual model:

```text
platform

market_id

event_id

title

description

category

status

open_time

close_time

resolution_time

probability

best_bid

best_ask

spread

volume

volume_24h

liquidity

timestamp
```

Platform-specific raw payloads may be retained separately.

Analytics should not depend directly on arbitrary exchange JSON.

---

# Probability Semantics

Do not assume the following are interchangeable:

```text
last trade price

midpoint

best bid

best ask

implied probability
```

The source and calculation for every probability metric must be explicit.

Potential metrics:

```text
probability_change_1m

probability_change_5m

probability_change_15m

probability_change_1h

probability_change_6h

probability_change_24h

probability_velocity

probability_acceleration

probability_volatility
```

---

# Market Candles

Support prediction-market candles.

Conceptual schema:

```text
platform

market_id

interval

timestamp

probability_open

probability_high

probability_low

probability_close

volume

trade_count

avg_spread

max_spread

avg_liquidity
```

Potential intervals:

```text
1m
5m
15m
1h
6h
1d
```

Prefer ClickHouse materialized rollups where appropriate.

---

# Signal Framework

Signals should be deterministic and explainable whenever possible.

Initial signal types may include:

```text
PROBABILITY_SPIKE

PROBABILITY_DROP

MOMENTUM

REVERSAL

VOLUME_SPIKE

TRADE_ACTIVITY_SPIKE

SPREAD_WIDENING

SPREAD_COMPRESSION

LIQUIDITY_DROP

LIQUIDITY_SPIKE

ORDERBOOK_IMBALANCE

CROSS_MARKET_DIVERGENCE
```

Example:

```json
{
  "signal_type": "PROBABILITY_SPIKE",
  "platform": "polymarket",
  "market_id": "example-market",
  "timestamp": "2026-01-01T12:00:00Z",
  "score": 0.91,
  "metrics": {
    "probability_change_1h": 0.12,
    "volume_zscore": 4.6
  }
}
```

Every signal should be reproducible from stored data.

---

# Market Selection

Do not send every market to the Agent layer.

Use deterministic filtering and ranking first.

Potential ranking factors:

```text
volume

volume acceleration

liquidity

spread

probability movement

unusual activity

time to expiry

market relevance

cross-market divergence
```

Agent analysis should operate on a useful subset.

This reduces:

- token usage;
- latency;
- cost;
- noise.

---

# Cross-Market Analysis

Quanthecy should eventually match equivalent or strongly related markets across platforms.

```text
Polymarket
     │
     ▼
Market Matcher
     ▲
     │
Kalshi
```

Potential metrics:

```text
probability_difference

spread_adjusted_difference

liquidity_difference

volume_difference

movement_lead_lag
```

Do not automatically classify probability differences as arbitrage.

Consider:

```text
wording
expiry
settlement rules
resolution sources
contract structure
fees
liquidity
```

Store match confidence.

---

# API Design

Django Ninja APIs should be versioned.

Examples:

```text
GET /api/v1/markets

GET /api/v1/markets/{id}

GET /api/v1/markets/{id}/history

GET /api/v1/markets/{id}/signals

GET /api/v1/markets/{id}/analysis

GET /api/v1/signals

GET /api/v1/movers

GET /api/v1/anomalies

GET /api/v1/cross-markets
```

Customer endpoints may include:

```text
GET /api/v1/me

GET /api/v1/organizations

GET /api/v1/organizations/{id}

GET /api/v1/organizations/{id}/members

GET /api/v1/organizations/{id}/watchlists

GET /api/v1/organizations/{id}/alerts

GET /api/v1/organizations/{id}/subscription

GET /api/v1/organizations/{id}/usage
```

Use pagination for large result sets.

Do not return raw database models.

---

# Realtime API

Realtime frontend delivery may use:

```text
SSE
WebSocket
```

Prefer SSE for straightforward server-to-client feeds.

Use WebSocket when genuine bidirectional subscription management is required.

React should receive normalized application events.

Example:

```json
{
  "type": "market_update",
  "market_id": "abc",
  "probability": 0.67,
  "volume_24h": 1839200,
  "timestamp": "2026-01-01T12:00:00Z"
}
```

Do not forward raw exchange WebSocket events directly to browsers.

---

# Repository Structure

Use a monorepo.

Preferred structure:

```text
quanthecy/
├── AGENTS.md
├── README.md
├── LICENSE
├── Makefile
│
├── compose.yaml
├── compose.dev.yaml
├── compose.prod.yaml
├── .env.example
│
├── apps/
│   ├── web/
│   │   ├── Dockerfile
│   │   └── src/
│   │
│   └── backend/
│       ├── Dockerfile
│       ├── manage.py
│       │
│       ├── config/
│       │   ├── settings/
│       │   ├── urls.py
│       │   └── asgi.py
│       │
│       └── quanthecy/
│           ├── accounts/
│           ├── organizations/
│           ├── markets/
│           ├── watchlists/
│           ├── alerts/
│           ├── billing/
│           ├── agents/
│           ├── audit/
│           └── api/
│
├── services/
│   └── market-data/
│       ├── Dockerfile
│       ├── Cargo.toml
│       └── src/
│
├── python/
│   └── quanthecy_analytics/
│       ├── analytics/
│       ├── signals/
│       ├── agents/
│       ├── storage/
│       ├── workers/
│       └── backtest/
│
├── infra/
│   ├── clickhouse/
│   ├── postgres/
│   └── proxy/
│
├── tests/
│
├── examples/
│
└── docs/
```

Avoid unnecessary microservices.

---

# Domain-Oriented Django Apps

Prefer Django apps organized around business domains:

```text
accounts

organizations

markets

watchlists

alerts

billing

agents

audit
```

Avoid dumping unrelated logic into generic modules such as:

```text
utils

misc

common_models
```

unless code is truly cross-domain.

---

# Containerization

Containerization is a first-class requirement.

A developer should not need to install:

```text
Rust
Python
Node.js
PostgreSQL
Redis
ClickHouse
```

directly on the host.

The project should support:

```bash
docker compose up --build
```

or:

```bash
make up
```

---

# Docker Compose

Docker Compose is the default orchestrator for:

- local development;
- integration testing;
- demos;
- staging;
- initial single-server production.

Core services:

```text
web

backend

worker

market-data

postgres

clickhouse

redis
```

Optional:

```text
reverse-proxy
```

---

# Compose Files

Prefer:

```text
compose.yaml

compose.dev.yaml

compose.prod.yaml
```

`compose.yaml` contains shared configuration.

Development overrides may include:

```text
bind mounts
hot reload
debug ports
development commands
```

Production overrides may include:

```text
restart policies
production images
restricted ports
resource limits
reverse proxy
```

Avoid duplicating entire Compose files unnecessarily.

---

# Local Development

Expected setup:

```bash
git clone <repository>

cd quanthecy

cp .env.example .env

docker compose up --build
```

Expected development services:

```text
Web
http://localhost:3000

Backend
http://localhost:8000

API Documentation
http://localhost:8000/api/docs

Django Admin
http://localhost:8000/admin
```

---

# Backend Container

Django production containers must use a production-capable ASGI server.

Possible deployment:

```text
uvicorn
```

or an appropriate production process manager.

Do not use:

```bash
python manage.py runserver
```

in production.

The backend container should:

- expose health endpoints;
- handle graceful termination;
- avoid running background analytics loops;
- use explicit migration deployment procedures.

---

# Worker Container

The worker may use the same Python image as Django.

Different commands should start separate workloads.

Conceptually:

```text
same Python image

backend
    → ASGI application

worker
    → analytics worker
```

Do not run both as one process.

---

# Rust Container

Use a multi-stage Docker build.

```text
Rust builder
    ↓
cargo build --release
    ↓
copy executable
    ↓
minimal runtime image
```

The production image should not contain the full Rust compiler toolchain.

The collector must support graceful shutdown.

---

# React Container

Use a multi-stage build.

```text
Node builder
    ↓
frontend build
    ↓
static assets
    ↓
minimal web server
```

Do not use the Vite development server in production.

---

# Persistent Volumes

Persistent services must use named volumes or externally managed storage.

Examples:

```text
postgres_data

clickhouse_data

redis_data
```

Running:

```bash
docker compose down
```

must not destroy persistent storage.

Destructive cleanup should require:

```bash
docker compose down -v
```

or another explicit destructive command.

---

# Health Checks

Important services should expose useful health checks.

Examples:

```text
Django
    /health

Rust Collector
    /health
    /ready

PostgreSQL
    pg_isready

Redis
    PING

ClickHouse
    ping
```

Differentiate between:

```text
alive
ready
```

when appropriate.

---

# Dependency Recovery

Services must tolerate dependencies temporarily being unavailable.

Implement where appropriate:

```text
retry

reconnect

exponential backoff

graceful recovery
```

Do not assume Docker startup order means a dependency is ready.

---

# Production Exposure

Production should preferably expose only:

```text
80
443
```

through a reverse proxy.

Do not publicly expose:

```text
PostgreSQL

Redis

ClickHouse

Rust internal operational endpoints
```

without an explicit secure requirement.

---

# Initial Production Deployment

The initial production target is:

> **One Linux server running Docker Compose.**

Do not introduce Kubernetes into the MVP.

Conceptually:

```text
Internet
   │
   ▼
Reverse Proxy
   │
   ├── React
   │
   └── Django
          │
    ┌─────┼─────────┐
    ▼     ▼         ▼
 Redis Postgres ClickHouse
                  ▲
                  │
             Rust Collector

             Python Worker
```

---

# Kubernetes Boundary

Do not add Kubernetes merely to appear production-grade.

Consider Kubernetes only when there is a demonstrated need for:

```text
multiple production hosts

horizontal scaling

automated workload placement

rolling multi-host deployments

large service count

stronger orchestration requirements
```

Do not add during MVP:

```text
Helm

service mesh

operators

Kubernetes manifests
```

unless explicitly requested.

---

# Configuration

Environment-dependent values must come from configuration.

Provide:

```text
.env.example
```

Potential settings:

```text
DJANGO_SECRET_KEY=
DJANGO_DEBUG=
DJANGO_ALLOWED_HOSTS=

POSTGRES_URL=

CLICKHOUSE_URL=
CLICKHOUSE_DATABASE=
CLICKHOUSE_USER=
CLICKHOUSE_PASSWORD=

REDIS_URL=

POLYMARKET_API_URL=
POLYMARKET_WS_URL=

KALSHI_API_URL=
KALSHI_WS_URL=
KALSHI_API_KEY_ID=
KALSHI_PRIVATE_KEY_PATH=

OPENAI_API_KEY=
```

Never commit production secrets.

---

# Data Quality

Prediction-market APIs may contain:

```text
stale data

missing fields

duplicate events

reconnect gaps

out-of-order events

malformed payloads

temporary failures

exchange-specific semantics
```

Collectors must implement:

```text
retries

reconnect logic

deduplication

timestamp validation

schema validation

observability
```

Never silently substitute invalid numeric values with zero.

Prefer explicit nullability where appropriate.

---

# Timestamp Rules

Use UTC internally.

Persist UTC timestamps.

Expose ISO-8601 timestamps through APIs.

Frontend localization happens at presentation time.

Do not perform analytics with mixed local timezones.

---

# Numeric Precision

Use precision appropriate to each domain.

Floating-point values may be appropriate for analytical probability calculations.

Use exact decimal or fixed-point representations for values such as:

```text
billing amounts

fees

settlement amounts

balances
```

---

# Testing

Every meaningful component should be independently testable.

## Rust

Test:

```text
API parsing

normalization

deduplication

malformed payload handling

snapshot generation

reconnect behavior
```

Normal tests should use fixtures rather than requiring live exchanges.

---

## Django / Python

Test:

```text
custom User manager

case-insensitive email uniqueness

User creation

superuser creation

Organization creation

Membership uniqueness

owner protection

tenant isolation

permission rules

organization invitations

API-key hashing

API endpoints

services

repositories

signals

analytics

Agent context generation
```

LLM calls must be mocked during normal unit tests.

Billing-provider calls must be mocked.

---

# Required Identity Tests

The following behaviors should have explicit tests.

```text
alice@example.com and Alice@example.com cannot become different users

create_superuser creates valid staff/superuser state

new personal organization gets an OWNER membership

same user cannot have duplicate membership in one organization

user can belong to multiple organizations

VIEWER cannot perform ADMIN operations

organization owner does not automatically become Django staff

Django staff does not automatically gain customer Organization membership

organization-scoped API cannot retrieve another organization's resource

last organization owner cannot leave without explicit ownership handling

external identity is unique by provider + subject
```

---

# React Testing

Test:

```text
API state transformations

loading states

error states

critical views

organization switching

important user interactions
```

---

# Fixtures

Store representative exchange fixtures where appropriate.

Example:

```text
tests/
└── fixtures/
    ├── polymarket/
    │   ├── markets.json
    │   ├── orderbook.json
    │   └── trades.json
    │
    └── kalshi/
        ├── markets.json
        ├── orderbook.json
        └── trades.json
```

Keep fixtures small and sanitized.

---

# Observability

Use structured logging.

Rust should use:

```text
tracing
```

Python/Django logs should be container-friendly.

Useful context may include:

```text
service

request_id

user_id

organization_id

platform

market_id

component

event_type

error_type
```

Do not log secrets.

Do not log complete high-frequency exchange payloads by default.

Potential metrics:

```text
collector_messages_total

collector_errors_total

collector_reconnects_total

clickhouse_insert_rows_total

clickhouse_insert_failures_total

markets_active

signals_generated_total

agent_requests_total

agent_failures_total

api_requests_total

api_request_duration

worker_jobs_total

worker_failures_total
```

---

# Performance Principles

Optimize based on measured workload.

Important rules:

```text
batch ClickHouse inserts

avoid one insert per WebSocket event

avoid unnecessary JSON transformations

avoid reading entire historical datasets into memory

aggregate inside ClickHouse where useful

paginate API responses

cache current state

avoid Django N+1 queries

use select_related / prefetch_related appropriately

keep expensive analytics out of request handlers
```

Do not prematurely add:

```text
Kafka

RabbitMQ

Celery

Kubernetes

gRPC

service mesh
```

without demonstrated requirements.

---

# Rust / Python Boundary

Do not use PyO3 by default.

Preferred integration:

```text
Rust
  ↓
ClickHouse / Redis / PostgreSQL
  ↓
Python / Django
```

Only introduce direct language bindings for demonstrated performance requirements.

---

# Service Communication

Avoid unnecessary synchronous service-to-service RPC.

Prefer:

```text
Rust
  ↓
storage
  ↓
Python
```

over:

```text
Rust
  ↓ HTTP
Python
  ↓ HTTP
Rust
```

Do not introduce gRPC during the MVP without a concrete need.

---

# Coding Standards

## General

Prefer:

```text
explicit types

small modules

deterministic behavior

clear boundaries

structured errors

testable functions

explicit dependencies
```

Avoid:

```text
giant utility modules

global mutable state

hidden side effects

duplicate domain models

undocumented thresholds

speculative infrastructure
```

---

# Rust Standards

Before completing Rust changes:

```bash
cargo fmt --check
cargo clippy --all-targets --all-features
cargo test
```

Do not suppress Clippy warnings without justification.

---

# Python Standards

Preferred tooling:

```text
ruff
pytest
pyright
```

Before completing Python changes:

```bash
ruff check .
pytest
```

Run the configured type checker.

Public Python interfaces should have type annotations.

---

# Django Standards

Keep Django applications domain-oriented.

Avoid meaningful business workflows hidden inside:

```text
model save()

Django signals

API route handlers

schema validation
```

Prefer explicit application/service functions.

Django signals should be used sparingly.

Important workflows such as:

```text
register user

create organization

invite member

accept invitation

change membership role

transfer ownership

create API key

change subscription
```

should use explicit transactional services.

---

# Transaction Boundaries

Multi-model business workflows should use explicit database transactions.

Examples:

```text
user registration + personal organization creation

organization creation + owner membership

invite acceptance + membership creation

ownership transfer

subscription state update
```

Do not rely on a chain of model signals to preserve transactional correctness.

---

# Database Migration Rules

PostgreSQL changes require Django migrations.

Do not silently modify already-applied migrations after release.

ClickHouse schema changes must also be explicit and reviewable.

Destructive migrations require documentation.

---

# CI Expectations

CI should eventually run:

```text
Rust
    cargo fmt --check
    cargo clippy
    cargo test

Python / Django
    ruff
    typecheck
    pytest
    migration consistency check

Frontend
    lint
    typecheck
    tests
    build

Docker
    build production images
```

A feature that works locally but breaks the production image is incomplete.

---

# Documentation

README should explain:

1. what Quanthecy does;
2. supported prediction markets;
3. architecture;
4. technology decisions;
5. identity and organization model;
6. normalized market model;
7. storage architecture;
8. signal framework;
9. Agent framework;
10. Django application architecture;
11. local Docker setup;
12. production deployment;
13. example output.

Use concrete diagrams and data flows.

---

# MVP Scope

The initial MVP should focus on:

```text
1. Polymarket ingestion

2. Kalshi ingestion

3. normalized market schema

4. ClickHouse historical storage

5. PostgreSQL application metadata

6. Redis live state

7. probability history

8. market ranking

9. anomaly detection

10. signal framework

11. structured single-Agent analysis

12. Django backend

13. Django Ninja API

14. Django Admin

15. custom UUID/email-based User model

16. custom UserManager

17. Organization model

18. OrganizationMembership model

19. personal Organization workflow

20. basic Organization authorization

21. React dashboard

22. Python analytics worker

23. Docker images

24. Docker Compose environment

25. single-server deployment

26. README

27. sample outputs

28. tests
```

Full billing does not need to be implemented during the first MVP.

The architecture must still preserve the Organization-level billing boundary.

---

# Explicitly Out of Scope for MVP

Do not introduce unless explicitly requested:

```text
autonomous trading

wallet management

exchange execution

complex multi-Agent debate systems

full billing implementation

enterprise SSO

fine-grained custom RBAC

Kafka

Kubernetes

service mesh

distributed microservice architecture
```

---

# Safety and Trading Boundary

Quanthecy begins as an analytics and research system.

Default behavior:

```text
observe

collect

normalize

analyze

rank

detect

compare

explain
```

Not:

```text
execute trades

move funds

manage wallets
```

Future execution functionality must be isolated behind explicit interfaces.

---

# Development Priorities

When choosing between solutions, prioritize:

```text
1. Correctness

2. Data integrity

3. Tenant isolation

4. Security

5. Clear architecture

6. Long-term maintainability

7. Reproducible deployment

8. Observability

9. Testability

10. Performance

11. Developer convenience
```

---

# Rules for Coding Agents

When modifying this repository:

1. Read this file before making architectural changes.
2. Preserve Data Plane / Control Plane / Intelligence Plane separation.
3. Django + Django Ninja is the canonical public backend.
4. Do not introduce FastAPI as a second public backend.
5. Rust owns exchange ingestion and real-time collection.
6. Python owns analytics and Agent logic.
7. Django ORM manages PostgreSQL application state.
8. Do not force ClickHouse through Django ORM.
9. React must not access infrastructure databases directly.
10. The project must use a custom User model from the first migration.
11. User primary keys must use UUID.
12. Email is the human login identifier.
13. Email uniqueness must be enforced case-insensitively at the database level.
14. Do not reintroduce Django username as a required login identifier.
15. Keep the User model minimal.
16. Do not add billing, preference, organization, or provider-specific fields directly to User without justification.
17. External identities belong in AuthIdentity.
18. User and Organization must remain many-to-many through Membership.
19. Do not add a direct single `organization` field to User.
20. Organization is the primary tenant boundary.
21. Billing belongs to Organization, not User.
22. Organization permissions are independent of Django `is_staff` and `is_superuser`.
23. Never treat an Organization owner as Django staff automatically.
24. Never grant Django staff automatic membership in customer Organizations.
25. All organization-owned resources must enforce tenant isolation server-side.
26. Avoid unscoped organization-resource queries in customer-facing code.
27. Keep billing-provider code behind an integration boundary.
28. Never store raw API key secrets.
29. Keep API handlers thin.
30. Keep expensive analytics outside request processes.
31. Use explicit transactions for multi-model workflows.
32. Avoid using Django signals for core business workflows.
33. Keep deterministic calculations outside LLM reasoning.
34. Every independently deployable service must be containerized.
35. Keep `docker compose up` as a supported development path.
36. Do not introduce Kubernetes during MVP.
37. Do not introduce Kafka without a measured requirement.
38. Do not introduce Celery merely because Django is used.
39. Never commit secrets.
40. Use migrations for persistent schema changes.
41. Do not expose PostgreSQL, Redis, or ClickHouse publicly in production.
42. Add tests for meaningful business logic.
43. Test tenant isolation explicitly.
44. Update documentation when architecture or public behavior changes.
45. Production services must handle graceful shutdown.
46. Treat historical prediction-market data as a core project asset.
47. Do not implement automatic trading unless explicitly requested.

---

# Identity Architecture Summary

The intended identity architecture is:

```text
                    User
                 UUID identity
                      │
        ┌─────────────┼─────────────┐
        │             │             │
        ▼             ▼             ▼
 UserProfile    UserPreference  AuthIdentity
                                    │
                            Google / GitHub /
                            OIDC / other
                      │
                      │
                      ▼
          OrganizationMembership
                      │
                      ▼
                Organization
                      │
          ┌───────────┼───────────────┐
          │           │               │
          ▼           ▼               ▼
      Watchlists    API Keys     Subscription
          │                           │
        Alerts                    Entitlements
                                      │
                                    Usage
```

Core semantics:

```text
User
    a person or authentication identity

Organization
    a customer workspace / tenant

Membership
    relationship and authorization

AuthIdentity
    external authentication linkage

Subscription
    organization billing

Entitlement
    organization product capability
```

---

# Guiding Principle

The core Quanthecy market-data path is:

```text
Reliable Market Data
        ↓
Normalized Historical Dataset
        ↓
Deterministic Analytics
        ↓
Explainable Signals
        ↓
Structured Agent Reasoning
        ↓
Prediction-Market Intelligence
```

The application architecture is:

```text
Rust
    Data Plane

Django
    Application / Control Plane

Python
    Intelligence Plane

React
    Presentation Plane
```

The identity architecture is:

```text
User
    Identity

Organization
    Tenant

Membership
    Authorization

Subscription
    Billing
```

The storage philosophy is:

```text
PostgreSQL
    application truth

ClickHouse
    analytical history

Redis
    realtime state
```

The deployment philosophy is:

> **Containers first. Compose first. Complexity only when justified.**

The Agent is not the foundation of Quanthecy.

The foundation is:

> **reliable data, reproducible analytics, correct identity boundaries, tenant isolation, stable application architecture, and clear system ownership.**