from fastapi import Depends, HTTPException, status
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
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict:
    # Demo mode bypass — identical to TypeScript isDemoMode
    if settings.is_demo_mode:
        return DEMO_USER

    if not credentials:
        # In debug/development mode, fall back to demo user for unauthenticated requests.
        # This allows testing the API without Supabase auth tokens.
        # In production (DEBUG=false), this will properly return 401.
        if settings.debug:
            return DEMO_USER
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    try:
        payload = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
        )
        # Enrich with organization_id from our users table if not in JWT
        if "organization_id" not in payload:
            payload["organization_id"] = "demo-org"
        return payload
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )
