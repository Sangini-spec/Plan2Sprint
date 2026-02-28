"""
GitHub integration router (READ-ONLY -- no write-back per MRD).
Ports all Next.js GitHub routes: auth, callback, repos, pulls, commits,
events, and webhooks.

Endpoints (all prefixed with /api/integrations/github by main.py):
  GET  /auth           - Returns GitHub OAuth authorize URL
  POST /auth           - Exchange authorization code for access token + user
  GET  /callback       - OAuth callback redirect handler
  GET  /repos          - List repos (demo mock)
  POST /repos          - Fetch real repos using OAuth access token
  GET  /pulls          - List PRs for a repo (demo mock)
  POST /pulls          - Fetch real PRs for linked repos
  GET  /commits        - List commits for a repo (demo mock)
  POST /commits        - Fetch real commits for linked repos
  POST /events         - Fetch recent activity events for linked repos
  POST /webhooks       - Receive GitHub webhook events
"""

from __future__ import annotations

import json
from datetime import datetime
from urllib.parse import urlencode, quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from ...auth.supabase import get_current_user
from ...config import settings
import httpx

router = APIRouter()

# ---------------------------------------------------------------------------
# Mock data (matches integration-data.ts)
# ---------------------------------------------------------------------------
MOCK_GITHUB_REPOS = [
    {"id": "gr-1", "name": "acme-web", "fullName": "acme-org/acme-web", "defaultBranch": "main", "url": "https://github.com/acme-org/acme-web", "isPrivate": True, "language": "TypeScript", "openIssuesCount": 12, "stargazersCount": 45},
    {"id": "gr-2", "name": "acme-api", "fullName": "acme-org/acme-api", "defaultBranch": "main", "url": "https://github.com/acme-org/acme-api", "isPrivate": True, "language": "Python", "openIssuesCount": 8, "stargazersCount": 32},
    {"id": "gr-3", "name": "acme-mobile", "fullName": "acme-org/acme-mobile", "defaultBranch": "develop", "url": "https://github.com/acme-org/acme-mobile", "isPrivate": True, "language": "TypeScript", "openIssuesCount": 5, "stargazersCount": 18},
    {"id": "gr-4", "name": "acme-infra", "fullName": "acme-org/acme-infra", "defaultBranch": "main", "url": "https://github.com/acme-org/acme-infra", "isPrivate": True, "language": "HCL", "openIssuesCount": 3, "stargazersCount": 8},
    {"id": "gr-5", "name": "design-system", "fullName": "acme-org/design-system", "defaultBranch": "main", "url": "https://github.com/acme-org/design-system", "isPrivate": False, "language": "TypeScript", "openIssuesCount": 2, "stargazersCount": 120},
]

MOCK_GITHUB_PRS = [
    {"id": "gpr-1", "repositoryId": "gr-1", "externalId": "gh-412", "number": 412, "title": "feat: checkout flow step navigation", "status": "AWAITING_REVIEW", "authorId": "tm-1", "reviewers": ["tm-3", "tm-5"], "ciStatus": "PASSING", "linkedWorkItemId": "wi-1", "url": "https://github.com/acme-org/acme-web/pull/412", "createdExternalAt": "2026-02-19T14:30:00Z"},
    {"id": "gpr-2", "repositoryId": "gr-2", "externalId": "gh-189", "number": 189, "title": "feat: Stripe payment intent endpoint", "status": "CHANGES_REQUESTED", "authorId": "tm-2", "reviewers": ["tm-4"], "ciStatus": "PASSING", "linkedWorkItemId": "wi-2", "url": "https://github.com/acme-org/acme-api/pull/189", "createdExternalAt": "2026-02-18T10:00:00Z"},
    {"id": "gpr-3", "repositoryId": "gr-1", "externalId": "gh-415", "number": 415, "title": "fix: mobile checkout responsive layout", "status": "APPROVED", "authorId": "tm-1", "reviewers": ["tm-3"], "ciStatus": "PASSING", "linkedWorkItemId": "wi-5", "url": "https://github.com/acme-org/acme-web/pull/415", "createdExternalAt": "2026-02-19T09:15:00Z"},
    {"id": "gpr-4", "repositoryId": "gr-2", "externalId": "gh-191", "number": 191, "title": "feat: webhook signature verification", "status": "OPEN", "authorId": "tm-2", "reviewers": ["tm-4", "tm-6"], "ciStatus": "FAILING", "linkedWorkItemId": "wi-6", "url": "https://github.com/acme-org/acme-api/pull/191", "createdExternalAt": "2026-02-18T16:00:00Z"},
    {"id": "gpr-5", "repositoryId": "gr-1", "externalId": "gh-413", "number": 413, "title": "feat: address autocomplete with Google Places", "status": "AWAITING_REVIEW", "authorId": "tm-5", "reviewers": ["tm-1"], "ciStatus": "PASSING", "linkedWorkItemId": "wi-8", "url": "https://github.com/acme-org/acme-web/pull/413", "createdExternalAt": "2026-02-19T16:45:00Z"},
    {"id": "gpr-6", "repositoryId": "gr-3", "externalId": "gh-78", "number": 78, "title": "chore: upgrade React Native to 0.76", "status": "MERGED", "authorId": "tm-5", "reviewers": ["tm-1"], "ciStatus": "PASSING", "url": "https://github.com/acme-org/acme-mobile/pull/78", "createdExternalAt": "2026-02-17T11:00:00Z", "mergedAt": "2026-02-18T14:00:00Z"},
]

MOCK_GITHUB_COMMITS = [
    {"id": "gc-1", "repositoryId": "gr-1", "sha": "a1b2c3d", "message": "feat: add checkout step component", "authorId": "tm-1", "branch": "feat/checkout-flow", "linkedTicketIds": ["PROJ-201"], "filesChanged": 5, "committedAt": "2026-02-19T14:15:00Z"},
    {"id": "gc-2", "repositoryId": "gr-2", "sha": "e4f5g6h", "message": "feat: implement Stripe payment intent creation", "authorId": "tm-2", "branch": "feat/payment-gateway", "linkedTicketIds": ["PROJ-202"], "filesChanged": 3, "committedAt": "2026-02-19T11:30:00Z"},
    {"id": "gc-3", "repositoryId": "gr-1", "sha": "i7j8k9l", "message": "fix: responsive grid on mobile checkout", "authorId": "tm-1", "branch": "fix/mobile-checkout", "linkedTicketIds": ["PROJ-205"], "filesChanged": 2, "committedAt": "2026-02-19T09:00:00Z"},
    {"id": "gc-4", "repositoryId": "gr-2", "sha": "m0n1o2p", "message": "feat: add Stripe webhook signature verification", "authorId": "tm-2", "branch": "feat/stripe-webhooks", "linkedTicketIds": ["PROJ-206"], "filesChanged": 4, "committedAt": "2026-02-18T17:45:00Z"},
    {"id": "gc-5", "repositoryId": "gr-1", "sha": "q3r4s5t", "message": "feat: Google Places autocomplete integration", "authorId": "tm-5", "branch": "feat/address-autocomplete", "linkedTicketIds": ["PROJ-208"], "filesChanged": 6, "committedAt": "2026-02-19T16:30:00Z"},
    {"id": "gc-6", "repositoryId": "gr-4", "sha": "u6v7w8x", "message": "chore: update Terraform modules to v5", "authorId": "tm-4", "branch": "chore/terraform-upgrade", "linkedTicketIds": [], "filesChanged": 12, "committedAt": "2026-02-18T14:00:00Z"},
    {"id": "gc-7", "repositoryId": "gr-1", "sha": "y9z0a1b", "message": "test: add E2E tests for cart summary", "authorId": "tm-3", "branch": "test/cart-e2e", "linkedTicketIds": ["PROJ-203"], "filesChanged": 3, "committedAt": "2026-02-18T11:20:00Z"},
]

_GH_HEADERS = {
    "Accept": "application/vnd.github.v3+json",
}


def _gh_auth_headers(access_token: str) -> dict:
    return {
        **_GH_HEADERS,
        "Authorization": f"Bearer {access_token}",
    }


# ===================================================================
# AUTH
# ===================================================================

@router.get("/auth")
async def get_github_authorize_url(current_user: dict = Depends(get_current_user)):
    """
    GET /auth
    Returns the GitHub OAuth authorize URL.
    Does NOT include redirect_uri -- GitHub uses whatever is configured in
    the OAuth App settings.
    """
    client_id = settings.github_client_id

    if not client_id:
        raise HTTPException(
            status_code=500, detail="GitHub OAuth not configured"
        )

    scope = "repo read:user user:email"
    authorize_url = (
        f"https://github.com/login/oauth/authorize"
        f"?client_id={client_id}"
        f"&scope={quote(scope)}"
    )

    return {"authorizeUrl": authorize_url}


@router.post("/auth")
async def exchange_github_code(
    body: dict,
    current_user: dict = Depends(get_current_user),
):
    """
    POST /auth
    Exchange authorization code for access token + fetch user info.
    """
    code = body.get("code")
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    client_id = settings.github_client_id
    client_secret = settings.github_client_secret

    if not client_id or not client_secret:
        raise HTTPException(
            status_code=500,
            detail="GitHub OAuth not configured on server",
        )

    async with httpx.AsyncClient(timeout=15.0) as client:
        # Exchange code for access token
        try:
            token_res = await client.post(
                "https://github.com/login/oauth/access_token",
                json={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code": code,
                },
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
            token_data = token_res.json()
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=500, detail=f"OAuth exchange failed: {str(e)}"
            )

        if token_data.get("error"):
            raise HTTPException(
                status_code=400,
                detail=token_data.get("error_description", token_data["error"]),
            )

        access_token = token_data.get("access_token")
        if not access_token:
            raise HTTPException(
                status_code=400, detail="No access token received"
            )

        # Fetch authenticated user info
        try:
            user_res = await client.get(
                "https://api.github.com/user",
                headers=_gh_auth_headers(access_token),
            )
            user_data = user_res.json()
        except httpx.RequestError:
            user_data = {}

    return {
        "success": True,
        "accessToken": access_token,
        "user": {
            "login": user_data.get("login"),
            "name": user_data.get("name"),
            "avatarUrl": user_data.get("avatar_url"),
            "profileUrl": user_data.get("html_url"),
        },
    }


# ===================================================================
# CALLBACK (OAuth redirect handler)
# ===================================================================

@router.get("/callback")
async def oauth_callback(
    code: str | None = Query(None),
    error: str | None = Query(None),
    error_description: str | None = Query(None),
):
    """
    GET /callback
    GitHub redirects here after the user authorizes.
    Exchanges the code for a token, then redirects back to the app
    with the token in URL parameters.
    """
    frontend_base = (
        settings.cors_origin_list[0]
        if settings.cors_origin_list
        else "http://localhost:3000"
    )

    if error or not code:
        error_msg = error_description or error or "Authorization was denied"
        return RedirectResponse(
            url=f"{frontend_base}/dev/github?github_error={quote(error_msg)}"
        )

    client_id = settings.github_client_id
    client_secret = settings.github_client_secret

    if not client_id or not client_secret:
        return RedirectResponse(
            url=f"{frontend_base}/dev/github?github_error={quote('Server not configured for GitHub OAuth')}"
        )

    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            # Exchange code for access token
            token_res = await client.post(
                "https://github.com/login/oauth/access_token",
                json={
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code": code,
                },
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
            token_data = token_res.json()

            if token_data.get("error"):
                error_msg = token_data.get(
                    "error_description", token_data["error"]
                )
                return RedirectResponse(
                    url=f"{frontend_base}/dev/github?github_error={quote(error_msg)}"
                )

            access_token = token_data.get("access_token", "")

            # Fetch user info
            user_res = await client.get(
                "https://api.github.com/user",
                headers=_gh_auth_headers(access_token),
            )
            user_data = user_res.json()

        except httpx.RequestError as e:
            return RedirectResponse(
                url=f"{frontend_base}/dev/github?github_error={quote(str(e))}"
            )

    params = urlencode({
        "github_token": access_token,
        "github_user": user_data.get("login", ""),
        "github_name": user_data.get("name") or user_data.get("login", ""),
        "github_avatar": user_data.get("avatar_url", ""),
    })
    return RedirectResponse(url=f"{frontend_base}/dev/github?{params}")


# ===================================================================
# REPOS
# ===================================================================

@router.get("/repos")
async def list_repos_demo(current_user: dict = Depends(get_current_user)):
    """GET /repos -- returns mock repos in demo mode."""
    if settings.is_demo_mode:
        return {"repos": MOCK_GITHUB_REPOS}
    return {"repos": []}


@router.post("/repos")
async def fetch_repos(
    body: dict,
    current_user: dict = Depends(get_current_user),
):
    """POST /repos -- fetch real repos using OAuth access token."""
    access_token = body.get("accessToken")
    if not access_token:
        raise HTTPException(status_code=400, detail="Missing access token")

    repos: list[dict] = []
    page = 1
    has_more = True

    async with httpx.AsyncClient(timeout=30.0) as client:
        while has_more and page <= 5:
            try:
                res = await client.get(
                    "https://api.github.com/user/repos",
                    params={
                        "per_page": 100,
                        "page": page,
                        "sort": "updated",
                        "affiliation": "owner,collaborator,organization_member",
                    },
                    headers=_gh_auth_headers(access_token),
                )
                if res.is_error:
                    err_data = {}
                    try:
                        err_data = res.json()
                    except Exception:
                        pass
                    raise HTTPException(
                        status_code=res.status_code,
                        detail=err_data.get(
                            "message",
                            f"GitHub API error: {res.status_code}",
                        ),
                    )
                data = res.json()
                repos.extend(data)
                has_more = len(data) == 100
                page += 1
            except httpx.RequestError as e:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to fetch repos: {str(e)}",
                )

    mapped = [
        {
            "id": str(r.get("id")),
            "name": r.get("name"),
            "fullName": r.get("full_name"),
            "defaultBranch": r.get("default_branch", "main"),
            "url": r.get("html_url"),
            "isPrivate": r.get("private", False),
            "language": r.get("language"),
            "openIssuesCount": r.get("open_issues_count", 0),
            "stargazersCount": r.get("stargazers_count", 0),
            "description": r.get("description"),
            "updatedAt": r.get("updated_at"),
            "owner": (r.get("owner") or {}).get("login"),
        }
        for r in repos
    ]
    return {"repos": mapped}


# ===================================================================
# PULLS
# ===================================================================

@router.get("/pulls")
async def list_pulls_demo(
    repo: str = Query(""),
    current_user: dict = Depends(get_current_user),
):
    """GET /pulls?repo=... -- list PRs (demo mock)."""
    if settings.is_demo_mode:
        if repo:
            filtered = [
                pr for pr in MOCK_GITHUB_PRS
                if any(
                    r["fullName"] == repo and r["id"] == pr["repositoryId"]
                    for r in MOCK_GITHUB_REPOS
                )
            ]
            return {"pulls": filtered}
        return {"pulls": MOCK_GITHUB_PRS}
    return {"pulls": []}


@router.post("/pulls")
async def fetch_pulls(
    body: dict,
    current_user: dict = Depends(get_current_user),
):
    """POST /pulls -- fetch real PRs for linked repos using OAuth access token."""
    access_token = body.get("accessToken")
    repos = body.get("repos", [])

    if not access_token or not repos:
        raise HTTPException(
            status_code=400, detail="Missing accessToken or repos"
        )

    all_prs: list[dict] = []

    async with httpx.AsyncClient(timeout=60.0) as client:
        for repo_full_name in repos:
            try:
                res = await client.get(
                    f"https://api.github.com/repos/{repo_full_name}/pulls",
                    params={
                        "state": "all",
                        "per_page": 30,
                        "sort": "updated",
                        "direction": "desc",
                    },
                    headers=_gh_auth_headers(access_token),
                )
                if res.is_error:
                    continue
                data = res.json()

                for pr in data:
                    # Determine status
                    status = "OPEN"
                    if pr.get("merged_at"):
                        status = "MERGED"
                    elif pr.get("state") == "closed":
                        status = "CLOSED"
                    elif pr.get("requested_reviewers"):
                        status = "AWAITING_REVIEW"

                    # Determine review state for open PRs
                    review_status = status
                    if pr.get("state") == "open":
                        try:
                            reviews_res = await client.get(
                                f"https://api.github.com/repos/{repo_full_name}/pulls/{pr['number']}/reviews",
                                headers=_gh_auth_headers(access_token),
                            )
                            if reviews_res.is_success:
                                reviews = reviews_res.json()
                                has_approval = any(
                                    r.get("state") == "APPROVED"
                                    for r in reviews
                                )
                                has_changes_requested = any(
                                    r.get("state") == "CHANGES_REQUESTED"
                                    for r in reviews
                                )
                                if has_approval:
                                    review_status = "APPROVED"
                                elif has_changes_requested:
                                    review_status = "CHANGES_REQUESTED"
                                elif pr.get("requested_reviewers"):
                                    review_status = "AWAITING_REVIEW"
                        except httpx.RequestError:
                            pass

                    all_prs.append({
                        "id": str(pr.get("id")),
                        "number": pr.get("number"),
                        "title": pr.get("title"),
                        "status": review_status,
                        "state": pr.get("state"),
                        "author": (pr.get("user") or {}).get("login", "Unknown"),
                        "authorAvatar": (pr.get("user") or {}).get("avatar_url", ""),
                        "repo": repo_full_name,
                        "url": pr.get("html_url"),
                        "createdAt": pr.get("created_at"),
                        "updatedAt": pr.get("updated_at"),
                        "mergedAt": pr.get("merged_at"),
                        "closedAt": pr.get("closed_at"),
                        "draft": pr.get("draft", False),
                        "reviewers": [
                            r.get("login")
                            for r in (pr.get("requested_reviewers") or [])
                        ],
                        "additions": pr.get("additions"),
                        "deletions": pr.get("deletions"),
                        "changedFiles": pr.get("changed_files"),
                        "branch": (pr.get("head") or {}).get("ref", ""),
                        "baseBranch": (pr.get("base") or {}).get("ref", ""),
                    })
            except httpx.RequestError:
                # Skip failed repos
                continue

    # Sort by updated date descending
    all_prs.sort(key=lambda x: x.get("updatedAt") or "", reverse=True)

    return {"pulls": all_prs}


# ===================================================================
# COMMITS
# ===================================================================

@router.get("/commits")
async def list_commits_demo(
    repo: str = Query(""),
    current_user: dict = Depends(get_current_user),
):
    """GET /commits?repo=... -- list commits (demo mock)."""
    if settings.is_demo_mode:
        if repo:
            filtered = [
                c for c in MOCK_GITHUB_COMMITS
                if any(
                    r["fullName"] == repo and r["id"] == c["repositoryId"]
                    for r in MOCK_GITHUB_REPOS
                )
            ]
            return {"commits": filtered}
        return {"commits": MOCK_GITHUB_COMMITS}
    return {"commits": []}


@router.post("/commits")
async def fetch_commits(
    body: dict,
    current_user: dict = Depends(get_current_user),
):
    """POST /commits -- fetch real commits for linked repos."""
    access_token = body.get("accessToken")
    repos = body.get("repos", [])

    if not access_token or not repos:
        raise HTTPException(
            status_code=400, detail="Missing accessToken or repos"
        )

    all_commits: list[dict] = []

    async with httpx.AsyncClient(timeout=60.0) as client:
        for repo_full_name in repos:
            try:
                res = await client.get(
                    f"https://api.github.com/repos/{repo_full_name}/commits",
                    params={"per_page": 30},
                    headers=_gh_auth_headers(access_token),
                )
                if res.is_error:
                    continue
                data = res.json()

                for c in data:
                    commit_obj = c.get("commit") or {}
                    author_obj = commit_obj.get("author") or {}
                    gh_author = c.get("author") or {}

                    all_commits.append({
                        "sha": c.get("sha"),
                        "message": commit_obj.get("message", ""),
                        "author": (
                            author_obj.get("name")
                            or gh_author.get("login", "Unknown")
                        ),
                        "authorLogin": gh_author.get("login", ""),
                        "authorAvatar": gh_author.get("avatar_url", ""),
                        "date": author_obj.get("date", ""),
                        "repo": repo_full_name,
                        "url": c.get("html_url"),
                        "additions": (c.get("stats") or {}).get("additions"),
                        "deletions": (c.get("stats") or {}).get("deletions"),
                    })
            except httpx.RequestError:
                # Skip failed repos
                continue

    # Sort by date descending
    all_commits.sort(key=lambda x: x.get("date") or "", reverse=True)

    return {"commits": all_commits}


# ===================================================================
# EVENTS
# ===================================================================

@router.post("/events")
async def fetch_events(
    body: dict,
    current_user: dict = Depends(get_current_user),
):
    """POST /events -- fetch recent activity events for linked repos."""
    access_token = body.get("accessToken")
    repos = body.get("repos", [])

    if not access_token or not repos:
        raise HTTPException(
            status_code=400, detail="Missing accessToken or repos"
        )

    all_events: list[dict] = []

    async with httpx.AsyncClient(timeout=60.0) as client:
        for repo_full_name in repos:
            try:
                res = await client.get(
                    f"https://api.github.com/repos/{repo_full_name}/events",
                    params={"per_page": 50},
                    headers=_gh_auth_headers(access_token),
                )
                if res.is_error:
                    continue
                data = res.json()

                for event in data:
                    payload = event.get("payload") or {}
                    raw_type = event.get("type", "Unknown")

                    # Build human-readable description
                    description = ""
                    event_type = "other"
                    branch = (payload.get("ref") or "").replace(
                        "refs/heads/", ""
                    )

                    if raw_type == "PushEvent":
                        size = payload.get("size", 0)
                        suffix = "s" if size != 1 else ""
                        description = (
                            f"Pushed {size} commit{suffix} to {branch}"
                        )
                        event_type = "push"
                    elif raw_type == "PullRequestEvent":
                        pr = payload.get("pull_request") or {}
                        description = (
                            f"{payload.get('action', 'updated')} PR "
                            f"#{pr.get('number')}: {pr.get('title', '')}"
                        )
                        event_type = "pull_request"
                    elif raw_type == "CreateEvent":
                        description = (
                            f"Created {payload.get('ref_type', 'ref')} "
                            f"{payload.get('ref', '')}"
                        )
                        event_type = "create"
                    elif raw_type == "DeleteEvent":
                        description = (
                            f"Deleted {payload.get('ref_type', 'ref')} "
                            f"{payload.get('ref', '')}"
                        )
                        event_type = "delete"
                    elif raw_type == "IssuesEvent":
                        issue = payload.get("issue") or {}
                        description = (
                            f"{payload.get('action', 'updated')} issue "
                            f"#{issue.get('number')}: {issue.get('title', '')}"
                        )
                        event_type = "issue"
                    elif raw_type == "IssueCommentEvent":
                        issue = payload.get("issue") or {}
                        description = (
                            f"Commented on #{issue.get('number')}: "
                            f"{issue.get('title', '')}"
                        )
                        event_type = "comment"
                    elif raw_type == "PullRequestReviewEvent":
                        pr = payload.get("pull_request") or {}
                        review = payload.get("review") or {}
                        description = (
                            f"Reviewed PR #{pr.get('number')}: "
                            f"{review.get('state', '')}"
                        )
                        event_type = "review"
                    elif raw_type == "ReleaseEvent":
                        release = payload.get("release") or {}
                        description = (
                            f"{payload.get('action', 'published')} release "
                            f"{release.get('tag_name', '')}"
                        )
                        event_type = "release"
                    elif raw_type == "ForkEvent":
                        forkee = payload.get("forkee") or {}
                        description = (
                            f"Forked to {forkee.get('full_name', '')}"
                        )
                        event_type = "fork"
                    elif raw_type == "WatchEvent":
                        description = "Starred the repository"
                        event_type = "star"
                    else:
                        description = (
                            raw_type.replace("Event", "")
                            if raw_type
                            else "Activity"
                        )

                    # Extract commits from PushEvent
                    commits = []
                    if raw_type == "PushEvent":
                        commits = [
                            {
                                "sha": (c.get("sha") or "")[:7],
                                "message": c.get("message"),
                                "author": (c.get("author") or {}).get("name"),
                                "url": c.get("url"),
                            }
                            for c in payload.get("commits", [])
                        ]

                    actor = event.get("actor") or {}
                    pr_payload = payload.get("pull_request") or {}
                    issue_payload = payload.get("issue") or {}

                    all_events.append({
                        "id": event.get("id"),
                        "type": event_type,
                        "rawType": raw_type,
                        "repo": repo_full_name,
                        "actor": actor.get("login", "Unknown"),
                        "actorAvatar": actor.get("avatar_url", ""),
                        "description": description,
                        "branch": branch,
                        "commits": commits,
                        "commitCount": (
                            payload.get("size", 0)
                            if raw_type == "PushEvent"
                            else 0
                        ),
                        "createdAt": event.get("created_at"),
                        "url": (
                            pr_payload.get("html_url")
                            or issue_payload.get("html_url")
                            or f"https://github.com/{repo_full_name}"
                        ),
                    })
            except httpx.RequestError:
                # Skip failed repos
                continue

    # Sort by date descending
    all_events.sort(
        key=lambda x: x.get("createdAt") or "", reverse=True
    )

    return {"events": all_events}


# ===================================================================
# WEBHOOKS
# ===================================================================

@router.post("/webhooks")
async def receive_webhook(request: Request):
    """
    POST /webhooks
    Receive GitHub webhook events.
    Verifies HMAC-SHA256 signature using webhook secret.
    """
    try:
        signature = request.headers.get("x-hub-signature-256")
        event = request.headers.get("x-github-event")
        body_bytes = await request.body()
        body_text = body_bytes.decode("utf-8")

        # TODO: Verify webhook signature
        # webhook_secret = settings.github_webhook_secret
        # if not verify_github_signature(body_text, signature, webhook_secret):
        #     raise HTTPException(status_code=401, detail="Invalid signature")

        payload = json.loads(body_text)

        # Process webhook event
        if event == "pull_request":
            # TODO: Update local PullRequest record
            pass
        elif event == "push":
            # TODO: Update local Commit records
            pass
        elif event in ("check_run", "check_suite"):
            # TODO: Update CI status on linked PullRequest
            pass
        else:
            # Log unhandled event type
            pass

        # TODO: Append to audit log
        return {
            "received": True,
            "event": event,
            "action": payload.get("action"),
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
    except Exception:
        raise HTTPException(
            status_code=500, detail="Webhook processing failed"
        )
