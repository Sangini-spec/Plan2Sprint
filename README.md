# Plan2Sprint

**AI-Powered Sprint Planning**

Plan2Sprint transforms agile team management by integrating with Jira, Azure DevOps, and GitHub to deliver intelligent sprint planning, real-time health signals, automated standups, and cross-tool observability.

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
- [Integration Layer](#integration-layer)
- [Deployment](#deployment)

---

## Key Features

### AI Sprint Planning
- AI-powered sprint optimization with confidence scoring
- Automatic skill-to-task matching and workload balancing
- Spillover risk assessment and success probability forecasting
- One-click approval with write-back to Jira / Azure DevOps

### Team Health Monitoring
- 8 real-time health signal types: burnout risk, velocity variance, stalled tickets, review lag, CI failure, after-hours activity, inactivity, and capacity overload
- RAG (Red/Amber/Green) severity indicators per signal
- Automatic escalation workflows via Slack and Microsoft Teams

### Standup Automation
- Auto-generated standups from synced work items, PRs, and commits
- Blocker flagging with instant PO notification
- Team digest summaries with acknowledged percentage tracking
- Sprint pacing and at-risk item detection

### GitHub Monitoring
- Pull request tracking with CI status, review state, and linked work items
- Commit activity feed with developer, type, and time-range filters
- Aggregate metrics: repos, open PRs, merged PRs, commits per sprint

### Retrospective & Failure Analysis
- AI-driven root cause analysis for missed sprint goals
- What went well / what didn't go well categorization
- Action items with carry-forward tracking across sprints

### Multi-Tool Integration
- OAuth 2.0 flows for Jira (3LO), Azure DevOps, GitHub, Slack, and Microsoft Teams
- Webhook-based real-time data sync
- Field normalization across all source tools
- Batch write-back with 60-minute undo window
- Full audit logging for every integration event

### Notification System
- Multi-channel delivery: Slack, Microsoft Teams, Email, In-App
- Adaptive card templates for rich notifications
- Event-based triggers: sprint approval, blocker alerts, health alerts, standup reports

### Real-Time Dashboards
- WebSocket-powered live updates across all dashboard panels
- Three role-specific dashboards: Product Owner (10 panels), Developer (8 panels), Stakeholder (6 panels)
- Project-scoped views with persistent project selection

---

## Tech Stack

### Frontend
| Technology | Version | Purpose |
|-----------|---------|---------|
| Next.js | 15.1.0 | React framework (App Router) |
| React | 19.0.0 | UI library |
| TypeScript | 5.7.0 | Type safety |
| Tailwind CSS | 4.0.0 | Utility-first styling |
| Framer Motion | 12.0.0 | Animations and transitions |
| Recharts | 3.7.0 | Dashboard charts and graphs |
| TanStack React Table | 8.21.3 | Data tables |
| React Hook Form + Zod | 7.54.0 / 3.24.0 | Form handling and validation |
| Supabase SSR | 0.8.0 | Authentication |
| Lucide React | 0.469.0 | Icon library |
| Sonner | 2.0.7 | Toast notifications |

### Backend
| Technology | Version | Purpose |
|-----------|---------|---------|
| FastAPI | 0.115.0 | Async Python web framework |
| Python | 3.12+ | Runtime |
| SQLAlchemy | 2.0+ | Async ORM |
| asyncpg | 0.30.0 | PostgreSQL async driver |
| Alembic | 1.14.0 | Database migrations |
| Pydantic | 2.10.0 | Request/response validation |
| httpx | 0.28.0 | Async HTTP client for integrations |
| python-jose | 3.3.0 | JWT authentication |
| Anthropic SDK | 0.80.0 | Claude AI integration |

### Infrastructure
| Technology | Purpose |
|-----------|---------|
| Supabase | PostgreSQL database + Auth |
| Docker + Compose | Containerized deployment |
| Ngrok | Local OAuth callback tunneling |
| WebSocket | Real-time dashboard updates |

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                        FRONTEND                              │
│                   Next.js 15 (App Router)                    │
│                                                              │
│   ┌──────────┐  ┌──────────┐  ┌──────────────┐              │
│   │    PO    │  │   Dev    │  │ Stakeholder  │  Dashboards  │
│   │ 10 panels│  │ 8 panels │  │  6 panels    │              │
│   └──────────┘  └──────────┘  └──────────────┘              │
│                                                              │
│   ┌──────────────────────────────────────────┐               │
│   │  Integration UI  │  Auth  │  Settings    │               │
│   └──────────────────────────────────────────┘               │
│                        │                                     │
│                   /api/* proxy                               │
└────────────────────────┼─────────────────────────────────────┘
                         │
┌────────────────────────┼─────────────────────────────────────┐
│                    BACKEND                                    │
│                 FastAPI (Python)                              │
│                                                              │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌───────────┐  │
│   │ Routers  │  │ Services │  │ Adapters │  │  Models   │  │
│   │ 15+ APIs │  │ AI Plan  │  │ Jira     │  │ 25 tables │  │
│   │          │  │ Standups │  │ ADO      │  │           │  │
│   │          │  │ Health   │  │ GitHub   │  │           │  │
│   │          │  │ Forecast │  │ Slack    │  │           │  │
│   │          │  │ Notifs   │  │ Teams    │  │           │  │
│   └──────────┘  └──────────┘  └──────────┘  └───────────┘  │
│                        │                                     │
└────────────────────────┼─────────────────────────────────────┘
                         │
              ┌──────────┼──────────┐
              │   Supabase Cloud    │
              │  PostgreSQL + Auth  │
              └─────────────────────┘
```

### Route Groups
- `(marketing)` — Public landing page
- `(auth)` — Login, signup, forgot password
- `(app)` — Authenticated shell with sidebar + topbar

### API Proxy
All `/api/*` requests from the frontend are proxied to the FastAPI backend via Next.js rewrites configured in `next.config.ts`.

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
│   │   │   ├── models/                   # 25 SQLAlchemy ORM models
│   │   │   ├── routers/                  # API endpoint handlers
│   │   │   │   ├── analytics.py
│   │   │   │   ├── dashboard.py
│   │   │   │   ├── sprints.py
│   │   │   │   ├── standups.py
│   │   │   │   ├── github.py
│   │   │   │   ├── team_health.py
│   │   │   │   ├── notifications.py
│   │   │   │   ├── projects.py
│   │   │   │   ├── writeback.py
│   │   │   │   ├── retrospectives.py
│   │   │   │   ├── ws.py
│   │   │   │   └── integrations/         # OAuth + sync routers
│   │   │   │       ├── connections.py
│   │   │   │       ├── sync.py
│   │   │   │       ├── jira.py
│   │   │   │       ├── ado.py
│   │   │   │       ├── github.py
│   │   │   │       ├── slack.py
│   │   │   │       └── teams.py
│   │   │   ├── services/                 # Business logic
│   │   │   │   ├── ai_sprint_generator.py
│   │   │   │   ├── sprint_forecast.py
│   │   │   │   ├── standup_generator.py
│   │   │   │   ├── failure_analysis.py
│   │   │   │   ├── activity_engine.py
│   │   │   │   ├── delivery_queue.py
│   │   │   │   ├── ws_manager.py
│   │   │   │   └── writeback.py
│   │   │   ├── adapters/                 # External API wrappers
│   │   │   └── schemas/                  # Pydantic schemas
│   │   ├── pyproject.toml
│   │   ├── Dockerfile
│   │   └── .env.example
│   │
│   └── web/                              # Next.js Frontend
│       ├── src/
│       │   ├── app/
│       │   │   ├── globals.css           # Design tokens
│       │   │   ├── (marketing)/          # Landing page
│       │   │   ├── (auth)/               # Login, signup
│       │   │   └── (app)/                # Authenticated shell
│       │   │       ├── po/               # Product Owner (8 pages)
│       │   │       ├── dev/              # Developer (7 pages)
│       │   │       ├── stakeholder/      # Stakeholder (6 pages)
│       │   │       └── settings/         # Settings (4 pages)
│       │   ├── components/
│       │   │   ├── ui/                   # Base UI components
│       │   │   ├── dashboard/            # Shared panels & cards
│       │   │   ├── layout/               # Sidebar, topbar
│       │   │   ├── integrations/         # Jira/ADO/GitHub cards
│       │   │   ├── po/                   # PO-specific components
│       │   │   ├── dev/                  # Dev-specific components
│       │   │   └── stakeholder/          # Stakeholder components
│       │   ├── lib/
│       │   │   ├── auth/                 # AuthProvider + useAuth
│       │   │   ├── types/                # TypeScript interfaces
│       │   │   ├── integrations/         # Adapters + write-back
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
- **Supabase** project (for PostgreSQL + Auth)
- **Ngrok** (for local OAuth callback tunneling)

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

# Terminal 3 — Ngrok (required for OAuth callbacks)
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

| Variable | Description |
|----------|-------------|
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_ANON_KEY` | Supabase anonymous key |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase service role key |
| `SUPABASE_JWT_SECRET` | JWT secret for token verification |
| `DATABASE_URL` | PostgreSQL connection string (asyncpg) |
| `JIRA_CLIENT_ID` / `JIRA_CLIENT_SECRET` | Jira OAuth 3LO credentials |
| `ADO_CLIENT_ID` / `ADO_CLIENT_SECRET` | Azure DevOps OAuth credentials |
| `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` | GitHub App credentials |
| `SLACK_CLIENT_ID` / `SLACK_CLIENT_SECRET` / `SLACK_SIGNING_SECRET` | Slack App credentials |
| `TEAMS_CLIENT_ID` / `TEAMS_CLIENT_SECRET` | Microsoft Teams credentials |
| `ANTHROPIC_API_KEY` | Claude AI API key |
| `INTEGRATION_ENCRYPTION_KEY` | Fernet key for token encryption |
| `FRONTEND_URL` | Frontend origin (default: `http://localhost:3000`) |

### Frontend (`apps/web/.env.local`)

| Variable | Description |
|----------|-------------|
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase project URL |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Supabase anonymous key |
| `SUPABASE_SERVICE_ROLE_KEY` | Service role key (server-side only) |
| `INTEGRATION_ENCRYPTION_KEY` | Token encryption key |

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
| GET | `/api/dashboard/project-plan` | Project plan with Gantt timeline data |

### Sprint Planning
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/sprints` | Sprint overview + latest plan |
| GET | `/api/sprints/plan` | Full plan with assignments |
| POST | `/api/sprints` | Generate AI sprint plan |
| PATCH | `/api/sprints` | Approve or reject plan |
| GET | `/api/sprints/forecast` | Success probability + spillover risk |
| POST | `/api/sprints/forecast/refresh` | Refresh forecast calculations |

### Standups
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/standups` | Digest + individual reports |
| POST | `/api/standups` | Submit standup note |
| POST | `/api/standups/generate` | Auto-generate standups |
| POST | `/api/standups/blocker` | Flag a blocker |

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
| POST | `/api/retrospectives/analyze` | Trigger failure analysis |

### Projects
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/projects/` | List imported projects |
| POST | `/api/projects/` | Save/upsert project |
| DELETE | `/api/projects/{id}` | Remove project |
| GET | `/api/projects/preferences/selected` | User's last-selected project |
| POST | `/api/projects/preferences/selected` | Save project selection |

### Notifications
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/notifications/send` | Trigger notification |
| POST | `/api/notifications/test` | Send test notification |

### Integration OAuth & Sync
| Tool | Auth Endpoint | Callback | Data Endpoints |
|------|--------------|----------|----------------|
| Jira | `GET /api/integrations/jira/connect` | `/jira/callback` | `/jira/projects`, `/jira/issues`, `/jira/sprints` |
| ADO | `GET /api/integrations/ado/connect` | `/ado/callback` | `/ado/projects`, `/ado/iterations`, `/ado/work-items` |
| GitHub | `GET /api/integrations/github/auth` | `/github/callback` | `/github/repos`, `/github/pulls`, `/github/commits` |
| Slack | `GET /api/integrations/slack/connect` | `/slack/callback` | `/slack/users`, `/slack/send`, `/slack/channels` |
| Teams | `GET /api/integrations/teams/connect` | `/teams/callback` | `/teams/users`, `/teams/send` |

### WebSocket
| Endpoint | Description |
|----------|-------------|
| `WS /api/ws` | Real-time dashboard updates |

---

## Database Schema

### Core Entities (25 tables)

**Organization & Auth**
- `Organization` — Workspace with timezone, working hours, standup schedule
- `User` — Account linked to Supabase Auth
- `TeamMember` — Profile with skills, capacity, Slack/Teams IDs

**Work Management**
- `WorkItem` — Jira issues / ADO tasks (status, story points, priority, epic, assignee)
- `Iteration` — Sprints with start/end dates, state, and goal
- `Repository` — GitHub repos
- `PullRequest` — PRs with status, reviewers, CI state, linked work item
- `Commit` — Git commits with SHA, message, branch, linked tickets

**Sprint Planning**
- `SprintPlan` — AI-generated plan (status flow: GENERATING → PENDING_REVIEW → APPROVED → SYNCED)
- `PlanAssignment` — Work item → team member assignment with confidence, rationale, risk flags
- `VelocityProfile` — Rolling velocity averages per team member
- `SprintConstraint` — Capacity limits and excluded dates

**Standups & Health**
- `StandupReport` — Daily standup (completed, in-progress, blockers, narrative)
- `TeamStandupDigest` — Sprint-level standup summary
- `BlockerFlag` — Blocker lifecycle (OPEN → ACKNOWLEDGED → ESCALATED → RESOLVED)
- `HealthSignal` — Health alerts with severity (GREEN / AMBER / RED)
- `BurnoutAlert` — Burnout risk detection

**Retrospectives**
- `Retrospective` — Sprint retro with AI failure analysis
- `RetroActionItem` — Action items with carry-forward tracking

**Integration & Audit**
- `ToolConnection` — OAuth connections for all 5 tools
- `ImportedProject` — External project references with cached data
- `UserProjectPreference` — User's last-selected project
- `AuditLogEntry` — Full audit trail for all integration events
- `ActivityEvent` — Unified activity timeline
- `NotificationPreference` — Per-user channel preferences

### Key Enums
| Enum | Values |
|------|--------|
| SprintPlanStatus | GENERATING, PENDING_REVIEW, APPROVED, REJECTED, REGENERATING, SYNCING, SYNCED, SYNCED_PARTIAL, UNDONE, EXPIRED |
| WorkItemStatus | BACKLOG, TODO, IN_PROGRESS, IN_REVIEW, DONE, CLOSED |
| PRStatus | OPEN, AWAITING_REVIEW, CHANGES_REQUESTED, APPROVED, MERGED, CLOSED |
| HealthSignalType | BURNOUT_RISK, VELOCITY_VARIANCE, STALLED_TICKET, REVIEW_LAG, CI_FAILURE, AFTER_HOURS, INACTIVITY, CAPACITY_OVERLOAD |
| HealthSeverity | GREEN, AMBER, RED |
| SourceTool | JIRA, ADO, GITHUB, NOTION, LINEAR |
| UserRole | owner, admin, product_owner, engineering_manager, developer, stakeholder |

---

## Role-Based Access Control

Plan2Sprint implements 6 roles with granular dashboard access:

| Role | PO Dashboard | Dev Dashboard | Stakeholder Dashboard | Settings |
|------|:------------:|:-------------:|:---------------------:|:--------:|
| Owner | Full | Full | Full | Full |
| Admin | Full | Full | Full | Full |
| Product Owner | Full | — | Read | Limited |
| Engineering Manager | Full | — | Read | Limited |
| Developer | — | Full | — | Own profile |
| Stakeholder | — | — | Full | Own profile |

### Dashboard Panel Counts
- **Product Owner:** Project hero banner (KPIs + timeline stepper), project overview (module status cards), sprint forecast, GitHub monitoring, standup digest, retrospective hub, write-back confirmation, project plan Gantt (8 panels)
- **Developer:** Sprint board, assigned work, PR list, commit activity, velocity trend, standup submission, blocker flagging, notification center (8 panels)
- **Stakeholder:** Portfolio health summary, delivery predictability, epic/milestone tracker, team health summary, standup replacement status, export/reporting (6 panels)

---

## Integration Layer

### Write-Back Safety

Write-back operations use **frozen allowlists** to prevent accidental data modification:

| Tool | Allowed Fields |
|------|---------------|
| Jira | `assignee`, `sprint_id`, `story_points` |
| Azure DevOps | `AssignedTo`, `IterationPath`, `StoryPoints`, `StartDate`, `TargetDate` |
| GitHub | **Read-only** (no write-back) |

All write-back operations:
- Require explicit user confirmation via a modal guard
- Are logged in the audit trail with before/after state
- Support undo within a 60-minute window

### Data Flow

```
External Tool (Jira/ADO/GitHub)
        │
        ▼
   OAuth + Webhooks
        │
        ▼
   Adapter Layer (normalize fields)
        │
        ▼
   SQLAlchemy Models (internal DB)
        │
        ▼
   API Routers (serve to frontend)
        │
        ▼
   WebSocket Broadcast (real-time updates)
```

---

## Deployment

### Docker Compose (Recommended)

```bash
# Build and start
docker compose up --build -d

# View logs
docker compose logs -f

# Stop
docker compose down
```

### Manual Deployment

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
| `/po` | Product Owner dashboard (hero banner + module status) & project plan Gantt |
| `/po/planning` | Sprint planning interface |
| `/po/standups` | Standup digest |
| `/po/health` | Team health signals |
| `/po/github` | GitHub monitoring |
| `/po/projects` | Project management |
| `/po/retro` | Retrospectives |
| `/po/notifications` | Notification center |
| `/dev` | Developer overview |
| `/dev/sprint` | Sprint board |
| `/dev/standups` | Submit standup |
| `/dev/github` | PR list & activity |
| `/dev/velocity` | Velocity trends |
| `/stakeholder` | Stakeholder overview |
| `/stakeholder/delivery` | Delivery timeline |
| `/stakeholder/health` | Health summary |
| `/stakeholder/epics` | Epic roadmap |
| `/settings/connections` | Integration management |
| `/settings/notifications` | Notification preferences |
| `/settings/team` | Team management |

---

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
