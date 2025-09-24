from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db
from app.auth_dependencies import get_current_user
from app.users.models import User

router = APIRouter(prefix="/users", tags=["users"])


class UserResponse(BaseModel):
    id: int
    email: str
    first_name: str | None = None
    last_name: str | None = None
    profile_picture_url: str | None = None
    root_folder_id: int | None = None
    resource_count: int = 0
    created_at: str | None = None
    updated_at: str | None = None

    class Config:
        from_attributes = True


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    """
    Get the current authenticated user's information.

    Returns:
        UserResponse: Complete user profile information including:
        - User ID
        - Email address
        - First and last name (if available)
        - Profile picture URL (if available)
        - Account creation and update timestamps

    Requires:
        JWT authentication via Authorization header
    """
    return UserResponse(
        id=current_user.id,
        email=current_user.email,
        first_name=current_user.first_name,
        last_name=current_user.last_name,
        profile_picture_url=current_user.profile_picture_url,
        root_folder_id=current_user.root_folder_id,
        resource_count=current_user.resource_count or 0,
        created_at=current_user.created_at.isoformat() if current_user.created_at else None,
        updated_at=current_user.updated_at.isoformat() if current_user.updated_at else None
    )


@router.delete("/delete-account")
async def delete_account(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Delete the current user's account and all associated data.
    This action is irreversible and will permanently remove:
    - User profile data
    - All learning resources
    - All folders and subfolders
    - All flash cards
    - All quiz questions

    Returns:
        dict: Success message confirming account deletion

    Raises:
        HTTPException: 500 if deletion fails
    """
    try:
        # Import here to avoid circular imports
        from app.learning.models import (
            ResourceFolder,
            LearningResource,
            FlashCard,
            MultipleChoiceQuestion
        )

        user_id = current_user.id

        # Delete in order of dependencies (child tables first)
        # 1. Delete flash cards
        flash_cards_deleted = db.query(FlashCard).filter(
            FlashCard.user_id == user_id
        ).delete()

        # 2. Delete multiple choice questions
        questions_deleted = db.query(MultipleChoiceQuestion).filter(
            MultipleChoiceQuestion.user_id == user_id
        ).delete()

        # 3. Delete learning resources
        resources_deleted = db.query(LearningResource).filter(
            LearningResource.user_id == user_id
        ).delete()

        # 4. Set root_folder_id to null to avoid foreign key constraint violation
        # The users table has a foreign key reference to resource_folders.id via root_folder_id
        # We must null this field before deleting the folders to prevent constraint violations
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            user.root_folder_id = None
            db.flush()  # Apply the update before deleting folders

        # 5. Delete resource folders (including nested folders)
        folders_deleted = db.query(ResourceFolder).filter(
            ResourceFolder.user_id == user_id
        ).delete()

        # 6. Finally delete the user
        user_deleted = db.query(User).filter(User.id == user_id).delete()

        # Commit all deletions
        db.commit()

        return {
            "message": "Account successfully deleted",
            "deleted_counts": {
                "flash_cards": flash_cards_deleted,
                "quiz_questions": questions_deleted,
                "learning_resources": resources_deleted,
                "folders": folders_deleted,
                "user": user_deleted
            }
        }

    except Exception as e:
        print(e)
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete account: {str(e)}"
        )