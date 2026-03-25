from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from ..config import settings

security = HTTPBearer(auto_error=False)

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
        # Log the actual error for debugging
        import logging
        logging.getLogger(__name__).error(f"JWT decode failed: {e}, token_start={token[:20]}...")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )
