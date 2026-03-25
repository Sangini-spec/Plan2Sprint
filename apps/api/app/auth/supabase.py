from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError, jwk
from ..config import settings
import logging

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
        if settings.debug:
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

        # Enrich with organization_id from our users table if not in JWT
        if "organization_id" not in payload:
            payload["organization_id"] = "demo-org"
        return payload
    except JWTError as e:
        logger.error(f"JWT decode failed: {e}, alg={token_alg}, token_start={token[:30]}...")

        # In debug mode, fall back to demo user even if token is invalid
        if settings.debug:
            logger.warning("Debug mode: falling back to demo user despite invalid token")
            return DEMO_USER

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )
