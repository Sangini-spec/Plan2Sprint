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
    """Look up the user's organization from the DB. If not found, auto-create one."""
    from ..database import AsyncSessionLocal
    from ..models.user import User
    from ..models.organization import Organization

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
    role_from_signup = user_meta.get("role", "product_owner")

    try:
        async with AsyncSessionLocal() as db:
            # 1. Look up existing user by supabase_user_id
            result = await db.execute(
                select(User).where(User.supabase_user_id == supabase_uid)
            )
            user = result.scalar_one_or_none()

            if user:
                # User exists — use their stored org
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
                    payload["organization_id"] = user.organization_id
                    payload["role"] = user.role
                    payload["full_name"] = user.full_name
                    return payload

            # 3. New user — create org + user
            new_org_id = uuid.uuid4().hex[:25]
            new_user_id = uuid.uuid4().hex[:25]
            org_display_name = org_name_from_signup or f"{full_name}'s Organization"

            # Generate slug from org name
            import re
            slug = re.sub(r'[^a-z0-9]+', '-', org_display_name.lower()).strip('-')[:50]
            slug = f"{slug}-{new_org_id[:8]}"  # Ensure uniqueness

            new_org = Organization(
                id=new_org_id,
                name=org_display_name,
                slug=slug,
            )
            db.add(new_org)

            new_user = User(
                id=new_user_id,
                email=email,
                full_name=full_name,
                role=role_from_signup,
                supabase_user_id=supabase_uid,
                organization_id=new_org_id,
                onboarding_completed=False,
            )
            db.add(new_user)
            await db.commit()

            logger.info(f"Auto-created org '{org_display_name}' ({new_org_id}) and user '{email}' ({new_user_id})")

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
