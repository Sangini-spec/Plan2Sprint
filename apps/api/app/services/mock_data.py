"""
Demo/mock data for all endpoints when running in demo mode.
Port of apps/web/src/lib/mock-data/ files.
"""

# ──────────────────────────────────────────────
# Integration mock data (from integration-data.ts)
# ──────────────────────────────────────────────

MOCK_JIRA_PROJECTS = [
    {"id": "10001", "key": "PROJ", "name": "Project Alpha", "projectType": "scrum", "avatarUrl": None},
    {"id": "10002", "key": "INFRA", "name": "Infrastructure", "projectType": "kanban", "avatarUrl": None},
    {"id": "10003", "key": "MOBILE", "name": "Mobile App", "projectType": "scrum", "avatarUrl": None},
    {"id": "10004", "key": "DESIGN", "name": "Design System", "projectType": "scrum", "avatarUrl": None},
]

MOCK_JIRA_SPRINTS = [
    {"id": 101, "name": "Sprint 24", "state": "active", "startDate": "2026-02-09T00:00:00Z", "endDate": "2026-02-23T00:00:00Z", "boardId": "1"},
    {"id": 102, "name": "Sprint 25", "state": "future", "startDate": "2026-02-23T00:00:00Z", "endDate": "2026-03-09T00:00:00Z", "boardId": "1"},
    {"id": 100, "name": "Sprint 23", "state": "closed", "startDate": "2026-01-27T00:00:00Z", "endDate": "2026-02-09T00:00:00Z", "boardId": "1"},
]

MOCK_ADO_PROJECTS = [
    {"id": "ado-1", "name": "Contoso Web", "description": "Main web application", "state": "wellFormed", "url": "https://dev.azure.com/contoso/web"},
    {"id": "ado-2", "name": "Contoso API", "description": "Backend API services", "state": "wellFormed", "url": "https://dev.azure.com/contoso/api"},
    {"id": "ado-3", "name": "Contoso Mobile", "description": "Mobile applications", "state": "wellFormed", "url": "https://dev.azure.com/contoso/mobile"},
]

MOCK_ADO_ITERATIONS = [
    {"id": "iter-ado-1", "name": "Sprint 24", "path": "Contoso Web\\Sprint 24", "attributes": {"startDate": "2026-02-09T00:00:00Z", "finishDate": "2026-02-23T00:00:00Z", "timeFrame": "current"}},
    {"id": "iter-ado-2", "name": "Sprint 25", "path": "Contoso Web\\Sprint 25", "attributes": {"startDate": "2026-02-23T00:00:00Z", "finishDate": "2026-03-09T00:00:00Z", "timeFrame": "future"}},
    {"id": "iter-ado-3", "name": "Sprint 23", "path": "Contoso Web\\Sprint 23", "attributes": {"startDate": "2026-01-27T00:00:00Z", "finishDate": "2026-02-09T00:00:00Z", "timeFrame": "past"}},
]

MOCK_GITHUB_REPOS = [
    {"id": "gh-1", "name": "acme-web", "fullName": "acme-org/acme-web", "defaultBranch": "main", "url": "https://github.com/acme-org/acme-web", "isPrivate": True, "language": "TypeScript", "openIssuesCount": 12, "stargazersCount": 0, "description": "Main web application", "updatedAt": "2026-02-20T18:00:00Z"},
    {"id": "gh-2", "name": "acme-api", "fullName": "acme-org/acme-api", "defaultBranch": "main", "url": "https://github.com/acme-org/acme-api", "isPrivate": True, "language": "Python", "openIssuesCount": 8, "stargazersCount": 0, "description": "Backend API", "updatedAt": "2026-02-20T16:30:00Z"},
    {"id": "gh-3", "name": "acme-mobile", "fullName": "acme-org/acme-mobile", "defaultBranch": "main", "url": "https://github.com/acme-org/acme-mobile", "isPrivate": True, "language": "TypeScript", "openIssuesCount": 5, "stargazersCount": 0, "description": "Mobile app", "updatedAt": "2026-02-19T12:00:00Z"},
    {"id": "gh-4", "name": "acme-infra", "fullName": "acme-org/acme-infra", "defaultBranch": "main", "url": "https://github.com/acme-org/acme-infra", "isPrivate": True, "language": "HCL", "openIssuesCount": 3, "stargazersCount": 0, "description": "Infrastructure as code", "updatedAt": "2026-02-18T10:00:00Z"},
    {"id": "gh-5", "name": "design-system", "fullName": "acme-org/design-system", "defaultBranch": "main", "url": "https://github.com/acme-org/design-system", "isPrivate": False, "language": "TypeScript", "openIssuesCount": 2, "stargazersCount": 15, "description": "Shared design system", "updatedAt": "2026-02-17T08:00:00Z"},
]

MOCK_GITHUB_PRS = [
    {"id": "gpr-1", "number": 89, "title": "feat: Checkout flow redesign", "status": "AWAITING_REVIEW", "repo": "acme-web", "author": "Alex Chen", "ciStatus": "PASSING", "linkedWorkItemId": "wi-1", "createdAt": "2026-02-19T10:30:00Z"},
    {"id": "gpr-2", "number": 87, "title": "fix: Mobile responsive layout", "status": "APPROVED", "repo": "acme-web", "author": "Alex Chen", "ciStatus": "PASSING", "linkedWorkItemId": "wi-5", "createdAt": "2026-02-18T14:00:00Z"},
    {"id": "gpr-3", "number": 92, "title": "feat: Payment integration - Stripe", "status": "CHANGES_REQUESTED", "repo": "acme-api", "author": "Sarah Kim", "ciStatus": "FAILING", "linkedWorkItemId": "wi-2", "createdAt": "2026-02-20T09:15:00Z"},
    {"id": "gpr-4", "number": 45, "title": "chore: Update auth dependencies", "status": "OPEN", "repo": "acme-web", "author": "Marcus Johnson", "ciStatus": "PASSING", "linkedWorkItemId": None, "createdAt": "2026-02-20T16:45:00Z"},
    {"id": "gpr-5", "number": 23, "title": "feat: Push notification service", "status": "AWAITING_REVIEW", "repo": "acme-mobile", "author": "James Wilson", "ciStatus": "PENDING", "linkedWorkItemId": "wi-7", "createdAt": "2026-02-21T08:00:00Z"},
    {"id": "gpr-6", "number": 15, "title": "feat: Recommendation engine v2", "status": "MERGED", "repo": "acme-api", "author": "Emma Davis", "ciStatus": "PASSING", "linkedWorkItemId": "wi-9", "createdAt": "2026-02-17T11:00:00Z"},
]

MOCK_GITHUB_COMMITS = [
    {"sha": "a1b2c3d", "message": "feat: add checkout form validation", "author": "Alex Chen", "authorLogin": "alexchen", "branch": "feature/checkout-redesign", "repo": "acme-web", "date": "2026-02-20T18:30:00Z", "linkedTicketIds": ["wi-1"]},
    {"sha": "e4f5g6h", "message": "fix: stripe webhook signature verification", "author": "Sarah Kim", "authorLogin": "sarahkim", "branch": "feature/payment-integration", "repo": "acme-api", "date": "2026-02-20T16:00:00Z", "linkedTicketIds": ["wi-2"]},
    {"sha": "i7j8k9l", "message": "style: responsive cart layout", "author": "Marcus Johnson", "authorLogin": "marcusjohnson", "branch": "fix/mobile-responsive", "repo": "acme-web", "date": "2026-02-20T14:20:00Z", "linkedTicketIds": ["wi-5"]},
    {"sha": "m0n1o2p", "message": "chore: update kubernetes manifests", "author": "Priya Patel", "authorLogin": "priyapatel", "branch": "infra/k8s-update", "repo": "acme-infra", "date": "2026-02-20T11:00:00Z", "linkedTicketIds": ["wi-4"]},
    {"sha": "q3r4s5t", "message": "feat: deep link routing", "author": "James Wilson", "authorLogin": "jameswilson", "branch": "feature/push-notifications", "repo": "acme-mobile", "date": "2026-02-19T15:45:00Z", "linkedTicketIds": ["wi-7"]},
    {"sha": "u6v7w8x", "message": "feat: collaborative filtering model", "author": "Emma Davis", "authorLogin": "emmadavis", "branch": "feature/recommendation-v2", "repo": "acme-api", "date": "2026-02-19T10:30:00Z", "linkedTicketIds": ["wi-9"]},
    {"sha": "y9z0a1b", "message": "test: add e2e tests for checkout", "author": "Alex Chen", "authorLogin": "alexchen", "branch": "feature/checkout-redesign", "repo": "acme-web", "date": "2026-02-19T09:00:00Z", "linkedTicketIds": ["wi-1"]},
]

# ──────────────────────────────────────────────
# Work items mock data (from po-dashboard.ts)
# ──────────────────────────────────────────────

MOCK_WORK_ITEMS = [
    {"id": "wi-1", "externalId": "AUTH-41", "title": "Checkout flow redesign", "status": "IN_PROGRESS", "storyPoints": 8, "type": "story", "assigneeId": "tm-1"},
    {"id": "wi-2", "externalId": "AUTH-42", "title": "Payment integration - Stripe", "status": "IN_PROGRESS", "storyPoints": 13, "type": "story", "assigneeId": "tm-2"},
    {"id": "wi-3", "externalId": "AUTH-43", "title": "Cart page animations", "status": "TODO", "storyPoints": 5, "type": "story", "assigneeId": "tm-3"},
    {"id": "wi-4", "externalId": "AUTH-44", "title": "K8s deployment config", "status": "IN_REVIEW", "storyPoints": 3, "type": "task", "assigneeId": "tm-4"},
    {"id": "wi-5", "externalId": "AUTH-45", "title": "Mobile responsive fixes", "status": "IN_REVIEW", "storyPoints": 3, "type": "bug", "assigneeId": "tm-1"},
    {"id": "wi-6", "externalId": "AUTH-46", "title": "Email notification templates", "status": "TODO", "storyPoints": 5, "type": "story", "assigneeId": "tm-3"},
    {"id": "wi-7", "externalId": "AUTH-47", "title": "Push notification service", "status": "IN_PROGRESS", "storyPoints": 8, "type": "story", "assigneeId": "tm-5"},
    {"id": "wi-8", "externalId": "AUTH-48", "title": "Order confirmation page", "status": "BACKLOG", "storyPoints": 5, "type": "story", "assigneeId": None},
    {"id": "wi-9", "externalId": "AUTH-49", "title": "Recommendation engine v2", "status": "DONE", "storyPoints": 5, "type": "story", "assigneeId": "tm-6"},
    {"id": "wi-10", "externalId": "AUTH-50", "title": "Load testing framework", "status": "DONE", "storyPoints": 3, "type": "task", "assigneeId": "tm-4"},
]
