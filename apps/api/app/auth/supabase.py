from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError, jwk
from sqlalchemy import select
from ..config import settings
import logging
import uuid

logger = logging.getLogger(__name__)
security = HTTPBearer(auto_error=False)

# Supabase JWKS public key for ES256 verification
# Fetched from https://obmbpfoormxbbizudrrp.supabase.co/auth/v1/.well-known/jwks.json
_SUPABASE_ES256_JWK = {
    "alg": "ES256",
    "crv": "P-256",
    "ext": True,
    "key_ops": ["verify"],
    "kid": "102fcb70-7594-4615-beac-cfac83f47fe2",
    "kty": "EC",
    "use": "sig",
    "x": "bbpH29xNI809c_lWskKCIYOHAPu7dvl2qY5QyonVrLA",
    "y": "2Mo3hnvkFeYQoToD7TsQM-KtfOZWpriaHyPUBVXUoU4",
}

async def _resolve_user_org(request: Request, payload: dict) -> dict:
    """Look up the user's organization from the DB. If not found, either
    auto-create one OR — if a pending invitation matches the user's
    email — consume the invitation and place the user into the inviter's
    org with the invited role (Hotfix 65A)."""
    from datetime import datetime, timezone
    from ..database import AsyncSessionLocal
    from ..models.user import User
    from ..models.organization import Organization
    from ..models.invitation import Invitation

    supabase_uid = payload.get("sub", "")
    email = payload.get("email", "")
    # user_metadata may come from JWT (signup) or be empty (OAuth login)
    user_meta = payload.get("user_metadata", {})
    # Also check raw_user_meta_data from Supabase (different JWT versions)
    if not user_meta:
        user_meta = payload.get("raw_user_meta_data", {})
    full_name = (
        user_meta.get("full_name")
        or user_meta.get("name")
        or (email.split("@")[0] if email else "User")
    )
    org_name_from_signup = user_meta.get("organization_name", "")
    # Hotfix 51 (CRIT-6) — refuse to honour ``role`` from signup metadata.
    # The Supabase signup form is client-controllable, so anyone could
    # set ``role=product_owner`` in their own metadata and self-elect.
    # Combined with CRIT-2 (sprint mutations have no role check) this
    # was unbounded escalation.
    #
    # We now ALWAYS default new orgs' first user to ``product_owner``
    # (because the user creating an org IS its PO by definition), but
    # ignore any client-supplied role for invited / additional users —
    # those default to ``developer`` and must be promoted by an existing
    # admin via the explicit role-management endpoint.
    role_from_signup = "product_owner"  # only used for brand-new org creation

    try:
        async with AsyncSessionLocal() as db:
            # 1. Look up existing user by supabase_user_id
            result = await db.execute(
                select(User).where(User.supabase_user_id == supabase_uid)
            )
            user = result.scalar_one_or_none()

            if user:
                # User exists — use their stored org
                payload["id"] = user.id
                payload["organization_id"] = user.organization_id
                payload["role"] = user.role
                payload["full_name"] = user.full_name
                return payload

            # 2. Also check by email (for users created before supabase_user_id was set)
            if email:
                result = await db.execute(
                    select(User).where(User.email == email)
                )
                user = result.scalar_one_or_none()
                if user:
                    # Link supabase_user_id and return
                    user.supabase_user_id = supabase_uid
                    await db.commit()
                    payload["id"] = user.id
                    payload["organization_id"] = user.organization_id
                    payload["role"] = user.role
                    payload["full_name"] = user.full_name
                    return payload

            # 3a. Hotfix 65A — before auto-creating an org, check if
            # this email has a PENDING invitation waiting. If so we
            # consume it: drop the new user into the inviter's org with
            # the invited role, mark the invitation accepted, and skip
            # auto-org creation. Without this branch, anyone who signed
            # up after being invited would end up as PO of a brand-new
            # auto-org (e.g. "Raj's Organization") and forever blocked
            # from accepting the invitation by Hotfix 61's cross-org
            # collision check.
            if email:
                inv_now = datetime.now(timezone.utc)
                inv_q = await db.execute(
                    select(Invitation)
                    .where(
                        Invitation.email == email.lower(),
                        Invitation.status == "pending",
                    )
                    .order_by(Invitation.created_at.desc())
                )
                pending_invs = inv_q.scalars().all()
                # Pick the first non-expired one. Stale rows are skipped
                # rather than consumed so the user falls through to
                # auto-org creation if every invite is expired.
                live_inv = None
                for cand in pending_invs:
                    if cand.expires_at and cand.expires_at < inv_now:
                        continue
                    live_inv = cand
                    break

                if live_inv is not None:
                    new_user_id = uuid.uuid4().hex[:25]
                    new_user = User(
                        id=new_user_id,
                        email=email,
                        full_name=full_name,
                        # Stored upper-case to match the existing
                        # accept_invitation path; downstream consumers
                        # lower-case for comparisons.
                        role=(live_inv.role or "developer").upper(),
                        supabase_user_id=supabase_uid,
                        organization_id=live_inv.organization_id,
                        onboarding_completed=False,
                    )
                    db.add(new_user)
                    live_inv.status = "accepted"
                    live_inv.accepted_at = inv_now
                    await db.commit()

                    logger.info(
                        f"[invite-autoaccept] Consumed pending invitation "
                        f"{live_inv.id} for {email!r} -> org "
                        f"{live_inv.organization_id} role={live_inv.role}"
                    )

                    # Hotfix 66B — sync the invited role into Supabase
                    # ``user_metadata`` so the FRONTEND role-router
                    # (apps/web middleware + auth context, both reading
                    # from ``user.user_metadata.role``) lands the user
                    # on their correct dashboard. Without this, a
                    # signup-time metadata of ``product_owner`` survives
                    # the invitation auto-consume and the new
                    # stakeholder/developer ends up dumped on /po
                    # showing the org's data — exactly the failure mode
                    # reported on 2026-05-05. Best-effort: failures are
                    # logged, never block the auth path. NOTE: the
                    # caller's CURRENT JWT still has stale metadata —
                    # they need to log out/in for the new role to take
                    # effect on the client side.
                    try:
                        from ..config import settings as _s
                        service_key = (_s.supabase_service_role_key or "").strip()
                        sup_url = (_s.supabase_url or "").strip().rstrip("/")
                        if supabase_uid and service_key and sup_url:
                            import httpx as _httpx
                            async with _httpx.AsyncClient(timeout=8.0) as _client:
                                _r = await _client.put(
                                    f"{sup_url}/auth/v1/admin/users/{supabase_uid}",
                                    headers={
                                        "apikey": service_key,
                                        "Authorization": f"Bearer {service_key}",
                                        "Content-Type": "application/json",
                                    },
                                    json={
                                        "user_metadata": {
                                            "role": (live_inv.role or "developer").lower(),
                                            "full_name": full_name,
                                        }
                                    },
                                )
                                if _r.status_code >= 300:
                                    logger.warning(
                                        f"[invite-autoaccept] Supabase metadata "
                                        f"sync failed ({_r.status_code}): "
                                        f"{_r.text[:200]}"
                                    )
                    except Exception as _e:
                        logger.warning(
                            f"[invite-autoaccept] Supabase metadata sync error: {_e!r}"
                        )

                    payload["id"] = new_user_id
                    payload["organization_id"] = live_inv.organization_id
                    payload["role"] = (live_inv.role or "developer").lower()
                    payload["full_name"] = full_name
                    return payload

            # 3b. No pending invitation — fall through to find-or-
            # create-org logic.
            #
            # Hotfix 85 — was previously a forced create-new-org with a
            # random slug suffix, which produced duplicate orgs whenever
            # two POs typed the same organisation name. Now we
            # canonical-match first: if any existing org has the same
            # ``LOWER(TRIM(name))``, the new user is attached to that
            # org as a (second) PO; only when no match is found does a
            # brand-new org get created.
            #
            # Path A (OAuth, no org name in metadata) still creates a
            # placeholder named ``"<full_name>'s Organization"`` —
            # that placeholder is canonical-matchable too, so a user
            # who later renames it via Settings → Team to "C2A" will
            # land in the existing C2A org via the rename endpoint.
            from ..services.org_lookup import find_or_create_org

            org_input = org_name_from_signup.strip() if org_name_from_signup else ""
            if org_input:
                # Path B — explicit org name supplied at signup.
                org_obj, was_created = await find_or_create_org(db, org_input)
            else:
                # Path A — OAuth, no org name yet. Create a unique
                # placeholder so the user has a valid org_id; they'll
                # rename it from Settings later.
                placeholder_canonical = f"oauth-{(supabase_uid or uuid.uuid4().hex)[:24]}"
                placeholder_display = f"{full_name}'s Organization"
                org_obj, was_created = await find_or_create_org(
                    db,
                    placeholder_display,
                    fallback_canonical=placeholder_canonical,
                )

            new_user_id = uuid.uuid4().hex[:25]
            # Existing users already in this org? If so, log it — useful
            # forensic signal that someone else just joined the tenant.
            if not was_created:
                _existing_count_q = await db.execute(
                    select(User).where(User.organization_id == org_obj.id)
                )
                _existing_users = _existing_count_q.scalars().all()
                logger.info(
                    f"[org-canonical-match] '{email}' joining existing org "
                    f"'{org_obj.name}' ({org_obj.id}) — already has "
                    f"{len(_existing_users)} user(s)"
                )

            new_user = User(
                id=new_user_id,
                email=email,
                full_name=full_name,
                role=role_from_signup,
                supabase_user_id=supabase_uid,
                organization_id=org_obj.id,
                onboarding_completed=False,
            )
            db.add(new_user)
            await db.commit()

            if was_created:
                logger.info(
                    f"Auto-created org '{org_obj.name}' ({org_obj.id}) "
                    f"and user '{email}' ({new_user_id})"
                )
            else:
                logger.info(
                    f"Attached '{email}' ({new_user_id}) to existing org "
                    f"'{org_obj.name}' ({org_obj.id}) via canonical name match"
                )

            new_org_id = org_obj.id  # keep the symbol used downstream

            payload["id"] = new_user_id
            payload["organization_id"] = new_org_id
            payload["role"] = role_from_signup
            payload["full_name"] = full_name
            return payload

    except Exception as e:
        logger.error(f"Failed to resolve user org: {e}")
        # If DB is unreachable and debug mode, allow demo fallback
        if settings.debug:
            payload["organization_id"] = "demo-org"
            return payload
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to resolve user organization",
        )


DEMO_USER = {
    "sub": "demo-user-1",
    "id": "demo-user-1",
    "email": "demo@plan2sprint.app",
    "full_name": "Demo User",
    "role": "product_owner",
    "organization_id": "demo-org",
    "organization_name": "Demo Organization",
}

async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict:
    # Demo mode bypass — identical to TypeScript isDemoMode
    if settings.is_demo_mode:
        return DEMO_USER

    # Try to get token from: 1) Bearer header, 2) query param, 3) cookie
    token = None
    if credentials:
        token = credentials.credentials
    elif request.query_params.get("token"):
        token = request.query_params.get("token")
    elif request.cookies.get("sb-access-token"):
        token = request.cookies.get("sb-access-token")

    if not token:
        # SECURITY: Only explicit demo_mode bypasses auth, not debug flag
        if settings.is_demo_mode:
            return DEMO_USER
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        # Check token algorithm to use the right key
        try:
            header = jwt.get_unverified_header(token)
            token_alg = header.get("alg", "unknown")
        except Exception:
            token_alg = "unknown"

        if token_alg == "ES256":
            # Supabase new signing key (ECC P-256)
            es256_key = jwk.construct(_SUPABASE_ES256_JWK, algorithm="ES256")
            payload = jwt.decode(
                token,
                es256_key,
                algorithms=["ES256"],
                audience="authenticated",
                options={"verify_signature": True},
            )
        else:
            # Legacy HS256 signing key
            payload = jwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=["HS256"],
                audience="authenticated",
                options={"verify_signature": True},
            )

        # Enrich with organization_id from our users table
        if "organization_id" not in payload or not payload["organization_id"]:
            payload = await _resolve_user_org(request, payload)
        return payload
    except JWTError as e:
        logger.error(f"JWT decode failed: {e}, alg={token_alg}, token_start={token[:30]}...")

        # SECURITY: Never fall back to demo user on JWT failure.
        # Only settings.is_demo_mode (explicit opt-in) bypasses auth.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ---------------------------------------------------------------------------
# Hotfix 51 (CRIT-2) — Role-gating helpers
#
# Until now nearly every mutating endpoint in sprints.py / dashboard.py /
# integrations/* checked ``organization_id`` but never ``role``, so a
# stakeholder could approve sprint plans, exclude colleagues, trigger
# Jira/ADO writebacks, and burn AI quota. These helpers centralise the
# allow-list so mutations consistently require PO/admin/owner.
# ---------------------------------------------------------------------------

PO_ROLES = frozenset({"product_owner", "admin", "owner"})
WRITE_ROLES = frozenset({"product_owner", "admin", "owner", "engineering_manager", "developer"})


def require_po(current_user: dict) -> None:
    """Raise 403 unless the caller is a product_owner / admin / owner.

    Every endpoint that mutates sprint plans, team membership, AI
    workloads, or write-backs to external trackers must call this.
    """
    role = (current_user.get("role") or "").lower()
    if role not in PO_ROLES:
        raise HTTPException(
            status_code=403,
            detail=(
                "This action requires product owner / admin role. "
                f"Your role: {role or '(none)'}"
            ),
        )


def require_write_role(current_user: dict) -> None:
    """Raise 403 if the caller is a stakeholder (read-only role).

    Use this on endpoints where developers and engineering managers can
    legitimately mutate (e.g. work-item status drags, standup notes)
    but stakeholders should never be able to.
    """
    role = (current_user.get("role") or "").lower()
    if role not in WRITE_ROLES:
        raise HTTPException(
            status_code=403,
            detail=(
                "This action requires a developer / engineering manager "
                "/ product owner role. Stakeholders are read-only. "
                f"Your role: {role or '(none)'}"
            ),
        )
