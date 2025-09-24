from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.database import get_db
from app.users.models import User
from app.users.services.auth_service import AuthService

# HTTP Bearer token scheme
security = HTTPBearer()

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    """
    FastAPI dependency to get the current authenticated user from JWT token.
    
    Usage:
    @app.get("/protected")
    async def protected_route(current_user: User = Depends(get_current_user)):
        return {"user_id": current_user.id, "email": current_user.email}
    """
    auth_service = AuthService(db)
    
    try:
        # Extract token from credentials
        token = credentials.credentials
        
        # Get user from token
        user = auth_service.get_user_from_token(token)
        
        return user
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

def require_auth(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    """
    Alias for get_current_user - use whichever name you prefer
    """
    return get_current_user(credentials, db)