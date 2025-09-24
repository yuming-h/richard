import jwt
import json
import requests
from typing import Optional
from sqlalchemy.orm import Session
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from fastapi import Depends, HTTPException
from app.database import get_db
from app.users.models import User
from app.learning.models import ResourceFolder
from app.settings import settings


class AuthService:
    def __init__(self, db: Session = Depends(get_db)):
        self.db = db

    async def verify_google_token(self, token: str) -> dict:
        """Verify Google ID token and return user info"""
        try:
            # Verify the token
            idinfo = id_token.verify_oauth2_token(token, google_requests.Request())

            # Check if token is from Google
            if idinfo["iss"] not in [
                "accounts.google.com",
                "https://accounts.google.com",
            ]:
                raise HTTPException(status_code=400, detail="Invalid token issuer")

            return idinfo
        except Exception as e:
            raise HTTPException(
                status_code=400, detail=f"Invalid Google token: {str(e)}"
            )

    async def verify_apple_token(self, identity_token: str) -> dict:
        """Verify Apple ID token and return user info"""
        try:
            # Decode JWT header to get key ID
            header = jwt.get_unverified_header(identity_token)
            key_id = header.get("kid")

            if not key_id:
                raise HTTPException(status_code=400, detail="No key ID in token")

            # Get Apple's public keys
            response = requests.get("https://appleid.apple.com/auth/keys")
            if response.status_code != 200:
                raise HTTPException(
                    status_code=400, detail="Could not fetch Apple keys"
                )

            keys = response.json()["keys"]

            # Find the correct key
            public_key = None
            for key in keys:
                if key["kid"] == key_id:
                    public_key = jwt.algorithms.RSAAlgorithm.from_jwk(key)
                    break

            if not public_key:
                raise HTTPException(
                    status_code=400, detail="Could not find matching key"
                )

            # Verify and decode the token
            payload = jwt.decode(
                identity_token,
                public_key,
                algorithms=["RS256"],
                audience="com.yuming.richard",  # Your app's bundle ID
                issuer="https://appleid.apple.com",
            )

            return payload
        except jwt.InvalidTokenError as e:
            raise HTTPException(
                status_code=400, detail=f"Invalid Apple token: {str(e)}"
            )
        except Exception as e:
            raise HTTPException(
                status_code=400, detail=f"Apple token verification failed: {str(e)}"
            )

    def get_or_create_user(self, google_info: dict) -> User:
        """Get existing user or create new one from Google info"""
        google_sub = google_info.get("sub")
        email = google_info.get("email")

        # Try to find existing user by Google sub ID
        user = self.db.query(User).filter(User.google_sub == google_sub).first()

        if not user:
            # Extract name from Google info
            full_name = google_info.get("name", "")
            given_name = google_info.get("given_name", "")
            family_name = google_info.get("family_name", "")

            # Use given_name and family_name if available, otherwise parse full_name
            first_name = given_name or (full_name.split(" ")[0] if full_name else "")
            last_name = family_name or (
                " ".join(full_name.split(" ")[1:]) if " " in full_name else ""
            )

            # Get profile picture URL
            profile_picture_url = google_info.get("picture", "")

            # Create new user with root folder
            user = self.create_new_user_with_folder(
                email=email,
                first_name=first_name,
                last_name=last_name,
                google_sub=google_sub,
                profile_picture_url=profile_picture_url
            )
        else:
            # Update existing user with name info if not already set
            full_name = google_info.get("name", "")
            given_name = google_info.get("given_name", "")
            family_name = google_info.get("family_name", "")

            # Only update if fields are currently empty
            if not user.first_name and not user.last_name:
                first_name = given_name or (full_name.split(" ")[0] if full_name else "")
                last_name = family_name or (
                    " ".join(full_name.split(" ")[1:]) if " " in full_name else ""
                )

                if first_name or last_name:
                    user.first_name = first_name
                    user.last_name = last_name

            # Update profile picture if not already set
            if not user.profile_picture_url:
                profile_picture_url = google_info.get("picture", "")
                if profile_picture_url:
                    user.profile_picture_url = profile_picture_url

            # Commit any updates
            self.db.commit()
            self.db.refresh(user)

        return user

    def get_or_create_apple_user(
        self, apple_info: dict, first_name: str = "", last_name: str = ""
    ) -> User:
        """Get existing user or create new one from Apple info"""
        apple_sub = apple_info.get("sub")
        email = apple_info.get("email")

        # Try to find existing user by Apple sub ID
        user = self.db.query(User).filter(User.apple_sub == apple_sub).first()

        if not user:
            # Create new user with root folder
            user = self.create_new_user_with_folder(
                email=email,
                first_name=first_name,
                last_name=last_name,
                apple_sub=apple_sub
            )
        else:
            # Update existing user with name info if not already set and if provided
            if not user.first_name and not user.last_name and (first_name or last_name):
                user.first_name = first_name
                user.last_name = last_name
                self.db.commit()
                self.db.refresh(user)

        return user

    def create_new_user_with_folder(
        self,
        email: str,
        first_name: str,
        last_name: str,
        google_sub: str = None,
        apple_sub: str = None,
        profile_picture_url: str = None
    ) -> User:
        """Create a new user and their root folder"""
        user = User(
            email=email,
            first_name=first_name,
            last_name=last_name,
            google_sub=google_sub,
            apple_sub=apple_sub,
            profile_picture_url=profile_picture_url,
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        
        # Create root folder for new user
        self.create_root_folder(user)
        
        return user

    def create_root_folder(self, user: User) -> ResourceFolder:
        """Create a root folder for a new user"""
        root_folder = ResourceFolder(
            user_id=user.id,
            name=f"{user.first_name}'s files",
            parent_folder_id=None
        )
        self.db.add(root_folder)
        self.db.commit()
        self.db.refresh(root_folder)
        
        # Update user with root folder reference
        user.root_folder_id = root_folder.id
        self.db.commit()
        
        return root_folder

    def generate_jwt_token(self, user: User) -> str:
        """Generate non-expiring JWT token for user"""
        payload = {
            "user_id": user.id,
            "email": user.email,
            "google_sub": user.google_sub,
            "apple_sub": user.apple_sub,
            # Note: No 'exp' field means token doesn't expire
        }

        token = jwt.encode(payload, settings.jwt_secret_key, algorithm="HS256")
        return token

    def verify_jwt_token(self, token: str) -> dict:
        """Verify JWT token and return payload"""
        try:
            payload = jwt.decode(token, settings.jwt_secret_key, algorithms=["HS256"])
            return payload
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token has expired")
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=401, detail="Invalid token")

    def get_user_from_token(self, token: str) -> User:
        """Get user from JWT token"""
        payload = self.verify_jwt_token(token)
        user_id = payload.get("user_id")

        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token payload")

        user = self.db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=401, detail="User not found")

        return user

    def create_user(self, user: User):
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user
