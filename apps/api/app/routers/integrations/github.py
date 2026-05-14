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

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select as sa_select
from ...auth.supabase import get_current_user
from ...database import get_db
from ...config import settings
import httpx

router = APIRouter()


# ===================================================================
# WEBHOOK CONSTANTS — Hotfix 7
# ===================================================================
# Public URL where GitHub will POST webhook events. We hard-code the
# Container Apps FQDN so we don't depend on a request-time URL (which
# may not be available outside the request scope, e.g. when auto-
# installing during /update-linked-repos).
#
# If the deployment moves to a custom domain, update this constant +
# re-run install for each linked repo via /install-webhook.
GITHUB_WEBHOOK_URL = (
    "https://plan2sprint-api.purplebeach-150945ee.westus3.azurecontainerapps.io"
    "/api/integrations/github/webhooks"
)
GITHUB_WEBHOOK_EVENTS = [
    "push",
    "pull_request",
    "pull_request_review",
    "check_run",
    "check_suite",
]


def _new_webhook_secret() -> str:
    """Generate a 64-char hex secret for HMAC signing GitHub webhooks.

    Stored once per org in ``tool_connections.config["webhook_secret"]``.
    The same secret is set on every webhook GitHub creates for that org's
    repos, so the receiver can verify any incoming event by looking up
    the org by repo and checking the signature against this single key.
    """
    import secrets
    return secrets.token_hex(32)


def _verify_github_signature(body_bytes: bytes, signature: str, secret: str) -> bool:
    """Constant-time HMAC-SHA256 verify of a GitHub webhook payload.

    GitHub's ``X-Hub-Signature-256`` header is in the form
    ``sha256=<hex>``. We compute the same and compare with
    ``hmac.compare_digest`` to avoid timing leaks.
    """
    import hmac
    import hashlib
    if not signature or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        secret.encode("utf-8"), body_bytes, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


# ===================================================================
# HELPERS: GitHub connection persistence
# ===================================================================

async def _get_github_connection(db: AsyncSession, org_id: str):
    """Get stored GitHub ToolConnection for this org."""
    from ...models.tool_connection import ToolConnection
    result = await db.execute(
        sa_select(ToolConnection).where(
            ToolConnection.organization_id == org_id,
            ToolConnection.source_tool == "GITHUB",
        )
    )
    return result.scalar_one_or_none()


async def _resolve_github_token(db: AsyncSession, org_id: str, body_token: str | None = None) -> str:
    """Get GitHub token from DB (preferred) or fallback to body token.

    Security: always prefer DB-stored token to prevent cross-org token injection.
    """
    from ...services.encryption import decrypt_token
    conn = await _get_github_connection(db, org_id)
    if conn and conn.access_token:
        try:
            return decrypt_token(conn.access_token)
        except Exception:
            pass
    if body_token:
        return body_token
    return ""


async def _save_github_connection(
    db: AsyncSession, org_id: str, access_token: str,
    user_login: str = "", user_name: str = "", avatar_url: str = "",
    linked_repos: list[str] | None = None,
):
    """Create or update GitHub ToolConnection with access token.

    Hotfix 6 — per-developer repo persistence.
    --------------------------------------------
    Previously this stored `linked_repos` as a single org-level array. When
    multiple developers each bootstrapped their browser's localStorage to
    the backend, whichever dev called last would clobber the others'
    selection — which is exactly the "repos disappear after re-login"
    symptom we were chasing.

    Now we keep two structures inside ``config``:

      * ``linked_repos_by_user`` : ``{github_username: [repos]}``
        The authoritative per-developer selection. Each dev's bootstrap
        only mutates their own bucket — Pallavi's selection can never
        erase Mike's.

      * ``linked_repos`` : ``[unique_repos]``
        Auto-derived union of every developer's bucket. Kept for
        backward compatibility — the sync loop, the webhook
        `_resolve_org_from_repo`, and the existing PO activity feed
        all read from here, so they keep working unchanged.

    The helper rebuilds the union every time, so it never grows stale.
    """
    from ...models.tool_connection import ToolConnection
    from ...models.base import generate_cuid

    conn = await _get_github_connection(db, org_id)
    existing_config = (conn.config or {}) if conn else {}
    repos_by_user: dict[str, list[str]] = dict(
        existing_config.get("linked_repos_by_user") or {}
    )
    existing_org_repos: list[str] = list(
        existing_config.get("linked_repos") or []
    )

    # Only write into the calling developer's bucket. If user_login is
    # blank (legacy callers without it) we fall back to the org-level
    # array so behaviour is unchanged for them.
    if user_login:
        repos_by_user[user_login] = list(linked_repos or [])
        # Migration safety — pre-Hotfix-6 configs only had the org-level
        # ``linked_repos`` array. The very first dev to save under the new
        # scheme would otherwise shrink the union to just their own
        # selection, dropping repos other devs had previously added. We
        # union the existing org-level array in too so nothing disappears.
        # If the legacy bucket was already migrated (i.e. sum of per-user
        # buckets ⊇ existing_org_repos) this is a no-op.
        merged_union = sorted(
            {r for v in repos_by_user.values() for r in v}.union(
                existing_org_repos
            )
        )
    else:
        # No user attribution → keep behaviour: replace org-level array.
        merged_union = sorted(set(linked_repos or []))

    new_config = {
        **existing_config,
        "user_login": user_login or existing_config.get("user_login", ""),
        "user_name": user_name or existing_config.get("user_name", ""),
        "avatar_url": avatar_url or existing_config.get("avatar_url", ""),
        "linked_repos_by_user": repos_by_user,
        "linked_repos": merged_union,
    }

    if conn:
        # Only overwrite the access_token when the caller actually passed one
        # — bootstraps that just want to update repos shouldn't blank the
        # org-level token.
        if access_token:
            conn.access_token = access_token
        conn.config = new_config
    else:
        conn = ToolConnection(
            id=generate_cuid(),
            organization_id=org_id,
            source_tool="GITHUB",
            access_token=access_token,
            config=new_config,
        )
        db.add(conn)

    await db.commit()
    return conn

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
# STATUS — used by IntegrationProvider to mark GitHub as "connected"
# ===================================================================

@router.get("/status")
async def github_status(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    GET /status
    Returns whether a GitHub ToolConnection exists for this org.
    The PO's integration context uses this to decide if the GitHub
    page should show the connected view.

    Hotfix 6 — when the calling user has their own bucket in
    ``linked_repos_by_user``, return THAT list instead of the org-wide
    union, so the developer page rehydrates with their own selection
    rather than every other developer's repos pooled together.
    """
    from ...models.team_member import TeamMember

    org_id = current_user.get("organization_id", "")
    conn = await _get_github_connection(db, org_id)
    if conn and conn.access_token:
        from ...services.encryption import decrypt_token
        cfg = conn.config or {}
        # Decrypt token so frontend can use it for GitHub API calls
        try:
            decrypted_token = decrypt_token(conn.access_token)
        except Exception:
            # Token may be stored unencrypted (legacy) — use as-is
            decrypted_token = conn.access_token or ""

        # Resolve the calling developer's GitHub login (if any) so we can
        # return their own bucket rather than the org union.
        # Hotfix 38 — a user may have MULTIPLE TeamMember rows in the
        # same org (one per project they're on); ``scalar_one_or_none()``
        # raises ``MultipleResultsFound`` in that case and crashed the
        # endpoint with 500. Take the first matching row that has a
        # github_username, or just the first row if none are linked.
        repos_by_user = cfg.get("linked_repos_by_user") or {}
        caller_login = ""
        email = (current_user.get("email") or "").lower()
        if email:
            tms = (
                await db.execute(
                    sa_select(TeamMember).where(
                        TeamMember.organization_id == org_id,
                        TeamMember.email.ilike(email),
                    )
                )
            ).scalars().all()
            # Prefer a row that already has a github_username linked.
            tm = next((t for t in tms if t.github_username), tms[0] if tms else None)
            if tm and tm.github_username:
                caller_login = tm.github_username

        if caller_login and caller_login in repos_by_user:
            personal_repos = list(repos_by_user[caller_login])
        else:
            personal_repos = cfg.get("linked_repos", [])

        return {
            "connected": True,
            "user_login": cfg.get("user_login", ""),
            "user_name": cfg.get("user_name", ""),
            "avatar_url": cfg.get("avatar_url", ""),
            "linked_repos": personal_repos,
            "linked_repos_org": cfg.get("linked_repos", []),
            "linked_repos_by_user": repos_by_user,
            "caller_login": caller_login or None,
            "access_token": decrypted_token,
            "connected_at": conn.created_at.isoformat() if conn.created_at else None,
        }
    return {"connected": False}


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
# TOKEN PERSISTENCE
# ===================================================================

@router.post("/save-token")
async def save_github_token(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /save-token — persist GitHub access token + linked repos to DB.

    Called by the developer frontend after GitHub OAuth to store the token
    so the PO's GitHub monitoring can fetch live data.
    """
    access_token = body.get("accessToken", "")
    user_login = body.get("userLogin", "")
    user_name = body.get("userName", "")
    avatar_url = body.get("avatarUrl", "")
    linked_repos = body.get("linkedRepos", [])

    if not access_token:
        raise HTTPException(status_code=400, detail="accessToken is required")

    org_id = current_user.get("organization_id", "demo-org")
    await _save_github_connection(
        db, org_id, access_token,
        user_login=user_login, user_name=user_name,
        avatar_url=avatar_url, linked_repos=linked_repos,
    )
    return {"ok": True}


async def _ensure_webhook_secret(conn) -> str:
    """Return (and lazily seed) the HMAC secret for this org's webhooks.

    Stored inside ``ToolConnection.config["webhook_secret"]`` so it's
    encrypted-at-rest in the same row as the access token. Generated
    once per org; same secret used for every webhook GitHub creates
    against any of that org's linked repos.
    """
    cfg = dict(conn.config or {})
    secret = cfg.get("webhook_secret")
    if not secret:
        secret = _new_webhook_secret()
        cfg["webhook_secret"] = secret
        conn.config = cfg
    return secret


async def _install_github_webhook_for_repo(
    repo_full_name: str,
    access_token: str,
    secret: str,
) -> dict:
    """Install (or detect existing) Plan2Sprint webhook on a single repo.

    Returns a dict describing the outcome — never raises — so the caller
    can keep going across other repos in a batch even if one fails (e.g.
    no admin permission on a fork).

    Outcomes:
      * ``{"status": "created", "hookId": <int>}`` — fresh install
      * ``{"status": "exists", "hookId": <int>}`` — Plan2Sprint hook
        was already there (idempotent re-run)
      * ``{"status": "permission_denied"}`` — 403/404 from GitHub; the
        access token doesn't have admin on this repo
      * ``{"status": "error", "detail": "<msg>"}`` — anything else
    """
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"Bearer {access_token}",
    }
    list_url = f"https://api.github.com/repos/{repo_full_name}/hooks"
    create_url = list_url
    config_payload = {
        "url": GITHUB_WEBHOOK_URL,
        "content_type": "json",
        "secret": secret,
        "insecure_ssl": "0",
    }
    body = {
        "name": "web",
        "active": True,
        "events": GITHUB_WEBHOOK_EVENTS,
        "config": config_payload,
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        # Idempotency — if a webhook with our URL already exists, reuse
        # it rather than creating a duplicate. Just match on the URL field
        # so a manually-added entry pointing at us also gets adopted.
        try:
            existing = await client.get(list_url, headers=headers)
        except Exception as e:
            return {"status": "error", "detail": f"network: {e!r}"}
        if existing.status_code in (403, 404):
            return {"status": "permission_denied"}
        if existing.is_success:
            for hook in existing.json():
                hcfg = (hook or {}).get("config") or {}
                if hcfg.get("url") == GITHUB_WEBHOOK_URL:
                    # Already installed; rotate the secret so the new
                    # value matches what we just persisted, in case the
                    # org rotated keys.
                    hook_id = hook.get("id")
                    try:
                        await client.patch(
                            f"{list_url}/{hook_id}",
                            headers=headers,
                            json={
                                "active": True,
                                "events": GITHUB_WEBHOOK_EVENTS,
                                "config": config_payload,
                            },
                        )
                    except Exception:
                        # Even if patch fails, we still consider the hook
                        # present — caller decides whether to retry.
                        pass
                    return {"status": "exists", "hookId": hook_id}

        # No matching hook → create.
        try:
            resp = await client.post(create_url, headers=headers, json=body)
        except Exception as e:
            return {"status": "error", "detail": f"network: {e!r}"}
        if resp.status_code in (403, 404):
            return {"status": "permission_denied"}
        if resp.status_code == 422:
            # Per GitHub docs this fires when the hook already exists by
            # URL. Treat as idempotent success.
            return {"status": "exists"}
        if not resp.is_success:
            return {
                "status": "error",
                "detail": f"github {resp.status_code}: {resp.text[:200]}",
            }
        data = resp.json() or {}
        return {"status": "created", "hookId": data.get("id")}


async def _install_webhooks_for_repos(
    db: AsyncSession,
    conn,
    repos: list[str],
    access_token: str,
) -> dict[str, dict]:
    """Install webhooks for each repo in ``repos`` and persist hook IDs.

    Per-repo outcome saved into ``conn.config["webhooks_by_repo"]`` so we
    can show install state in the UI later and avoid re-installing on
    every refresh.
    """
    if not repos or not access_token:
        return {}

    secret = await _ensure_webhook_secret(conn)
    cfg = dict(conn.config or {})
    by_repo: dict[str, dict] = dict(cfg.get("webhooks_by_repo") or {})

    results: dict[str, dict] = {}
    for repo in repos:
        # Skip if we already have a confirmed-installed record AND the URL
        # constant hasn't changed since (rare). This keeps the batch fast
        # when called from /update-linked-repos.
        prev = by_repo.get(repo) or {}
        if prev.get("status") in ("created", "exists") and prev.get("url") == GITHUB_WEBHOOK_URL:
            results[repo] = prev
            continue
        outcome = await _install_github_webhook_for_repo(repo, access_token, secret)
        outcome["url"] = GITHUB_WEBHOOK_URL
        from datetime import datetime as _dt, timezone as _tz
        outcome["lastAttemptAt"] = _dt.now(_tz.utc).isoformat()
        by_repo[repo] = outcome
        results[repo] = outcome

    cfg["webhooks_by_repo"] = by_repo
    conn.config = cfg
    await db.commit()
    return results


async def _lazy_migrate_webhook_secret(org_id: str) -> None:
    """Hotfix 50 — Background task that backfills the webhook secret for
    a legacy connection on its first inbound webhook event.

    Runs from FastAPI BackgroundTasks after the webhook response has
    already been returned, so the user-facing event handler stays fast
    and never waits on GitHub's API.

    Race-protection: stamps ``cfg["webhook_migration_started_at"]`` before
    starting and refuses to start again if the previous attempt began
    within the last 5 minutes. Worst case if both attempts run is the
    last-write-wins race on the secret, which is fine because both
    attempts use the same ``_install_github_webhook_for_repo`` PATCH path
    and GitHub stores whichever secret got there last.
    """
    from datetime import datetime, timezone, timedelta
    from ...database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        # Re-fetch the connection in this task's session.
        from sqlalchemy import select as _sa_select
        from ...models.tool_connection import ToolConnection
        result = await db.execute(
            _sa_select(ToolConnection).where(
                ToolConnection.organization_id == org_id,
                ToolConnection.source_tool == "GITHUB",
            )
        )
        conn = result.scalar_one_or_none()
        if not conn or not conn.access_token:
            _logger.warning(
                f"[lazy-migrate] org={org_id}: no GitHub connection "
                f"found, skipping migration"
            )
            return

        cfg = dict(conn.config or {})

        # Already migrated? Nothing to do.
        if cfg.get("webhook_secret"):
            _logger.info(
                f"[lazy-migrate] org={org_id}: webhook_secret already set, "
                f"skipping"
            )
            return

        # Race guard — skip if another attempt started within the last 5 min.
        started_at_iso = cfg.get("webhook_migration_started_at") or ""
        if started_at_iso:
            try:
                started_at = datetime.fromisoformat(started_at_iso)
                if started_at.tzinfo is None:
                    started_at = started_at.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) - started_at < timedelta(minutes=5):
                    _logger.info(
                        f"[lazy-migrate] org={org_id}: another migration "
                        f"started at {started_at_iso}, skipping (race guard)"
                    )
                    return
            except Exception:
                pass

        # Mark started, persist, then run.
        cfg["webhook_migration_started_at"] = datetime.now(timezone.utc).isoformat()
        conn.config = cfg
        await db.commit()

        # Hotfix 57 — uniform token resolution via decrypt_token_safe.
        from ...services.encryption import decrypt_token_safe
        access_token = decrypt_token_safe(conn.access_token or "")
        if not access_token:
            _logger.warning(
                f"[lazy-migrate] org={org_id}: empty/unresolvable access token, "
                f"aborting migration"
            )
            return

        # Pick repos to migrate.
        repos = list(cfg.get("linked_repos") or [])
        if not repos:
            wbr = cfg.get("webhooks_by_repo") or {}
            repos = list(wbr.keys())
        if not repos:
            _logger.info(
                f"[lazy-migrate] org={org_id}: no linked repos to migrate"
            )
            return

        new_secret = _new_webhook_secret()
        results: dict[str, dict] = {}
        for repo in repos:
            outcome = await _install_github_webhook_for_repo(
                repo, access_token, new_secret
            )
            if outcome.get("status") == "exists":
                outcome["status"] = "rotated"
            outcome["url"] = GITHUB_WEBHOOK_URL
            outcome["rotatedAt"] = datetime.now(timezone.utc).isoformat()
            results[repo] = outcome

        # Persist new secret only if at least one repo succeeded.
        any_success = any(
            r.get("status") in ("rotated", "created") for r in results.values()
        )
        if any_success:
            cfg["webhook_secret"] = new_secret
            cfg["webhooks_by_repo"] = {**(cfg.get("webhooks_by_repo") or {}), **results}
            cfg["webhook_secret_rotated_at"] = datetime.now(timezone.utc).isoformat()
            cfg["webhook_secret_rotated_by"] = "lazy-auto-migration"
            cfg.pop("webhook_migration_started_at", None)
            conn.config = cfg
            await db.commit()
            _logger.info(
                f"[lazy-migrate] org={org_id}: SUCCESS — "
                f"rotated {sum(1 for r in results.values() if r.get('status')=='rotated')} "
                f"created {sum(1 for r in results.values() if r.get('status')=='created')} "
                f"perm_denied {sum(1 for r in results.values() if r.get('status')=='permission_denied')} "
                f"err {sum(1 for r in results.values() if r.get('status')=='error')}"
            )
        else:
            # Clear the in-progress marker so a future event can retry.
            cfg.pop("webhook_migration_started_at", None)
            conn.config = cfg
            await db.commit()
            _logger.warning(
                f"[lazy-migrate] org={org_id}: FAILED — no repos rotated. "
                f"Per-repo outcomes: {results}"
            )


@router.post("/install-webhook")
async def install_webhook(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /install-webhook — manually (re-)install webhooks for one or more repos.

    Body shape::
        { "repos": ["owner/name", ...] }   # explicit list, OR
        { }                                # empty → install for ALL
                                           # currently-linked repos

    Used both as an automatic step from /update-linked-repos and as a
    manual "Reinstall webhook" action from the UI when a previous
    install hit a permission error.
    """
    org_id = current_user.get("organization_id", "demo-org")
    conn = await _get_github_connection(db, org_id)
    if not conn or not conn.access_token:
        raise HTTPException(400, "GitHub not connected for this org.")

    # Resolve a usable token. Prefer the per-developer token of the
    # caller (since that's whose admin scope GitHub will check); fall
    # back to the org-level token.
    from ...services.encryption import decrypt_token
    from ...models.team_member import TeamMember

    access_token: str = ""
    email = (current_user.get("email") or "").lower()
    if email:
        tm = (
            await db.execute(
                sa_select(TeamMember).where(
                    TeamMember.organization_id == org_id,
                    TeamMember.email.ilike(email),
                )
            )
        ).scalar_one_or_none()
        if tm and tm.github_access_token:
            # Hotfix 57 (HIGH-5) — was reading plaintext directly.
            from ...services.encryption import decrypt_token_safe
            access_token = decrypt_token_safe(tm.github_access_token)
    if not access_token:
        from ...services.encryption import decrypt_token_safe
        access_token = decrypt_token_safe(conn.access_token or "")

    repos = body.get("repos")
    if not repos:
        cfg = conn.config or {}
        repos = list(cfg.get("linked_repos") or [])
    if not repos:
        return {"ok": True, "installed": {}, "skipped": "no-repos"}

    results = await _install_webhooks_for_repos(db, conn, repos, access_token)
    return {"ok": True, "installed": results}


@router.post("/backfill-webhook-secrets")
async def backfill_webhook_secrets(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Hotfix 48 — One-time migration: rotate webhook signing secrets onto
    every existing GitHub webhook for the caller's org.

    Unlike ``/install-webhook``, this **forces** a per-repo PATCH against
    GitHub (no skip-optimization), guaranteeing the secret stored on
    ``ToolConnection.config["webhook_secret"]`` matches the secret GitHub
    will use to sign events. This is what unblocks the strict-rejection
    behaviour that Hotfix 47 attempted to ship before Hotfix 47b reverted
    it.

    Operator flow:
      1. Hit this endpoint once (PO/admin role).
      2. Inspect the per-repo report — every repo should be ``rotated`` or
         ``exists`` (which means PATCH succeeded).
      3. Once all 5 production connections show clean reports, ship
         Hotfix 49 to flip ``STRICT_GITHUB_WEBHOOK_VERIFICATION`` on.

    Per-repo outcomes mirror ``_install_github_webhook_for_repo`` plus a
    ``rotated`` status to distinguish "we PATCHed an existing hook" from
    "we created a new one".
    """
    from ...services.encryption import decrypt_token
    from ...models.team_member import TeamMember

    org_id = current_user.get("organization_id", "demo-org")
    conn = await _get_github_connection(db, org_id)
    if not conn or not conn.access_token:
        raise HTTPException(400, "GitHub not connected for this org.")

    # Resolve a usable token. Prefer the caller's per-developer token
    # (admin scope on their own repos), fall back to org-level token.
    access_token: str = ""
    email = (current_user.get("email") or "").lower()
    if email:
        tm = (
            await db.execute(
                sa_select(TeamMember).where(
                    TeamMember.organization_id == org_id,
                    TeamMember.email.ilike(email),
                )
            )
        ).scalar_one_or_none()
        if tm and tm.github_access_token:
            # Hotfix 57 (HIGH-5) — handle both encrypted and legacy plaintext.
            from ...services.encryption import decrypt_token_safe
            access_token = decrypt_token_safe(tm.github_access_token)
    if not access_token:
        from ...services.encryption import decrypt_token_safe
        access_token = decrypt_token_safe(conn.access_token or "")
        if not access_token:
            raise HTTPException(500, "Cannot resolve GitHub access token")

    # Generate a fresh secret. ``_ensure_webhook_secret`` only creates one
    # if missing — we want a rotation regardless, so override directly.
    new_secret = _new_webhook_secret()
    cfg = dict(conn.config or {})
    by_repo: dict[str, dict] = dict(cfg.get("webhooks_by_repo") or {})

    # Determine which repos to migrate. Prefer the explicit list in
    # ``webhooks_by_repo``; fall back to ``linked_repos`` so connections
    # whose webhook records were never persisted still get covered.
    repos_to_migrate: list[str] = list(by_repo.keys())
    if not repos_to_migrate:
        repos_to_migrate = list(cfg.get("linked_repos") or [])

    results: dict[str, dict] = {}
    for repo in repos_to_migrate:
        outcome = await _install_github_webhook_for_repo(
            repo, access_token, new_secret
        )
        # Promote "exists" → "rotated" so the caller can tell at-a-glance
        # that we actively pushed the new secret to GitHub.
        if outcome.get("status") == "exists":
            outcome["status"] = "rotated"
        outcome["url"] = GITHUB_WEBHOOK_URL
        from datetime import datetime as _dt, timezone as _tz
        outcome["rotatedAt"] = _dt.now(_tz.utc).isoformat()
        by_repo[repo] = outcome
        results[repo] = outcome

    # Persist the new secret + the per-repo outcomes only after we've
    # attempted GitHub. If GitHub rejected every PATCH (e.g. expired
    # token), keep the old secret in place so the live integration
    # doesn't break further.
    any_success = any(
        r.get("status") in ("rotated", "created") for r in results.values()
    )
    if any_success:
        cfg["webhook_secret"] = new_secret
        cfg["webhooks_by_repo"] = by_repo
        cfg["webhook_secret_rotated_at"] = (
            __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ).isoformat()
        )
        conn.config = cfg
        await db.commit()

    summary = {
        "ok": any_success,
        "orgId": org_id,
        "reposAttempted": len(repos_to_migrate),
        "reposRotated": sum(1 for r in results.values() if r.get("status") == "rotated"),
        "reposCreated": sum(1 for r in results.values() if r.get("status") == "created"),
        "reposPermissionDenied": sum(1 for r in results.values() if r.get("status") == "permission_denied"),
        "reposError": sum(1 for r in results.values() if r.get("status") == "error"),
        "secretPersisted": any_success,
        "perRepo": results,
    }
    return summary


@router.post("/refetch-commit-authors")
async def refetch_commit_authors(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Backfill ``Commit.author_email`` / ``author_name`` for every
    commit in the caller's org whose email is NULL. Thin HTTP wrapper
    around ``github_author_refetch.refetch_orphan_authors`` — the same
    function the standup generator calls inline.

    Safe to re-run — only touches rows with NULL ``author_email``.
    """
    from ...services.github_author_refetch import refetch_orphan_authors
    org_id = current_user.get("organization_id", "demo-org")
    result = await refetch_orphan_authors(db, org_id)
    await db.commit()
    return {"ok": True, "orgId": org_id, **result}


@router.post("/update-linked-repos")
async def update_linked_repos(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /update-linked-repos — update the list of repos tracked for PO monitoring.

    Hotfix 6 — scope writes to the calling developer's bucket so other
    developers' selections aren't erased. The body may pass an explicit
    ``userLogin`` (the GitHub login the repo selection belongs to);
    otherwise we resolve it from the caller's ``team_members`` row.

    Hotfix 7 — after persisting, auto-install webhooks for any newly
    added repos. Failures (permission, network) are recorded in
    ``config.webhooks_by_repo`` but don't fail the request.
    """
    from ...models.team_member import TeamMember

    linked_repos = body.get("linkedRepos", [])
    explicit_login = (body.get("userLogin") or "").strip()
    org_id = current_user.get("organization_id", "demo-org")

    # Prefer the explicit github login from the body (the dev page knows it
    # because it just OAuth'd). Fall back to looking it up from the caller's
    # TeamMember row by email.
    user_login = explicit_login
    if not user_login:
        email = (current_user.get("email") or "").lower()
        if email:
            tm = (
                await db.execute(
                    sa_select(TeamMember).where(
                        TeamMember.organization_id == org_id,
                        TeamMember.email.ilike(email),
                    )
                )
            ).scalar_one_or_none()
            if tm and tm.github_username:
                user_login = tm.github_username

    conn = await _get_github_connection(db, org_id)
    if not conn:
        return {"ok": True, "skipped": "no-connection"}

    config = dict(conn.config or {})
    repos_by_user: dict[str, list[str]] = dict(
        config.get("linked_repos_by_user") or {}
    )
    existing_org_repos: list[str] = list(config.get("linked_repos") or [])
    if user_login:
        repos_by_user[user_login] = list(linked_repos)
        config["linked_repos_by_user"] = repos_by_user
        # Recompute the union, but UNION it with the legacy org-level array
        # too so we don't lose repos that pre-date the per-user scheme.
        new_org_repos = sorted(
            {r for v in repos_by_user.values() for r in v}.union(
                existing_org_repos
            )
        )
        config["linked_repos"] = new_org_repos
    else:
        # Last-resort fallback: no attribution → preserve old behaviour.
        new_org_repos = sorted(set(linked_repos))
        config["linked_repos"] = new_org_repos

    conn.config = config
    await db.commit()

    # Hotfix 7 — auto-install webhooks on any repos that don't already
    # have a Plan2Sprint hook registered. We only attempt newly-added
    # repos to keep the sync responsive; existing entries with
    # ``status: created`` or ``status: exists`` are skipped by
    # ``_install_webhooks_for_repos``. Failures land in
    # ``config.webhooks_by_repo[repo].status`` and don't fail the
    # parent request — the PO can retry via /install-webhook later.
    install_results: dict[str, dict] = {}
    if new_org_repos:
        # Determine which token to use for installation:
        # 1) explicit accessToken from body (dev page passes this on bootstrap)
        # 2) caller's per-developer token from team_members
        # 3) org-level token (decrypted)
        access_token = (body.get("accessToken") or "").strip()
        if not access_token:
            from ...models.team_member import TeamMember
            email = (current_user.get("email") or "").lower()
            if email:
                tm = (
                    await db.execute(
                        sa_select(TeamMember).where(
                            TeamMember.organization_id == org_id,
                            TeamMember.email.ilike(email),
                        )
                    )
                ).scalar_one_or_none()
                if tm and tm.github_access_token:
                    from ...services.encryption import decrypt_token_safe
                    access_token = decrypt_token_safe(tm.github_access_token)
        if not access_token:
            from ...services.encryption import decrypt_token_safe
            access_token = decrypt_token_safe(conn.access_token or "")
        if access_token:
            try:
                install_results = await _install_webhooks_for_repos(
                    db, conn, new_org_repos, access_token
                )
            except Exception:
                # Never let webhook install fail the repo-link save.
                install_results = {}

    return {
        "ok": True,
        "userLogin": user_login or None,
        "webhooksInstalled": install_results,
    }


# ===================================================================
# PER-DEVELOPER GITHUB LINKING
# ===================================================================

@router.post("/link-developer-github")
async def link_developer_github(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Link the current developer's personal GitHub account to their TeamMember record."""
    from ..models.team_member import TeamMember

    access_token = body.get("accessToken", "")
    user_login = body.get("userLogin", "")
    user_name = body.get("userName", "")

    if not access_token or not user_login:
        raise HTTPException(status_code=400, detail="accessToken and userLogin are required")

    org_id = current_user.get("organization_id", "demo-org")
    user_email = current_user.get("email", "")

    # Find the TeamMember record for this user by email
    result = await db.execute(
        select(TeamMember).where(
            TeamMember.organization_id == org_id,
            TeamMember.email.ilike(user_email),
        )
    )
    member = result.scalar_one_or_none()

    if not member:
        # Try matching by display name if email doesn't match
        user_name_from_token = current_user.get("full_name", "")
        if user_name_from_token:
            result2 = await db.execute(
                select(TeamMember).where(
                    TeamMember.organization_id == org_id,
                    TeamMember.display_name.ilike(user_name_from_token),
                    TeamMember.role == "developer",
                )
            )
            member = result2.scalar_one_or_none()

    if not member:
        # Last resort: find any developer team member in the org without a GitHub link
        result3 = await db.execute(
            select(TeamMember).where(
                TeamMember.organization_id == org_id,
                TeamMember.role == "developer",
                TeamMember.github_username.is_(None),
            ).limit(1)
        )
        member = result3.scalar_one_or_none()

    if not member:
        raise HTTPException(
            status_code=404,
            detail="No team member record found for your account. Ask your PO to add you to a project first.",
        )

    # Hotfix 57 (HIGH-5) — encrypt the per-developer GitHub token at
    # rest. Previously stored plaintext: a SQL injection / DB-read
    # compromise leaked every developer's GitHub PAT. ``ensure_encrypted``
    # is idempotent (no-op if already ciphertext) so this is safe to
    # apply uniformly.
    from ...services.encryption import ensure_encrypted
    member.github_username = user_login
    member.github_access_token = ensure_encrypted(access_token)
    await db.commit()

    return {"ok": True, "githubUsername": user_login}


@router.get("/developer-github-status")
async def developer_github_status(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Check if the current developer has linked their GitHub account."""
    from ..models.team_member import TeamMember

    org_id = current_user.get("organization_id", "demo-org")
    user_email = current_user.get("email", "")

    result = await db.execute(
        select(TeamMember).where(
            TeamMember.organization_id == org_id,
            TeamMember.email.ilike(user_email),
        )
    )
    member = result.scalar_one_or_none()

    # Fallback: try matching by full_name
    if not member:
        full_name = current_user.get("full_name", "")
        if full_name:
            result2 = await db.execute(
                select(TeamMember).where(
                    TeamMember.organization_id == org_id,
                    TeamMember.display_name.ilike(full_name),
                    TeamMember.role == "developer",
                )
            )
            member = result2.scalar_one_or_none()

    if member and member.github_username:
        return {"linked": True, "githubUsername": member.github_username}
    return {"linked": False}


@router.delete("/unlink-developer-github")
async def unlink_developer_github(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Disconnect the current developer's GitHub account."""
    from ..models.team_member import TeamMember

    org_id = current_user.get("organization_id", "demo-org")
    user_email = current_user.get("email", "")

    result = await db.execute(
        select(TeamMember).where(
            TeamMember.organization_id == org_id,
            TeamMember.email.ilike(user_email),
        )
    )
    member = result.scalar_one_or_none()

    if member:
        member.github_username = None
        member.github_access_token = None
        await db.commit()

    return {"ok": True}


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
    db: AsyncSession = Depends(get_db),
):
    """POST /repos -- fetch real repos using OAuth access token."""
    org_id = current_user.get("organization_id", "demo-org")
    access_token = await _resolve_github_token(db, org_id, body.get("accessToken"))
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


@router.post("/repos/create")
async def create_repo(
    body: dict,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """POST /repos/create -- create a new GitHub repository."""
    org_id = current_user.get("organization_id", "demo-org")
    access_token = await _resolve_github_token(db, org_id, body.get("accessToken"))
    name = (body.get("name") or "").strip()
    description = (body.get("description") or "").strip()
    is_private = body.get("isPrivate", True)
    auto_init = body.get("autoInit", True)

    if not access_token:
        raise HTTPException(status_code=400, detail="Missing access token")
    if not name:
        raise HTTPException(status_code=400, detail="Repository name is required")

    # Demo mode: return a mock created repo
    if settings.is_demo_mode:
        return {
            "success": True,
            "repo": {
                "id": f"gr-demo-{name}",
                "name": name,
                "fullName": f"demo-user/{name}",
                "defaultBranch": "main",
                "url": f"https://github.com/demo-user/{name}",
                "isPrivate": is_private,
                "language": None,
                "description": description,
                "owner": "demo-user",
            },
        }

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            res = await client.post(
                "https://api.github.com/user/repos",
                json={
                    "name": name,
                    "description": description,
                    "private": is_private,
                    "auto_init": auto_init,
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
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=500,
                detail=f"Failed to create repo: {str(e)}",
            )

    return {
        "success": True,
        "repo": {
            "id": str(data.get("id")),
            "name": data.get("name"),
            "fullName": data.get("full_name"),
            "defaultBranch": data.get("default_branch", "main"),
            "url": data.get("html_url"),
            "isPrivate": data.get("private", False),
            "language": data.get("language"),
            "description": data.get("description"),
            "updatedAt": data.get("updated_at"),
            "owner": (data.get("owner") or {}).get("login"),
        },
    }


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
    db: AsyncSession = Depends(get_db),
):
    """POST /pulls -- fetch real PRs for linked repos using OAuth access token."""
    org_id = current_user.get("organization_id", "demo-org")
    access_token = await _resolve_github_token(db, org_id, body.get("accessToken"))
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
    db: AsyncSession = Depends(get_db),
):
    """POST /commits -- fetch real commits for linked repos."""
    org_id = current_user.get("organization_id", "demo-org")
    access_token = await _resolve_github_token(db, org_id, body.get("accessToken"))
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
    db: AsyncSession = Depends(get_db),
):
    """POST /events -- fetch recent activity events for linked repos."""
    org_id = current_user.get("organization_id", "demo-org")
    access_token = await _resolve_github_token(db, org_id, body.get("accessToken"))
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
async def receive_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """
    POST /webhooks
    Receive GitHub webhook events and auto-track sprint progress.

    This is the CORE of Plan2Sprint's real-time tracking:
      - push events: commits → link to work items → auto-move to IN_PROGRESS
      - pull_request events: PR merge → link to work items → auto-move to DONE
      - check_run events: CI status → update PR records

    After any work-item status change, checks if the sprint is now 100% done
    and auto-completes it if so.
    """
    import logging
    _logger = logging.getLogger(__name__)

    try:
        signature = request.headers.get("x-hub-signature-256") or ""
        event = request.headers.get("x-github-event")
        body_bytes = await request.body()
        body_text = body_bytes.decode("utf-8")

        payload = json.loads(body_text)

        # Determine org_id from the repository's linked connection.
        # Resolution happens BEFORE signature verification because we need
        # the org's webhook_secret (stored on the ToolConnection) to
        # verify against. If we can't resolve an org, the event isn't for
        # us → respond 200 so GitHub doesn't endlessly retry.
        repo_full_name = payload.get("repository", {}).get("full_name", "")
        org_id = await _resolve_org_from_repo(db, repo_full_name)

        if not org_id:
            _logger.warning(
                f"GitHub webhook for unknown repo '{repo_full_name}' — no org match"
            )
            return {"received": True, "event": event, "skipped": True}

        # Hotfix 49 — Feature-flagged strict signature verification.
        #
        # Behaviour matrix:
        #   | secret stored | STRICT_GITHUB_WEBHOOK_VERIFICATION | action       |
        #   | yes           | (any)                              | verify HMAC  |
        #   | no            | "true"                             | reject (401) |
        #   | no            | (default false)                    | warn + accept|
        #
        # Operator workflow:
        #   1. Run the backfill migration so every active connection has
        #      a ``webhook_secret`` matching what GitHub holds.
        #   2. Set ``STRICT_GITHUB_WEBHOOK_VERIFICATION=true`` on the
        #      Container App env vars and restart.
        #   3. From that point any inbound webhook for an unmigrated
        #      legacy connection is rejected with 401.
        #
        # The flag lives in env so it can be toggled without redeploying
        # or even restarting code — just bumping the Container App env
        # triggers a new revision.
        import os as _os
        strict_mode = _os.environ.get(
            "STRICT_GITHUB_WEBHOOK_VERIFICATION", "false"
        ).strip().lower() in ("true", "1", "yes", "on")

        conn = await _get_github_connection(db, org_id)
        cfg = (conn.config or {}) if conn else {}
        webhook_secret = cfg.get("webhook_secret") or ""

        if webhook_secret:
            if not _verify_github_signature(body_bytes, signature, webhook_secret):
                _logger.warning(
                    f"GitHub webhook signature MISMATCH for repo "
                    f"'{repo_full_name}'. Ignoring event."
                )
                raise HTTPException(status_code=401, detail="Invalid signature")
        elif strict_mode:
            _logger.warning(
                f"[SECURITY] GitHub webhook REJECTED (strict mode) for "
                f"repo '{repo_full_name}' — connection has no stored "
                f"secret. Run /backfill-webhook-secrets to migrate."
            )
            raise HTTPException(
                status_code=401,
                detail="Webhook signing secret not configured for this connection",
            )
        else:
            # Hotfix 50 — schedule a background lazy-migration so the
            # NEXT event from this connection comes signed and validates.
            # The current event is accepted unverified (one-shot exposure
            # window) but every subsequent event is locked down.
            _logger.warning(
                f"[SECURITY] GitHub webhook for '{repo_full_name}' has "
                f"NO stored secret on its connection — accepting THIS "
                f"event unverified, scheduling background secret "
                f"migration so future events validate."
            )
            background_tasks.add_task(_lazy_migrate_webhook_secret, org_id)

        from ...services.github_tracker import (
            process_push_event,
            process_pull_request_event,
            process_check_event,
        )

        tracker_result: dict = {}
        items_changed = False

        # ── Process webhook events via GitHub Tracker service ──
        if event == "push":
            tracker_result = await process_push_event(db, org_id, payload)
            items_changed = tracker_result.get("itemsUpdated", 0) > 0

        elif event == "pull_request":
            tracker_result = await process_pull_request_event(db, org_id, payload)
            items_changed = tracker_result.get("itemsUpdated", 0) > 0

        elif event == "pull_request_review":
            # Review events also go through PR handler (action="submitted")
            tracker_result = await process_pull_request_event(db, org_id, payload)
            items_changed = tracker_result.get("itemsUpdated", 0) > 0

        elif event in ("check_run", "check_suite"):
            tracker_result = await process_check_event(db, org_id, payload)

        else:
            _logger.debug(f"Unhandled GitHub event type: {event}")

        # ── If any work items changed status, check for sprint completion ──
        if items_changed:
            try:
                from ...services.sprint_completion import check_and_complete_sprints
                completed = await check_and_complete_sprints(db, org_id)
                if completed:
                    tracker_result["sprintsCompleted"] = [
                        c["iterationName"] for c in completed
                    ]
                    _logger.info(
                        f"[GitHub Webhook] Sprint auto-completed after "
                        f"GitHub activity: {tracker_result['sprintsCompleted']}"
                    )
            except Exception as e:
                _logger.warning(f"Sprint completion check after webhook failed: {e}")

        # ── Broadcast real-time update to connected dashboards ──
        # Always broadcast on push events (even when no work items
        # changed status) so dashboards listening for GitHub signals
        # — like the dev standup — can refresh and pick up the new
        # commits as completed standup items.
        try:
            from ...services.ws_manager import ws_manager
            if items_changed or (event == "push" and tracker_result.get("commitsProcessed", 0) > 0):
                await ws_manager.broadcast(org_id, {
                    "type": "github_activity",
                    "data": {
                        "event": event,
                        "repo": repo_full_name,
                        "itemsUpdated": tracker_result.get("itemsUpdated", 0),
                        "commitsProcessed": tracker_result.get("commitsProcessed", 0),
                        "transitions": tracker_result.get("transitions", []),
                    },
                })
            # Also broadcast work_item_updated for each status transition
            # so hero banner and other panels refresh too
            for transition in (tracker_result.get("transitions") or []):
                await ws_manager.broadcast(org_id, {
                    "type": "work_item_updated",
                    "data": {
                        "workItemId": transition.get("work_item_id"),
                        "oldStatus": transition.get("old_status"),
                        "newStatus": transition.get("new_status"),
                    },
                })
        except Exception as e:
            _logger.warning(f"WebSocket broadcast after webhook failed: {e}")

        # ── Live standup regen — fold new commits into the dev's standup
        #    so the "completed today" section reflects real-time GitHub
        #    activity without manual refresh. Runs ONLY for push events
        #    that landed at least one commit by a recognised team member.
        affected_member_ids = tracker_result.get("affectedMemberIds") or []
        if event == "push" and affected_member_ids:
            try:
                from ...services.standup_generator import generate_member_standup, _since_cutoff
                from ...models.team_member import TeamMember as _TM
                from ...services.ws_manager import ws_manager as _ws
                since = _since_cutoff(None)
                for mid in affected_member_ids:
                    # NB: this module imports ``select as sa_select`` at the
                    # top, NOT bare ``select``. The earlier ``select(_TM)…``
                    # call raised NameError at runtime (verified in the
                    # Container App logs: "standup auto-regen pipeline
                    # failed: name 'select' is not defined"), silently
                    # skipping the live regen + WS broadcast that should
                    # fold a fresh commit into the dev's standup without
                    # them refreshing. Webhook still returned 200 (caught
                    # by the outer try/except), so push ingestion itself
                    # was fine — just no real-time standup update.
                    tm = (await db.execute(
                        sa_select(_TM).where(_TM.id == mid)
                    )).scalar_one_or_none()
                    if not tm:
                        continue
                    try:
                        await generate_member_standup(db, tm, org_id, since)
                    except Exception as e:
                        _logger.warning(
                            f"[GitHub Webhook] live standup regen for "
                            f"{tm.email} failed: {e}"
                        )
                # One broadcast for the whole batch — every listener
                # (PO digest + dev standup view) refreshes once.
                await _ws.broadcast(org_id, {
                    "type": "standup_generated",
                    "data": {
                        "trigger": "github_push",
                        "memberIds": affected_member_ids,
                    },
                })
            except Exception as e:
                _logger.warning(f"[GitHub Webhook] standup auto-regen pipeline failed: {e}")

        await db.commit()

        return {
            "received": True,
            "event": event,
            "action": payload.get("action"),
            "processed": tracker_result,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
    except Exception as e:
        import logging as _log
        _log.getLogger(__name__).exception("Webhook processing failed")
        raise HTTPException(
            status_code=500, detail=f"Webhook processing failed: {str(e)}"
        )


async def _resolve_org_from_repo(
    db: AsyncSession, repo_full_name: str
) -> str | None:
    """
    Find the organization_id that owns a given GitHub repo.
    Checks ToolConnection config for linked_repos containing this repo name.
    """
    if not repo_full_name:
        return None

    from ...models.tool_connection import ToolConnection

    result = await db.execute(
        sa_select(ToolConnection).where(
            ToolConnection.source_tool == "GITHUB",
        )
    )
    connections = result.scalars().all()

    for conn in connections:
        # The model attribute is ``config`` (no trailing underscore). The
        # earlier typo ``conn.config_`` raised AttributeError on the very
        # first iteration of this loop, crashing the entire webhook
        # handler with a 500 — which is why every push event since the
        # last revision shipped silently dropped on the floor (verified
        # via GitHub's deliveries API: 9 consecutive 500s/504s with body
        # "'ToolConnection' object has no attribute 'config_'"). No new
        # commits reached the DB; the standup engine then had nothing
        # within its 7-day window to surface, which masked this typo as
        # an alleged "no recent commits" issue in the PO/dev dashboards.
        config = conn.config or {}
        linked_repos = config.get("linked_repos", [])
        if repo_full_name in linked_repos:
            return conn.organization_id

    # Fallback: check repositories table
    from ...models.repository import Repository
    result = await db.execute(
        sa_select(Repository).where(
            Repository.full_name == repo_full_name,
        ).limit(1)
    )
    repo = result.scalar_one_or_none()
    return repo.organization_id if repo else None
