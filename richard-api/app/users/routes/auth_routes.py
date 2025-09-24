from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db
from app.users.services.auth_service import AuthService
from app.auth_dependencies import get_current_user
from app.users.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


class GoogleSignInRequest(BaseModel):
    id_token: str


class AppleSignInRequest(BaseModel):
    identity_token: str
    first_name: str = ""
    last_name: str = ""


class AuthResponse(BaseModel):
    jwt_token: str
    user_id: int
    email: str
    first_name: str | None = None
    last_name: str | None = None
    profile_picture_url: str | None = None


@router.post("/google-signin", response_model=AuthResponse)
async def google_signin(
    request: GoogleSignInRequest, auth_service: AuthService = Depends(AuthService)
):
    """
    Authenticate user with Google ID token and return JWT
    """

    # Verify Google token and get user info
    google_info = await auth_service.verify_google_token(request.id_token)

    # Get or create user
    user = auth_service.get_or_create_user(google_info)

    # Generate JWT token
    jwt_token = auth_service.generate_jwt_token(user)

    return AuthResponse(
        jwt_token=jwt_token,
        user_id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        profile_picture_url=user.profile_picture_url
    )


@router.post("/apple-signin", response_model=AuthResponse)
async def apple_signin(
    request: AppleSignInRequest, auth_service: AuthService = Depends(AuthService)
):
    """
    Authenticate user with Apple ID token and return JWT
    """

    # Verify Apple token and get user info
    apple_info = await auth_service.verify_apple_token(request.identity_token)

    # Get or create user
    user = auth_service.get_or_create_apple_user(
        apple_info, request.first_name, request.last_name
    )

    # Generate JWT token
    jwt_token = auth_service.generate_jwt_token(user)

    return AuthResponse(
        jwt_token=jwt_token,
        user_id=user.id,
        email=user.email,
        first_name=user.first_name,
        last_name=user.last_name,
        profile_picture_url=user.profile_picture_url
    )
