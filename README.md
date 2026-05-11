# Plan2Sprint

**AI-Powered Sprint Planning**

Plan2Sprint integrates with Jira, Azure DevOps, GitHub, Slack, and Microsoft Teams to deliver intelligent sprint planning, real-time health signals, automated standups, project-channel workflows, and cross-tool observability. Multi-tenant by design with org-scoped data isolation, role-based access controls, and a defence-in-depth security model.

---

## Table of Contents

- [Key Features](#key-features)
- [Tech Stack](#tech-stack)
- [Architecture](#architecture)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
- [Environment Variables](#environment-variables)
- [API Reference](#api-reference)
- [Database Schema](#database-schema)
- [Role-Based Access Control](#role-based-access-control)
- [Multi-Tenant Architecture](#multi-tenant-architecture)
- [Security](#security)
- [Integration Layer](#integration-layer)
- [Background Jobs](#background-jobs)
- [Deployment](#deployment)

---

## Key Features

### AI Sprint Planning
- AI-powered sprint optimization with composite confidence scoring (velocity, CI/CD throughput, AI plan baseline, target-launch feasibility, sprint reliability)
- Automatic skill-to-task matching and workload balancing
- Spillover risk assessment and success probability forecasting
- Sprint rebalancing — recommends realistic target-launch shifts when the plan ends past the committed date
- One-click approval with batched write-back to Jira / Azure DevOps

### Project Timeline & Lifecycle Tracking
- 7-phase project lifecycle (Discovery & Design → Core Development → Integration & APIs → Testing & QA → Deployment & Launch → UAT & Staging → Ready)
- AI phase classifier assigns features to phases automatically
- Descendant-aware phase inference — phase activity tracked through both feature status AND underlying work-item progress
- Phase-aware Sprint Completion hero (Current Sprint / Sprint Progress / Upcoming Sprint)
- Target Launch date — hover-editable on the hero card, auto-set on plan approval, persisted across plan regenerations when manually overridden

### Past-Target-Launch Alerts
- Red "OVERDUE" tile + "PLAN OVERDUE" badge when target_launch_date passes with incomplete work
- "Project Cycle Concluded" card on the retrospective page summarising completed vs outstanding scope
- Once-only email to the PO when a project first crosses its target, idempotent per (project, target_date) pair
- Auto-clears when a new target date is set or the project completes

### Team Health Monitoring
- 8 real-time health signal types: burnout risk, velocity variance, stalled tickets, review lag, CI failure, after-hours activity, inactivity, capacity overload
- RAG (Red/Amber/Green) severity indicators per signal
- Automatic escalation workflows via Slack and Microsoft Teams

### Standup Automation
- Auto-generated standups from synced work items, PRs, and commits
- 7-day rolling window so recently-closed items always surface
- Blocker auto-resolution when the underlying ticket reaches a terminal status
- "Send to Slack" / "Send to Teams" split button on the standup view — posts an overview to the project's channel + Plan2Sprint deep-link
- Blocker flagging with Adaptive Card actions (Escalate / Resolve) directly from Slack/Teams
- Multi-TeamMember identity merging so a single human with duplicate TM rows shows as one row

### Slack / Microsoft Teams Parity
- Platform tab switcher on Channels page — PO chooses Slack or Teams; setting persists in localStorage
- Auto-created project channels (`proj-{name}` in Slack, `{name}-P2S` channel inside a chosen parent Team in Microsoft Teams)
- Team auto-invited to project channels
- Quick Actions per platform: announcement, sprint plan share, blocker, standup, custom message
- Async-ack pattern on Slack interactive endpoint — returns within Slack's 3-second deadline even on cold-start, then updates the message via `response_url`
- Microsoft Teams Adaptive Cards with signed Escalate / Resolve action URLs
- Per-user Microsoft / Slack identity linking via `/me/connect` endpoints (developers and stakeholders OAuth their own personal account so DMs route to the right person, separately from the org-level bot connection)

### GitHub Monitoring
- Pull request tracking with CI status, review state, and linked work items
- Commit activity feed with developer, type, and time-range filters
- Aggregate metrics: repos, open PRs, merged PRs, commits per sprint
- Webhook-driven real-time updates (commits → work item status, PR merge → DONE, CI failure → health signal)

### Retrospective & Failure Analysis
- AI-driven root-cause analysis for missed sprint goals
- What went well / what didn't go well categorization
- Action items with carry-forward tracking across sprints
- Project Cycle Concluded card for projects past their target launch

### Multi-Tool Integration
- OAuth 2.0 flows for Jira (3LO), Azure DevOps, GitHub, Slack, and Microsoft Teams
- PAT-based ADO connection with intelligent error detection (`expired` / `not_found` / `scope` reasons surfaced explicitly from ADO's response body)
- Webhook-based real-time data sync with signature verification on every endpoint
- Field normalization across all source tools
- Batch write-back with 60-minute undo window
- Full audit logging for every integration event

### Notification System
- Multi-channel delivery: Slack, Microsoft Teams, Email, In-App
- Adaptive card templates for rich notifications
- Cron-scheduled daily digest (9 AM IST) + evening summary (5 PM IST) + Friday weekly PDF report
- Idempotent per-project past-target-launch email to PO
- Per-user channel + notification preferences

### Real-Time Dashboards
- WebSocket-powered live updates across all dashboard panels
- Redis-backed event bus for cross-replica event propagation (`blocker_status_changed`, `channel_created`, `join_request_resolved`, etc.)
- Three role-specific dashboards: Product Owner (10 panels), Developer (8 panels), Stakeholder (6 panels)
- Project-scoped views with persistent project selection per user
- Velocity Δ guards: same-unit requirement, minimum-baseline check, ±200% display cap (no more "+33,200%" edge cases)

### Smart Notes
- Per-project notes editor with rich formatting
- Tied to the selected project, accessible from every dashboard via the Notes button

---

## Tech Stack

### Frontend
| Technology | Version | Purpose |
|-----------|---------|---------|
| Next.js | 15.5+ | React framework (App Router) |
| React | 19 | UI library |
| TypeScript | 5.7 | Type safety |
| Tailwind CSS | 4 | Utility-first styling |
| Framer Motion | 12 | Animations and transitions |
| Recharts | 3 | Dashboard charts and graphs |
| TanStack React Table | 8 | Data tables |
| React Hook Form + Zod | 7 / 3 | Form handling and validation |
| Supabase SSR (`@supabase/ssr`) | 0.8 | Authentication (PKCE flow) |
| Lucide React | 0.469 | Icon library |
| Sonner | 2 | Toast notifications |

### Backend
| Technology | Version | Purpose |
|-----------|---------|---------|
| FastAPI | 0.115 | Async Python web framework |
| Python | 3.12+ | Runtime |
| SQLAlchemy | 2.0+ (async) | ORM |
| asyncpg | 0.30 | PostgreSQL async driver |
| Alembic | 1.14 | Database migrations |
| Pydantic | 2.10 (+ pydantic-settings) | Request/response validation, env config |
| httpx | 0.28 | Async HTTP client for integrations |
| python-jose | 3.3 | JWT verification |
| redis-py | 5.0+ | Redis async client |

### AI Models
| Model | Provider | Purpose |
|-------|----------|---------|
| Grok-4-Fast-Reasoning | Azure AI Foundry | Primary model (sprint planning, retrospectives, narrative generation) |
| o4-mini | Azure OpenAI | Secondary / reasoning-heavy fallback (rebalancer, predictability) |
| Claude (Anthropic SDK) | Anthropic | Legacy — kept for compatibility, not in active call path |

### Infrastructure
| Technology | Purpose |
|-----------|---------|
| Supabase | Auth (Google / Microsoft OAuth) + PostgreSQL |
| Azure Container Apps | Production hosting (API + Web) with KEDA cron-based scaling |
| Azure Container Registry | Image registry |
| Azure Cache for Redis Enterprise | Event bus + distributed locks (TLS, port 10000) |
| Azure Key Vault | All production secrets (OAuth client secrets, PATs, webhook secrets, encryption keys) referenced via system-assigned managed identity |
| WebSocket | Real-time dashboard updates |
| SMTP (configurable) | Transactional emails (digests, alerts, weekly reports) |

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                        FRONTEND                              │
│                   Next.js 15 (App Router)                    │
│                                                              │
│   ┌──────────┐  ┌──────────┐  ┌──────────────┐               │
│   │    PO    │  │   Dev    │  │ Stakeholder  │  Dashboards   │
│   │ 10 panels│  │ 8 panels │  │  6 panels    │               │
│   └──────────┘  └──────────┘  └──────────────┘               │
│                                                              │
│   ┌──────────────────────────────────────────┐               │
│   │  Integration UI  │  Auth  │  Settings    │               │
│   └──────────────────────────────────────────┘               │
│                        │                                     │
│                   /api/* proxy                               │
└────────────────────────┼─────────────────────────────────────┘
                         │
┌────────────────────────┼─────────────────────────────────────┐
│                    BACKEND                                   │
│                 FastAPI (Python 3.12)                        │
│                                                              │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌───────────┐    │
│   │ Routers  │  │ Services │  │ Adapters │  │  Models   │    │
│   │ 20+ APIs │  │ AI Plan  │  │ Jira     │  │ 30+ tables│    │
│   │          │  │ Standups │  │ ADO      │  │           │    │
│   │          │  │ Health   │  │ GitHub   │  │           │    │
│   │          │  │ Forecast │  │ Slack    │  │           │    │
│   │          │  │ Notifs   │  │ Teams    │  │           │    │
│   │          │  │ Cron     │  │          │  │           │    │
│   └──────────┘  └──────────┘  └──────────┘  └───────────┘    │
│                        │                                     │
└────────────────────────┼─────────────────────────────────────┘
                         │
       ┌─────────────────┼─────────────────────┐
       │                 │                     │
┌──────▼──────┐   ┌──────▼──────┐    ┌─────────▼─────────┐
│  Supabase   │   │ Azure Cache │    │  External tools   │
│   Auth +    │   │ for Redis   │    │  Jira, ADO,       │
│  Postgres   │   │ Enterprise  │    │  GitHub, Slack,   │
└─────────────┘   │ (events +   │    │  Teams (OAuth +   │
                  │  locks)     │    │  webhooks)        │
                  └─────────────┘    └───────────────────┘
```

### Route Groups
- `(marketing)` — Public landing page
- `(auth)` — Login, signup, forgot password (PKCE OAuth + email/password)
- `(app)` — Authenticated shell with sidebar + topbar; role-segregated route guards on `/po`, `/dev`, `/stakeholder`

### API Proxy
All `/api/*` requests from the frontend are proxied to the FastAPI backend via Next.js rewrites configured in `next.config.ts`. In production, both the Web and API containers run in the same Azure Container Apps environment.

### Cross-Replica Event Flow
Redis Streams (`events:all`) propagate WebSocket events between replicas so a broadcast initiated on replica A reaches a client connected to replica B. Distributed locks coordinate cron-fired jobs so the daily digest doesn't fire twice when KEDA scales to >1 replica.

---

## Project Structure

```
plan2sprint/
├── apps/
│   ├── api/                              # FastAPI Backend
│   │   ├── app/
│   │   │   ├── main.py                   # App setup, CORS, lifespan
│   │   │   ├── config.py                 # Pydantic settings
│   │   │   ├── database.py               # Async SQLAlchemy engine
│   │   │   ├── auth/                     # Supabase JWT middleware
│   │   │   ├── models/                   # 30+ SQLAlchemy ORM models
│   │   │   ├── routers/                  # API endpoint handlers
│   │   │   │   ├── analytics.py
│   │   │   │   ├── dashboard.py
│   │   │   │   ├── sprints.py
│   │   │   │   ├── standups.py
│   │   │   │   ├── github.py
│   │   │   │   ├── team_health.py
│   │   │   │   ├── notifications.py
│   │   │   │   ├── projects.py
│   │   │   │   ├── organizations.py
│   │   │   │   ├── writeback.py
│   │   │   │   ├── retrospectives.py
│   │   │   │   ├── ws.py
│   │   │   │   └── integrations/         # OAuth + sync + webhooks
│   │   │   │       ├── connections.py
│   │   │   │       ├── sync.py
│   │   │   │       ├── jira.py
│   │   │   │       ├── ado.py
│   │   │   │       ├── github.py
│   │   │   │       ├── slack.py
│   │   │   │       ├── teams.py
│   │   │   │       ├── _slack_channels.py
│   │   │   │       └── _teams_channels.py
│   │   │   ├── services/                 # Business logic
│   │   │   │   ├── ai_sprint_generator.py
│   │   │   │   ├── ai_caller.py
│   │   │   │   ├── ai_phase_classifier.py
│   │   │   │   ├── sprint_forecast.py
│   │   │   │   ├── sprint_rebalancer.py
│   │   │   │   ├── standup_generator.py
│   │   │   │   ├── timeline_engine.py
│   │   │   │   ├── failure_analysis.py
│   │   │   │   ├── predictability_engine.py
│   │   │   │   ├── confidence_engine.py
│   │   │   │   ├── notification_scheduler.py    # cron tick (60s)
│   │   │   │   ├── overdue_alert.py             # past-target email
│   │   │   │   ├── daily_digest.py
│   │   │   │   ├── weekly_report_renderer.py
│   │   │   │   ├── message_router.py
│   │   │   │   ├── project_access.py            # access guard
│   │   │   │   ├── project_status.py
│   │   │   │   ├── org_lookup.py                # canonical name match
│   │   │   │   ├── org_join_flow.py             # founder approval
│   │   │   │   ├── org_join_email.py
│   │   │   │   ├── webhook_security.py          # HMAC + clientState
│   │   │   │   ├── redis_pool.py
│   │   │   │   ├── event_bus.py                 # Redis Streams
│   │   │   │   ├── ws_manager.py
│   │   │   │   └── writeback.py
│   │   │   ├── adapters/                 # External API wrappers
│   │   │   └── email/                    # SMTP sender + templates
│   │   ├── alembic/                      # Database migrations
│   │   ├── tests/                        # Pytest suite (webhook + isolation)
│   │   ├── pyproject.toml
│   │   ├── Dockerfile
│   │   └── .env.example
│   │
│   └── web/                              # Next.js Frontend
│       ├── src/
│       │   ├── app/
│       │   │   ├── globals.css           # Design tokens
│       │   │   ├── (marketing)/          # Landing page
│       │   │   ├── (auth)/               # Login, signup, callback
│       │   │   └── (app)/                # Authenticated shell
│       │   │       ├── po/               # Product Owner (8 pages)
│       │   │       ├── dev/              # Developer (7 pages)
│       │   │       ├── stakeholder/      # Stakeholder (6 pages)
│       │   │       └── settings/         # Settings (4 pages)
│       │   ├── components/
│       │   │   ├── ui/                   # Base UI components
│       │   │   ├── auth/                 # Login form, role guard
│       │   │   ├── dashboard/            # Shared panels & cards
│       │   │   ├── layout/               # Sidebar, topbar
│       │   │   ├── integrations/         # Jira/ADO/GitHub cards
│       │   │   ├── notifications/        # Channels page components
│       │   │   ├── po/                   # PO-specific components
│       │   │   ├── dev/                  # Dev-specific components
│       │   │   ├── stakeholder/          # Stakeholder components
│       │   │   ├── settings/             # Settings components
│       │   │   └── project/              # Access-denied banner
│       │   ├── lib/
│       │   │   ├── auth/                 # AuthProvider + useAuth
│       │   │   ├── supabase/             # Browser + server clients
│       │   │   ├── types/                # TypeScript interfaces
│       │   │   ├── integrations/         # Adapters + write-back
│       │   │   ├── project/              # SelectedProjectContext
│       │   │   ├── ws/                   # WebSocket client
│       │   │   └── fetch-cache.ts        # Request dedup + caching
│       │   └── hooks/                    # React hooks
│       ├── package.json
│       ├── next.config.ts
│       └── Dockerfile
│
├── docker-compose.yml
├── package.json                          # Monorepo root scripts
├── LICENSE
└── README.md
```

---

## Getting Started

### Prerequisites
- **Node.js** 18+ and npm
- **Python** 3.12+
- **Supabase** project (for Auth + PostgreSQL)
- **Redis** (local for development) or **Azure Cache for Redis** (production)
- **Ngrok** (for local OAuth callback tunneling during development)

### Installation

```bash
# Clone the repository
git clone https://github.com/Sangini-spec/Plan2Sprint.git
cd Plan2Sprint

# Install frontend dependencies
cd apps/web
npm install

# Install backend dependencies
cd ../api
python -m venv .venv
source .venv/bin/activate    # On Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

### Environment Setup

```bash
# Copy environment templates
cp apps/api/.env.example apps/api/.env
cp apps/web/.env.example apps/web/.env.local

# Edit both files with your credentials (see Environment Variables section)
```

### Running the Application

Start all three services:

```bash
# Terminal 1 — Backend (FastAPI on port 8000)
cd apps/api
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2 — Frontend (Next.js on port 3000)
cd apps/web
npm run dev

# Terminal 3 — Ngrok (required for OAuth callbacks during local development)
ngrok http 8000 --domain=your-domain.ngrok-free.dev
```

Or use Docker Compose:

```bash
docker compose up --build
```

The application will be available at `http://localhost:3000`.

---

## Environment Variables

### Backend (`apps/api/.env`)

#### Auth & Database
| Variable | Description |
|----------|-------------|
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_ANON_KEY` | Supabase anonymous key |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase service role key |
| `SUPABASE_JWT_SECRET` | JWT secret for token verification |
| `DATABASE_URL` | PostgreSQL connection string (asyncpg) |

#### OAuth Integrations
| Variable | Description |
|----------|-------------|
| `JIRA_CLIENT_ID` / `JIRA_CLIENT_SECRET` | Jira OAuth 3LO credentials |
| `ADO_CLIENT_ID` / `ADO_CLIENT_SECRET` | Azure DevOps OAuth credentials |
| `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` | GitHub App credentials |
| `SLACK_CLIENT_ID` / `SLACK_CLIENT_SECRET` / `SLACK_SIGNING_SECRET` | Slack App credentials |
| `TEAMS_CLIENT_ID` / `TEAMS_CLIENT_SECRET` / `TEAMS_TENANT_ID` | Microsoft Teams (Azure AD) credentials |

#### Webhook Security
| Variable | Description |
|----------|-------------|
| `JIRA_WEBHOOK_SECRET` | HMAC-SHA256 signing secret for Jira webhooks |
| `ADO_WEBHOOK_SECRET` | Shared secret for ADO service-hook `X-Hook-Secret` |
| `TEAMS_WEBHOOK_CLIENT_STATE` | Microsoft Graph subscription clientState |
| `STRICT_WEBHOOK_VERIFICATION` | When `true`, reject webhooks without a configured secret |

#### AI
| Variable | Description |
|----------|-------------|
| `AZURE_AI_KEY` / `AZURE_AI_ENDPOINT` / `AZURE_AI_MODEL` | Primary model (Grok-4-Fast on Azure AI Foundry) |
| `AZURE_AI_KEY_2` / `AZURE_AI_ENDPOINT_2` / `AZURE_AI_MODEL_2` | Secondary model (o4-mini on Azure OpenAI) |
| `ANTHROPIC_API_KEY` | Optional Claude fallback (legacy) |

#### Infrastructure
| Variable | Description |
|----------|-------------|
| `REDIS_URL` | Explicit Redis connection string (preferred when set) |
| `REDIS_ENDPOINT` + `REDIS_KEY` | Azure Cache for Redis Enterprise split form (auto-composed into a `rediss://` URL when `REDIS_URL` is empty) |
| `INTEGRATION_ENCRYPTION_KEY` | Fernet key for OAuth token encryption at rest |
| `FRONTEND_URL` | Frontend origin (default: `http://localhost:3000`) |

#### Email (SMTP)
| Variable | Description |
|----------|-------------|
| `SMTP_HOST` / `SMTP_PORT` | SMTP server |
| `SMTP_USER` / `SMTP_PASS` | SMTP authentication |
| `EMAIL_FROM_ADDRESS` | Sender address for transactional emails |

### Frontend (`apps/web/.env.local`)

| Variable | Description |
|----------|-------------|
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase project URL |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Supabase anonymous key |
| `API_URL` | Backend origin (set at build time for Docker images) |

---

## API Reference

### Dashboard & Analytics
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/analytics` | Velocity trend, predictability, backlog health |
| GET | `/api/dashboard/summary` | Sprint summary stats |
| GET | `/api/dashboard/work-items` | Work items with filters |
| GET | `/api/dashboard/team` | Team member stats |
| GET | `/api/dashboard/sprints` | Active and recent iterations |
| GET | `/api/dashboard/feature-progress` | Feature/module progress with KPIs |
| GET | `/api/dashboard/project-plan` | Project plan with Gantt timeline + lifecycle status (`on_track` / `overdue` / `delivered_late`) |
| GET | `/api/dashboard/plan-summary` | Latest sprint plan summary (for hero banner) |

### Sprint Planning
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/sprints` | Sprint overview + latest plan |
| GET | `/api/sprints/plan` | Full plan with assignments |
| POST | `/api/sprints` | Generate AI sprint plan |
| PATCH | `/api/sprints` | Approve or reject plan |
| GET | `/api/sprints/forecast` | Success probability + spillover risk |
| POST | `/api/sprints/forecast/refresh` | Refresh forecast calculations |
| POST | `/api/sprints/rebalance` | Generate a rebalanced plan proposal |

### Standups
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/standups` | Digest + individual reports (`?forceRefresh=true` triggers ADO sync) |
| POST | `/api/standups` | Submit standup note |
| POST | `/api/standups/generate` | Auto-generate standups |
| POST | `/api/standups/blocker` | Flag a blocker |
| GET | `/api/standups/{report_id}/sprint-contributions` | Per-sprint contribution rollup |

### GitHub
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/github` | Pull request list |
| GET | `/api/github/overview` | Aggregate stats (repos, PRs, commits) |
| GET | `/api/github/activity` | Activity feed with filters |

### Team Health
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/team-health` | Active health signals |
| POST | `/api/team-health/evaluate` | Trigger signal evaluation |
| POST | `/api/team-health/resolve` | Resolve a signal |

### Write-back
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/writeback` | Sync fields to Jira/ADO |
| POST | `/api/writeback/undo` | Undo within 60-min window |
| GET | `/api/writeback/log` | Write-back audit entries |

### Retrospectives
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/retrospectives` | Latest retrospective |
| GET | `/api/retrospectives/history` | All retrospectives for a project |
| GET | `/api/retrospectives/project-summary?projectId=…` | Project-cycle summary (completed/outstanding, used by overdue email + UI card) |
| POST | `/api/retrospectives/analyze` | Trigger failure analysis |

### Projects
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/projects/` | List imported projects (filtered per role) |
| POST | `/api/projects/` | Save/upsert project |
| DELETE | `/api/projects/{id}` | Remove project |
| GET | `/api/projects/{id}/access` | Check if caller has access (hasAccess + projectName) |
| PATCH | `/api/projects/{id}/target-launch` | Set / override target launch date |
| GET | `/api/projects/preferences/selected` | User's last-selected project |
| POST | `/api/projects/preferences/selected` | Save project selection |
| GET | `/api/projects/stakeholder-assignments` | List stakeholder project assignments |
| POST | `/api/projects/stakeholder-assignments` | Assign project to a stakeholder/dev |
| DELETE | `/api/projects/stakeholder-assignments/{id}` | Remove assignment |

### Organizations
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/organizations/current` | Current org details |
| PATCH | `/api/organizations/current` | Update org settings (canonical-match flow may create a join request instead of renaming) |
| GET | `/api/organizations/current/members` | List org members (users + team_members) |
| PATCH | `/api/organizations/current/members/{id}` | Update member role |
| DELETE | `/api/organizations/current/members/{id}` | Remove member |
| GET | `/api/organizations/current/invitations` | List pending invitations |
| POST | `/api/organizations/current/invitations` | Send invitation |
| POST | `/api/organizations/invitations/{token}/accept` | Accept invitation |
| GET | `/api/organizations/current/join-requests` | Pending join requests targeting caller's org (founder only) |
| GET | `/api/organizations/join-requests/mine` | Caller's own pending join request |
| POST | `/api/organizations/join-requests/{id}/approve` | Founder approves → migration runs |
| POST | `/api/organizations/join-requests/{id}/reject` | Founder declines |
| POST | `/api/organizations/join-requests/{id}/cancel` | Requester withdraws |

### Notifications
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/notifications` | Latest in-app notifications |
| POST | `/api/notifications/send` | Trigger notification |
| POST | `/api/notifications/test` | Send test notification |
| PATCH | `/api/notifications/{id}/read` | Mark as read |
| DELETE | `/api/notifications/clear` | Clear all |

### Integration OAuth, Channels, Webhooks
| Tool | OAuth | Channels / Quick Actions | Webhook |
|------|-------|--------------------------|---------|
| Jira | `/api/integrations/jira/connect` → `/jira/callback` | — | `POST /api/integrations/jira/webhooks` (HMAC-SHA256 verified) |
| ADO | `/api/integrations/ado/connect` (OAuth) or `/ado/connect-token` (PAT) | — | `POST /api/integrations/ado/webhooks` (X-Hook-Secret constant-time compare) |
| GitHub | `/api/integrations/github/auth` → `/github/callback` | — | `POST /api/integrations/github/webhooks` (X-Hub-Signature-256, per-connection secret) |
| Slack | `/api/integrations/slack/connect` → `/slack/callback`; per-user: `/slack/me/connect` | `/slack/list-channels`, `/slack/create-channel`, `/slack/project-channel`, `/slack/post-to-channel` | `POST /api/integrations/slack/events` + `/slack/interactions` (X-Slack-Signature + replay-window) |
| Teams | `/api/integrations/teams/connect` → `/teams/callback`; per-user: `/teams/me/connect` | `/teams/list-teams`, `/teams/select-parent-team`, `/teams/create-channel`, `/teams/project-channel`, `/teams/post-to-channel` | `POST /api/integrations/teams/webhook` (Microsoft Graph clientState) |

### WebSocket
| Endpoint | Description |
|----------|-------------|
| `WS /api/ws` | Real-time dashboard updates (Redis-backed cross-replica delivery) |

Common event types broadcast on the WS channel: `notification`, `standup_generated`, `blocker_status_changed`, `blockers_detected`, `channel_created`, `sprint_plan_generated`, `sprint_plan_updated`, `work_item_updated`, `sync_complete`, `join_request_created`, `join_request_resolved`, `health_analysis_complete`, `retro_generated`.

---

## Database Schema

### Core Entities (30+ tables)

**Organization & Auth**
- `Organization` — Workspace with timezone, working hours, standup schedule. `name_canonical` column (lower(trim(name)), unique) used for canonical match on signup/rename.
- `User` — Plan2Sprint account linked to Supabase Auth (`supabase_user_id`)
- `TeamMember` — Profile with skills, capacity, Slack/Teams IDs
- `OrgJoinRequest` — Owner-approval queue for canonical-match org joins (pending / approved / rejected / cancelled)
- `Invitation` — Email-token invitations (PO → developer/stakeholder)
- `StakeholderProjectAssignment` — Explicit project assignments by a PO

**Work Management**
- `WorkItem` — Jira issues / ADO tasks (status, story points, priority, epic, assignee, phase_id, planned_start/end)
- `Iteration` — Sprints with start/end dates, state, and goal
- `ProjectPhase` — 7-phase lifecycle (Discovery & Design → Ready)
- `PhaseAssignmentRule` — AI phase-classifier output
- `Repository` — GitHub repos
- `PullRequest` — PRs with status, reviewers, CI state, linked work item
- `Commit` — Git commits with SHA, message, branch, linked tickets

**Sprint Planning**
- `SprintPlan` — AI-generated plan (status flow: GENERATING → PENDING_REVIEW → APPROVED → SYNCED)
- `PlanAssignment` — Work item → team member assignment with confidence, rationale, risk flags
- `VelocityProfile` — Rolling velocity averages per team member
- `SprintConstraint` — Capacity limits and excluded dates
- `RebalanceProposal` — Stored output of the rebalance engine

**Standups & Health**
- `StandupReport` — Daily standup (completed, in-progress, blockers, narrative_text, developer_note)
- `TeamStandupDigest` — Sprint-level standup summary
- `BlockerFlag` — Blocker lifecycle (OPEN → ACKNOWLEDGED → ESCALATED → RESOLVED), with HMAC-signed action URLs
- `HealthSignal` — Health alerts with severity (GREEN / AMBER / RED)
- `BurnoutAlert` — Burnout risk detection
- `Note` — Smart Notes per project

**Retrospectives**
- `Retrospective` — Sprint retro with AI failure analysis
- `RetroActionItem` — Action items with carry-forward tracking

**Integration & Audit**
- `ToolConnection` — OAuth/PAT connections for all 5 tools (tokens encrypted with Fernet)
- `ImportedProject` — External project references with cached data, `target_launch_date`, `target_launch_source` (AUTO/MANUAL), `last_overdue_alert_target_date` (idempotency key), `slack_channel_id`, `teams_channel_id`
- `UserProjectPreference` — User's last-selected project
- `AuditLogEntry` — Full audit trail for all integration events
- `ActivityEvent` — Unified activity timeline
- `NotificationPreference` — Per-user channel preferences
- `InAppNotification` — In-app notification inbox entries

### Key Enums
| Enum | Values |
|------|--------|
| SprintPlanStatus | GENERATING, PENDING_REVIEW, APPROVED, REJECTED, REGENERATING, SYNCING, SYNCED, SYNCED_PARTIAL, UNDONE, EXPIRED |
| WorkItemStatus | BACKLOG, TODO, IN_PROGRESS, IN_REVIEW, DONE, CLOSED |
| PRStatus | OPEN, AWAITING_REVIEW, CHANGES_REQUESTED, APPROVED, MERGED, CLOSED |
| HealthSignalType | BURNOUT_RISK, VELOCITY_VARIANCE, STALLED_TICKET, REVIEW_LAG, CI_FAILURE, AFTER_HOURS, INACTIVITY, CAPACITY_OVERLOAD |
| HealthSeverity | GREEN, AMBER, RED |
| BlockerStatus | OPEN, ACKNOWLEDGED, ESCALATED, RESOLVED, DISMISSED |
| SourceTool | JIRA, ADO, GITHUB, NOTION, LINEAR |
| UserRole | owner, admin, product_owner, engineering_manager, developer, stakeholder |
| OrgJoinRequestStatus | pending, approved, rejected, cancelled |

---

## Role-Based Access Control

Plan2Sprint implements 6 roles with granular dashboard access:

| Role | PO Dashboard | Dev Dashboard | Stakeholder Dashboard | Settings |
|------|:------------:|:-------------:|:---------------------:|:--------:|
| Owner | Full | Full | Full | Full |
| Admin | Full | Full | Full | Full |
| Product Owner | Full | Full (view) | Full (view) | Limited |
| Engineering Manager | Full | Full | — | Limited |
| Developer | — | Full | — | Own profile |
| Stakeholder | — | — | Full | Own profile |

### Project-Access Guard

Beyond role checks, every per-project data endpoint enforces a project-membership check via `services/project_access.assert_project_access`:

- **PO / admin / owner** — all projects in their org
- **Developer / stakeholder / engineering_manager** — projects where ANY of:
  1. `TeamMember.imported_project_id` matches the project AND email matches AND role != excluded
  2. An explicit `StakeholderProjectAssignment` exists for the project
  3. Any `WorkItem.assignee_id` in the project points at a TeamMember with the caller's email (catches ADO-imported team members whose TM row has `imported_project_id = NULL`)

Failed checks return `403` (in-org but no membership) or `404` (cross-org; we don't leak project existence). The `ProjectAccessDeniedBanner` component on the dev dashboard renders the denial explicitly so users see a clear "ask the PO to assign you" message instead of a silent empty state.

### Dashboard Panel Counts
- **Product Owner:** Project hero banner (KPIs + timeline stepper + target launch + overdue indicators), project overview (module status cards), sprint forecast, GitHub monitoring, standup digest, retrospective hub, write-back confirmation, project plan Gantt, channels manager, notification inbox (10 panels)
- **Developer:** Sprint board, assigned work, PR list, commit activity, velocity trend, standup submission, blocker flagging, notification center (8 panels)
- **Stakeholder:** Portfolio health summary, delivery predictability, epic/milestone tracker, team health summary, standup replacement status, export/reporting (6 panels)

---

## Multi-Tenant Architecture

### Org Canonicalisation

`organizations.name_canonical` (`LOWER(TRIM(name))`, UNIQUE) is the matching key for "the same organisation." Two POs typing "C2A", "c2a", or " C2A " land in the same row. The helper `services.org_lookup.find_or_create_org` is the single source of truth and is called from both the signup flow (email/password OR OAuth) and the Settings → org-rename flow.

### Owner-Approval Gate

When a sole-user PO renames their organisation to match an existing canonical, instead of auto-migrating (which would let strangers acquire access by guessing tenant names), Plan2Sprint creates an `OrgJoinRequest` and routes the approval to the **founder** of the target org (earliest-created PO):

```
PATCH /organizations/current ─ name match found ─┐
                                                 │
                          OrgJoinRequest created │
                                                 │
                  WebSocket + email to founder ──┘
                                                 │
        ┌────────────────────────────────────────┘
        ▼
Founder opens Settings → Team → "Join Requests"
        │
        ├── Approve → migration runs (re-validates sole-user invariant);
        │   requester's user_id + team_members + projects + connections
        │   + work_items reassigned to target org; source org deleted;
        │   audit-log entry written; WS notifies requester
        │
        └── Reject  → request closed; requester stays in their own org
```

### Project Isolation

Per-project data is isolated by `organization_id` + project-access guard. Cross-org leakage paths closed:
- Project list (`/api/projects`) filters per role
- All `/api/dashboard/*` endpoints route through `_resolve_org_for_project` which now enforces the access guard
- Project context's "auto-import from connection" fallback gated to privileged roles only

---

## Security

### Authentication
- Supabase Auth (PKCE flow) — Google OAuth, Microsoft OAuth, email/password
- Server-side JWT verification with strict algorithm pinning
- Per-user OAuth identity linking for Slack and Teams (separate from org-level bot connection)
- Auth-flash protection: sidebar + topbar gate role-dependent rendering on `authReady` so devs/stakeholders never glimpse PO-only nav during refresh

### OAuth Login Hardening
- Single shared Supabase browser singleton (one auth listener, one storage lock)
- `/login` surfaces PKCE failure errors explicitly
- Silent auto-retry without `prompt=select_account` on PKCE-flavoured failures (handles stricter cookie isolation on Brave / Chrome)
- `/auth/callback` forwards provider hint for the retry path

### Authorization
- Role-based route guards (middleware + page-level `RoleGuard`)
- Project-access guard on every per-project data endpoint
- Per-mutation `require_po` / `require_admin` checks on org-level write endpoints

### Webhook Signature Verification
| Provider | Header / Field | Method |
|----------|----------------|--------|
| Jira | `X-Atlassian-Webhook-Signature` | HMAC-SHA256, constant-time compare |
| ADO | `X-Hook-Secret` | Shared-secret, constant-time compare |
| Microsoft Teams (Graph) | `clientState` in notification body | Shared-secret, constant-time compare |
| GitHub | `X-Hub-Signature-256` | HMAC-SHA256, per-connection secret with lazy migration |
| Slack | `X-Slack-Signature` + `X-Slack-Request-Timestamp` | HMAC-SHA256 of `v0:ts:body` with 5-minute replay window |

`STRICT_WEBHOOK_VERIFICATION=true` rejects unsigned webhooks when secrets aren't configured.

### Secrets Management
- All production secrets live in Azure Key Vault, mounted into Container Apps via system-assigned managed identity
- OAuth tokens encrypted at rest with Fernet (`INTEGRATION_ENCRYPTION_KEY`)
- Webhook secrets composed via Key Vault references (`keyvaultref:https://...`)

### Audit
- Every integration event, write-back, and org-level state change logged to `AuditLogEntry`
- Org canonical-match merges recorded with full row-reassignment counts

---

## Integration Layer

### Write-Back Safety

Write-back operations use **frozen allowlists** to prevent accidental data modification:

| Tool | Allowed Fields |
|------|---------------|
| Jira | `comment` (read-only for status/assignee/sprint/SP) |
| Azure DevOps | `comment` (read-only for status/AssignedTo/IterationPath/SP/StartDate/TargetDate) |
| GitHub | **Read-only** (no write-back) |

All write-back operations:
- Require explicit user confirmation via a modal guard
- Are logged in the audit trail with before/after state
- Support undo within a 60-minute window

### Data Flow

```
External Tool (Jira / ADO / GitHub / Slack / Teams)
        │
        ▼
   OAuth + Webhooks (HMAC-signature verified)
        │
        ▼
   Adapter Layer (normalize fields)
        │
        ▼
   SQLAlchemy Models (internal DB)
        │
        ▼
   API Routers (serve to frontend, project-access guarded)
        │
        ▼
   WebSocket Broadcast (Redis-backed, cross-replica)
```

### Project Channel Flow

For both Slack and Microsoft Teams:

```
PO opens Channels page → picks Slack or Teams tab
        │
        ├── Slack: PO clicks "Create Channel" for project X
        │         → POST /api/integrations/slack/create-channel
        │         → conversations.create #proj-X
        │         → invite team members (TeamMember.slack_user_id)
        │         → store slack_channel_id on ImportedProject
        │
        └── Teams: First time only, PO picks parent Team
                  → POST /api/integrations/teams/select-parent-team
                  → stored in ToolConnection.config.parent_team_id
                  PO clicks "Create Channel" for project X
                  → POST /api/integrations/teams/create-channel
                  → POST /teams/{parent}/channels  (membershipType: standard)
                  → store teams_channel_id on ImportedProject
                  → Adaptive Card actions for blockers use signed URLs
                    that hit /api/integrations/teams/blocker-action
```

---

## Background Jobs

### Notification Scheduler (`services/notification_scheduler.py`)
60-second tick that fires the following at the right times:

| Window (Asia/Kolkata) | UTC | Action |
|---|---|---|
| Daily 09:00 | 03:30 | Morning digest to PO via Slack/Teams/email + overdue project alert sweep |
| Daily 17:00 | 11:30 | Evening summary to PO |
| Friday 17:00 | 11:30 | Weekly stakeholder PDF report |

Scheduling uses KEDA cron scalers on Azure Container Apps to wake the API container at exactly those windows (minReplicas=0 otherwise).

### Overdue Project Alerts (`services/overdue_alert.py`)
Fires once per morning. Finds projects where:
- `is_active = true`
- `target_launch_date` is at least 24h in the past
- `last_overdue_alert_target_date != target_launch_date` (idempotency key)

Sends a trimmed email to the PO (header + 4-tile counters + "Where the work sits" phase rollup + Next-step CTA). Updates `last_overdue_alert_target_date` so it never fires twice for the same target. The same data shape powers the in-app "Project Cycle Concluded" card on the retrospective page.

### Standup Generation
Triggered automatically by `?forceRefresh=true` on `/api/standups` (PO/dev refresh button) and on the morning digest path. 7-day rolling window; blocker auto-resolution against the underlying ticket's terminal status; multi-TeamMember merging for users with duplicate TM rows.

### Distributed Locks
When multiple replicas are active, Redis locks prevent duplicate cron fires + duplicate ADO/Jira syncs + duplicate standup generation.

---

## Deployment

### Production (Azure)

Plan2Sprint runs on **Azure Container Apps** in resource group `Rg_Plan2Sprint` (West US 3) with the following resources:

| Resource | Role |
|---|---|
| `plan2sprintacr` (Azure Container Registry) | Image registry for the API + Web images |
| `plan2sprint-api` (Container App) | FastAPI backend, KEDA cron-scaled |
| `plan2sprint-web` (Container App) | Next.js frontend |
| `plan2sprint-kv` (Key Vault) | All secrets, referenced via managed identity |
| `plan2sprint-redis` (Azure Cache for Redis Enterprise) | Event bus + distributed locks |
| Supabase (external) | Auth + PostgreSQL |

#### Build + Deploy

```bash
# Build API image and push to ACR
cd apps/api
az acr build --registry plan2sprintacr \
  --image "plan2sprint-api:v$(date +%s)" \
  --image "plan2sprint-api:latest" \
  --file Dockerfile --no-logs .

# Build Web image (requires Next.js build args)
cd apps/web
az acr build --registry plan2sprintacr \
  --image "plan2sprint-web:v$(date +%s)" \
  --image "plan2sprint-web:latest" \
  --file Dockerfile \
  --build-arg "NEXT_PUBLIC_SUPABASE_URL=$SUPA_URL" \
  --build-arg "NEXT_PUBLIC_SUPABASE_ANON_KEY=$SUPA_KEY" \
  --build-arg "API_URL=$API_URL" \
  --no-logs .

# Roll a Container App revision
az containerapp update --name plan2sprint-api \
  --resource-group Rg_Plan2Sprint \
  --image plan2sprintacr.azurecr.io/plan2sprint-api:vXXXXXXXXXX
```

### Local Development (Docker Compose)

```bash
# Build and start
docker compose up --build -d

# View logs
docker compose logs -f

# Stop
docker compose down
```

### Manual Local

```bash
# Build frontend
cd apps/web
npm run build
npm start

# Start backend
cd apps/api
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### NPM Scripts (Root)

```bash
npm run dev              # Start Next.js dev server
npm run build            # Production build
npm run start            # Start production server
npm run docker:build     # Build Docker images
npm run docker:up        # Start containers
npm run docker:down      # Stop containers
npm run docker:logs      # Stream container logs
npm run docker:restart   # Restart containers
```

---

## Frontend Pages

| Route | Description |
|-------|-------------|
| `/` | Landing page |
| `/login` | Authentication |
| `/signup` | Registration |
| `/onboarding` | Organization setup wizard |
| `/po` | Product Owner dashboard (hero banner + module status + project plan Gantt) |
| `/po/planning` | Sprint planning interface |
| `/po/standups` | Standup digest |
| `/po/health` | Team health signals |
| `/po/github` | GitHub monitoring |
| `/po/projects` | Project management |
| `/po/retro` | Retrospectives (includes "Project Cycle Concluded" card when overdue) |
| `/po/notifications` | Channels & quick actions (Slack/Teams tab switcher) |
| `/dev` | Developer overview (with project-access banner when denied) |
| `/dev/sprint` | Sprint board |
| `/dev/standups` | Submit standup |
| `/dev/github` | PR list & activity |
| `/dev/velocity` | Velocity trends |
| `/dev/notifications` | Channels (developer view) |
| `/stakeholder` | Stakeholder overview |
| `/stakeholder/delivery` | Delivery timeline |
| `/stakeholder/health` | Health summary |
| `/stakeholder/epics` | Epic roadmap |
| `/stakeholder/export` | Export & reporting |
| `/settings` | Organization general settings (pending-join-request banner here too) |
| `/settings/profile` | User profile |
| `/settings/team` | Team management (Join Requests + Pending Invitations) |
| `/settings/connections` | Integration management |
| `/settings/notifications` | Notification preferences |

---

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
