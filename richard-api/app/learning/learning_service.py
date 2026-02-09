from app.learning.models import LearningResource, LearningResourceFileType, ResourceFolder, FlashCard, MultipleChoiceQuestion, LearningResourceImage
from app.users.models import User
from sqlalchemy.orm import Session, undefer
from fastapi import Depends, HTTPException
from app.database import get_db
from app.settings import settings
from fastapi import UploadFile
import zipfile
import tempfile
import os
import boto3
import uuid
from typing import List, Optional, Literal, Dict, Any
from openai import OpenAI
import logging

logger = logging.getLogger(__name__)


class LearningService:
    def __init__(self, db: Session = Depends(get_db)):
        self.db = db

    async def decompress_and_upload_file(self, file: UploadFile) -> str:
        """
        Decompress a zip file, extract the single file, and upload to S3
        Returns the S3 URL of the uploaded file
        """
        try:
            # Initialize S3 client
            s3_client = boto3.client('s3')
            bucket_name = settings.files_s3_bucket_name
            
            # Generate unique file name
            file_id = str(uuid.uuid4())
            
            # Create temporary directory for extraction
            with tempfile.TemporaryDirectory() as temp_dir:
                # Save uploaded file temporarily
                temp_zip_path = os.path.join(temp_dir, file.filename)
                with open(temp_zip_path, 'wb') as temp_file:
                    content = await file.read()
                    temp_file.write(content)
                
                # Extract zip file
                with zipfile.ZipFile(temp_zip_path, 'r') as zip_ref:
                    zip_ref.extractall(temp_dir)
                
                # Find the first (and only) extracted file
                extracted_file = None
                for root, dirs, files in os.walk(temp_dir):
                    for filename in files:
                        # Skip the original zip file
                        if filename == file.filename:
                            continue
                        extracted_file = os.path.join(root, filename)
                        break
                    if extracted_file:
                        break
                
                if not extracted_file:
                    raise HTTPException(status_code=400, detail="No files found in zip archive")
                
                # Get original filename from extracted file
                original_filename = os.path.basename(extracted_file)
                file_extension = os.path.splitext(original_filename)[1]
                
                # Create S3 key with unique ID
                s3_key = f"learning-resources/{file_id}{file_extension}"
                
                # Upload to S3
                s3_client.upload_file(
                    extracted_file,
                    bucket_name,
                    s3_key
                )

                # Get the region from the S3 client
                region = s3_client.meta.region_name or 'us-east-2'

                # Return the HTTPS URL instead of S3 URI
                return f"https://{bucket_name}.s3.{region}.amazonaws.com/{s3_key}"
                
        except zipfile.BadZipFile:
            raise HTTPException(status_code=400, detail="Invalid zip file format")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"File processing error: {str(e)}")

    async def upload_images_to_s3(self, files: List[UploadFile]) -> List[str]:
        """
        Upload multiple image files to S3.
        Returns a list of S3 URLs for the uploaded images.
        """
        try:
            # Initialize S3 client
            s3_client = boto3.client('s3')
            bucket_name = settings.files_s3_bucket_name

            uploaded_urls = []

            for file in files:
                # Validate file type
                if not file.content_type or not file.content_type.startswith('image/'):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid file type for {file.filename}. Only image files are allowed."
                    )

                # Generate unique file name
                file_id = str(uuid.uuid4())
                file_extension = os.path.splitext(file.filename)[1]

                if not file_extension:
                    # Try to get extension from content type
                    content_type_map = {
                        'image/jpeg': '.jpg',
                        'image/png': '.png',
                        'image/gif': '.gif',
                        'image/webp': '.webp'
                    }
                    file_extension = content_type_map.get(file.content_type, '.jpg')

                # Create S3 key with unique ID
                s3_key = f"images/{file_id}{file_extension}"

                # Read file content
                file_content = await file.read()

                # Upload to S3
                s3_client.put_object(
                    Bucket=bucket_name,
                    Key=s3_key,
                    Body=file_content,
                    ContentType=file.content_type
                )

                # Get the region from the S3 client
                region = s3_client.meta.region_name or 'us-east-2'

                # Create the HTTPS URL
                image_url = f"https://{bucket_name}.s3.{region}.amazonaws.com/{s3_key}"
                uploaded_urls.append(image_url)

                # Reset file pointer for potential re-use
                await file.seek(0)

            return uploaded_urls

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Image upload error: {str(e)}")

    def list_user_folders(self, user_id: int) -> List[ResourceFolder]:
        """
        List all folders that belong to a specific user.

        Args:
            user_id: ID of the user

        Returns:
            List of ResourceFolder objects ordered by created_at desc (most recent first)
        """
        folders = self.db.query(ResourceFolder).filter(
            ResourceFolder.user_id == user_id
        ).order_by(ResourceFolder.created_at.desc()).all()

        return folders

    def get_folder_contents(
        self,
        folder_id: int,
        user_id: int,
        item_type: Optional[Literal["folder", "resource"]] = None
    ) -> Dict[str, Any]:
        """
        Get contents of a specific folder with optional filtering by item type.

        Args:
            folder_id: ID of the folder to get contents from
            user_id: ID of the current user (for security)
            item_type: Optional filter - 'folder', 'resource', or None for all

        Returns:
            Dictionary with folder_id and list of items

        Raises:
            HTTPException: If folder not found or doesn't belong to user
        """
        folder = self.db.query(ResourceFolder).filter(
            ResourceFolder.id == folder_id,
            ResourceFolder.user_id == user_id
        ).first()
        
        if not folder:
            raise HTTPException(status_code=404, detail="Folder not found")
            
        folder_name = folder.name
        folder_created_at = folder.created_at
        
        items = []
        
        # Get subfolders if requested (sorted by created_at desc)
        if item_type is None or item_type == "folder":
            subfolders = self.db.query(ResourceFolder).filter(
                ResourceFolder.parent_folder_id == folder_id,
                ResourceFolder.user_id == user_id
            ).order_by(ResourceFolder.created_at.desc()).all()
            
            for subfolder in subfolders:
                items.append({
                    "id": subfolder.id,
                    "name": subfolder.name,
                    "parent_folder_id": subfolder.parent_folder_id,
                    "created_at": subfolder.created_at,
                    "updated_at": subfolder.updated_at,
                    "type": "folder"
                })
        
        # Get resources if requested (sorted by created_at desc)
        if item_type is None or item_type == "resource":
            resources = self.db.query(LearningResource).filter(
                LearningResource.folder_id == folder_id,
                LearningResource.user_id == user_id
            ).order_by(LearningResource.created_at.desc()).all()
            
            for resource in resources:
                items.append({
                    "id": resource.id,
                    "title": resource.title,
                    "emoji": resource.emoji,
                    "resource_type": resource.resource_type,
                    "folder_id": resource.folder_id,
                    "file_url": resource.file_url,
                    "status": resource.status,
                    "created_at": resource.created_at,
                    "updated_at": resource.updated_at,
                    "type": "resource"
                })
        
        # Sort items: folders first, then resources (both already sorted reverse chronologically)
        # items.sort(key=lambda x: (x["type"] != "folder", x["created_at"]), reverse=False)
        
        return {
            "folder_id": folder_id,
            "folder_name": folder_name,
            "created_at": folder_created_at,
            "items": items
        }

    async def create_resource(
        self,
        folder_id: int,
        user_id: int,
        resource_type: LearningResourceFileType,
        transcript: str,
        file_url: str = None,
        file: UploadFile = None,
        files: List[UploadFile] = None,
    ):
        # Handle single file upload for non-image resources
        if file:
            file_url = await self.decompress_and_upload_file(file)

        # Create the main resource with transcript
        resource = LearningResource(
            folder_id=folder_id,
            user_id=user_id,
            resource_type=resource_type.value,
            transcript=transcript,
            file_url=file_url,
        )

        self.db.add(resource)

        # Increment user's resource count
        user = self.db.query(User).filter(User.id == user_id).first()
        if user:
            user.resource_count = (user.resource_count or 0) + 1

        self.db.commit()
        self.db.refresh(resource)

        # Handle multiple image uploads for IMAGE resource type
        if resource_type == LearningResourceFileType.IMAGE and files:
            image_urls = await self.upload_images_to_s3(files)

            # Create LearningResourceImage records for each uploaded image
            for image_url in image_urls:
                resource_image = LearningResourceImage(
                    user_id=user_id,
                    resource_id=resource.id,
                    image_url=image_url
                )
                self.db.add(resource_image)

            self.db.commit()

        return resource

    def create_folder(
        self,
        name: str,
        user_id: int,
        parent_folder_id: Optional[int] = None
    ):
        """
        Create a new folder.
        
        Args:
            name: Name of the folder
            user_id: ID of the current user (for security)
            parent_folder_id: ID of the parent folder, None for root level
            
        Returns:
            The created ResourceFolder object
            
        Raises:
            HTTPException: If parent folder doesn't exist or doesn't belong to user
        """
        # Verify parent folder exists and belongs to user if specified
        if parent_folder_id is not None:
            parent_folder = self.db.query(ResourceFolder).filter(
                ResourceFolder.id == parent_folder_id,
                ResourceFolder.user_id == user_id
            ).first()
            
            if not parent_folder:
                raise HTTPException(status_code=404, detail="Parent folder not found")
        
        # Create new folder
        folder = ResourceFolder(
            name=name,
            user_id=user_id,
            parent_folder_id=parent_folder_id
        )
        
        self.db.add(folder)
        self.db.commit()
        self.db.refresh(folder)
        return folder

    def get_resource(
        self,
        resource_id: int,
        user_id: int
    ):
        """
        Get a specific learning resource by ID.

        Args:
            resource_id: ID of the resource to retrieve
            user_id: ID of the current user (for security)

        Returns:
            The LearningResource object

        Raises:
            HTTPException: If resource not found or doesn't belong to user
        """
        resource = self.db.query(LearningResource).filter(
            LearningResource.id == resource_id,
            LearningResource.user_id == user_id
        ).first()

        if not resource:
            raise HTTPException(status_code=404, detail="Resource not found")

        return resource

    def get_resource_images(
        self,
        resource_id: int,
        user_id: int
    ) -> List[str]:
        """
        Get all image URLs for a specific learning resource, ordered by creation time.

        Args:
            resource_id: ID of the resource to retrieve images for
            user_id: ID of the current user (for security)

        Returns:
            List of image URLs in the order they were uploaded
        """
        images = self.db.query(LearningResourceImage).filter(
            LearningResourceImage.resource_id == resource_id,
            LearningResourceImage.user_id == user_id
        ).order_by(LearningResourceImage.created_at.asc()).all()

        return [image.image_url for image in images]

    def get_flash_cards(
        self,
        resource_id: int,
        user_id: int
    ):
        """
        Get all flash cards for a specific learning resource.
        
        Args:
            resource_id: ID of the resource to get flash cards for
            user_id: ID of the current user (for security)
            
        Returns:
            List of FlashCard objects for the resource
            
        Raises:
            HTTPException: If resource not found or doesn't belong to user
        """
        # First verify the resource exists and belongs to the user
        resource = self.db.query(LearningResource).filter(
            LearningResource.id == resource_id,
            LearningResource.user_id == user_id
        ).first()
        
        if not resource:
            raise HTTPException(status_code=404, detail="Resource not found")
        
        # Get all flash cards for this resource
        flash_cards = self.db.query(FlashCard).filter(
            FlashCard.resource_id == resource_id,
            FlashCard.user_id == user_id
        ).order_by(FlashCard.created_at.desc()).all()
        
        return flash_cards

    def get_resource_transcript(
        self,
        resource_id: int,
        user_id: int
    ) -> Optional[str]:
        """
        Get the transcript for a specific learning resource by ID.
        
        Args:
            resource_id: ID of the resource to get transcript for
            user_id: ID of the current user (for security)
            
        Returns:
            The transcript string, or None if no transcript exists
            
        Raises:
            HTTPException: If resource not found or doesn't belong to user
        """
        # Query with undefer to explicitly load the transcript field
        resource = self.db.query(LearningResource).options(
            undefer(LearningResource.transcript)
        ).filter(
            LearningResource.id == resource_id,
            LearningResource.user_id == user_id
        ).first()
        
        if not resource:
            raise HTTPException(status_code=404, detail="Resource not found")
        
        return resource.transcript

    def check_flash_cards_exist(
        self,
        resource_id: int,
        user_id: int
    ) -> bool:
        """
        Check if any flash cards exist for a specific learning resource.
        
        Args:
            resource_id: ID of the resource to check for flash cards
            user_id: ID of the current user (for security)
            
        Returns:
            True if flash cards exist for the resource, False otherwise
            
        Raises:
            HTTPException: If resource not found or doesn't belong to user
        """
        # First verify the resource exists and belongs to the user
        resource = self.db.query(LearningResource).filter(
            LearningResource.id == resource_id,
            LearningResource.user_id == user_id
        ).first()
        
        if not resource:
            raise HTTPException(status_code=404, detail="Resource not found")
        
        # Check if any flash cards exist for this resource
        flash_card_count = self.db.query(FlashCard).filter(
            FlashCard.resource_id == resource_id,
            FlashCard.user_id == user_id
        ).count()
        
        return flash_card_count > 0

    def check_quiz_questions_exist(
        self,
        resource_id: int,
        user_id: int
    ) -> bool:
        """
        Check if any quiz questions exist for a specific learning resource.
        
        Args:
            resource_id: ID of the resource to check for quiz questions
            user_id: ID of the current user (for security)
            
        Returns:
            True if quiz questions exist for the resource, False otherwise
            
        Raises:
            HTTPException: If resource not found or doesn't belong to user
        """
        # First verify the resource exists and belongs to the user
        resource = self.db.query(LearningResource).filter(
            LearningResource.id == resource_id,
            LearningResource.user_id == user_id
        ).first()
        
        if not resource:
            raise HTTPException(status_code=404, detail="Resource not found")
        
        # Check if any quiz questions exist for this resource
        quiz_question_count = self.db.query(MultipleChoiceQuestion).filter(
            MultipleChoiceQuestion.resource_id == resource_id,
            MultipleChoiceQuestion.user_id == user_id
        ).count()
        
        return quiz_question_count > 0

    def get_quiz_questions(
        self,
        resource_id: int,
        user_id: int
    ):
        """
        Get all quiz questions for a specific learning resource.
        
        Args:
            resource_id: ID of the resource to get quiz questions for
            user_id: ID of the current user (for security)
            
        Returns:
            List of MultipleChoiceQuestion objects for the resource
            
        Raises:
            HTTPException: If resource not found or doesn't belong to user
        """
        # First verify the resource exists and belongs to the user
        resource = self.db.query(LearningResource).filter(
            LearningResource.id == resource_id,
            LearningResource.user_id == user_id
        ).first()
        
        if not resource:
            raise HTTPException(status_code=404, detail="Resource not found")
        
        # Get all quiz questions for this resource
        quiz_questions = self.db.query(MultipleChoiceQuestion).filter(
            MultipleChoiceQuestion.resource_id == resource_id,
            MultipleChoiceQuestion.user_id == user_id
        ).order_by(MultipleChoiceQuestion.created_at.desc()).all()
        
        return quiz_questions

    def check_transcript_exists(
        self,
        resource_id: int,
        user_id: int
    ) -> bool:
        """
        Check if a transcript exists for a specific learning resource.

        Args:
            resource_id: ID of the resource to check for transcript
            user_id: ID of the user who owns the resource

        Returns:
            True if transcript exists for the resource, False otherwise

        Raises:
            HTTPException: If resource not found or doesn't belong to user
        """
        # First verify the resource exists and belongs to the user
        resource = self.db.query(LearningResource).filter(
            LearningResource.id == resource_id,
            LearningResource.user_id == user_id
        ).first()

        if not resource:
            raise HTTPException(status_code=404, detail="Resource not found")

        # Check if transcript exists and is not None/empty
        return resource.transcript is not None and resource.transcript.strip() != ""

    def check_summary_notes_exist(
        self,
        resource_id: int,
        user_id: int
    ) -> bool:
        """
        Check if summary notes exist for a specific learning resource.

        Args:
            resource_id: ID of the resource to check for summary notes
            user_id: ID of the user who owns the resource

        Returns:
            True if summary notes exist for the resource, False otherwise

        Raises:
            HTTPException: If resource not found or doesn't belong to user
        """
        # First verify the resource exists and belongs to the user
        resource = self.db.query(LearningResource).filter(
            LearningResource.id == resource_id,
            LearningResource.user_id == user_id
        ).first()

        if not resource:
            raise HTTPException(status_code=404, detail="Resource not found")

        # Check if summary_notes exists and is not None/empty
        return resource.summary_notes is not None and resource.summary_notes.strip() != ""

    def delete_s3_file(self, file_url: str) -> bool:
        """
        Delete a file from S3 if it's from our bucket.
        Supports both s3:// and https:// S3 URLs.

        Args:
            file_url: The S3 URL of the file to delete

        Returns:
            True if file was deleted or doesn't need deletion, False if error occurred
        """
        if not file_url:
            return True  # Nothing to delete

        try:
            # Initialize S3 client
            s3_client = boto3.client('s3')
            bucket_name = settings.files_s3_bucket_name

            # Extract bucket and key from S3 URL
            if file_url.startswith('s3://'):
                # Format: s3://bucket-name/key/path
                url_parts = file_url.replace('s3://', '').split('/', 1)
                if len(url_parts) != 2:
                    return True  # Invalid URL format, nothing to delete
                file_bucket, s3_key = url_parts
            elif file_url.startswith('https://') and '.s3.' in file_url:
                # Format: https://bucket-name.s3.region.amazonaws.com/key/path
                import re
                match = re.match(r'https://([^.]+)\.s3\.[^/]+\.amazonaws\.com/(.+)', file_url)
                if match:
                    file_bucket = match.group(1)
                    s3_key = match.group(2)
                else:
                    return True  # Can't parse URL, nothing to delete
            else:
                return True  # Not an S3 URL, nothing to delete

            # Only delete if it's from our bucket
            if file_bucket != bucket_name:
                return True  # Not our bucket, nothing to delete

            # Delete the object from S3
            s3_client.delete_object(Bucket=bucket_name, Key=s3_key)
            return True

        except Exception as e:
            # Log the error but don't fail the deletion
            print(f"Warning: Failed to delete S3 file {file_url}: {str(e)}")
            return False

    def delete_resource(
        self,
        resource_id: int,
        user_id: int
    ) -> bool:
        """
        Delete a learning resource and its associated S3 file.

        Args:
            resource_id: ID of the resource to delete
            user_id: ID of the current user (for security)

        Returns:
            True if resource was deleted successfully

        Raises:
            HTTPException: If resource not found or doesn't belong to user
        """
        # First verify the resource exists and belongs to the user
        resource = self.db.query(LearningResource).filter(
            LearningResource.id == resource_id,
            LearningResource.user_id == user_id
        ).first()

        if not resource:
            raise HTTPException(status_code=404, detail="Resource not found")

        # Delete S3 file if it exists and is from our bucket
        if resource.file_url:
            self.delete_s3_file(resource.file_url)

        # Delete associated resource images and their S3 files
        resource_images = self.db.query(LearningResourceImage).filter(
            LearningResourceImage.resource_id == resource_id,
            LearningResourceImage.user_id == user_id
        ).all()

        for resource_image in resource_images:
            if resource_image.image_url:
                self.delete_s3_file(resource_image.image_url)

        self.db.query(LearningResourceImage).filter(
            LearningResourceImage.resource_id == resource_id,
            LearningResourceImage.user_id == user_id
        ).delete()

        # Delete associated flash cards
        self.db.query(FlashCard).filter(
            FlashCard.resource_id == resource_id,
            FlashCard.user_id == user_id
        ).delete()

        # Delete associated quiz questions
        self.db.query(MultipleChoiceQuestion).filter(
            MultipleChoiceQuestion.resource_id == resource_id,
            MultipleChoiceQuestion.user_id == user_id
        ).delete()

        # Delete the resource itself
        self.db.delete(resource)
        self.db.commit()

        return True

    def delete_folder(
        self,
        folder_id: int,
        user_id: int
    ) -> bool:
        """
        Recursively delete a folder and all its contents.

        Args:
            folder_id: ID of the folder to delete
            user_id: ID of the current user (for security)

        Returns:
            True if folder was deleted successfully

        Raises:
            HTTPException: If folder not found or doesn't belong to user, or if trying to delete root folder
        """
        # Prevent deletion of root folder
        if folder_id == 1:
            raise HTTPException(status_code=400, detail="Cannot delete root folder")

        # First verify the folder exists and belongs to the user
        folder = self.db.query(ResourceFolder).filter(
            ResourceFolder.id == folder_id,
            ResourceFolder.user_id == user_id
        ).first()

        if not folder:
            raise HTTPException(status_code=404, detail="Folder not found")

        # Recursively delete all contents
        self._recursive_delete_folder_contents(folder_id, user_id)

        # Delete the folder itself
        self.db.delete(folder)
        self.db.commit()

        return True

    def _recursive_delete_folder_contents(
        self,
        folder_id: int,
        user_id: int
    ) -> None:
        """
        Recursively delete all contents of a folder (subfolders and resources).

        Args:
            folder_id: ID of the folder whose contents to delete
            user_id: ID of the current user (for security)
        """
        # Get all subfolders in this folder
        subfolders = self.db.query(ResourceFolder).filter(
            ResourceFolder.parent_folder_id == folder_id,
            ResourceFolder.user_id == user_id
        ).all()

        # Recursively delete each subfolder
        for subfolder in subfolders:
            self._recursive_delete_folder_contents(subfolder.id, user_id)
            self.db.delete(subfolder)

        # Get all resources in this folder
        resources = self.db.query(LearningResource).filter(
            LearningResource.folder_id == folder_id,
            LearningResource.user_id == user_id
        ).all()

        # Delete each resource and its S3 file
        for resource in resources:
            # Delete S3 file if it exists and is from our bucket
            if resource.file_url:
                self.delete_s3_file(resource.file_url)

            # Delete associated resource images and their S3 files
            resource_images = self.db.query(LearningResourceImage).filter(
                LearningResourceImage.resource_id == resource.id,
                LearningResourceImage.user_id == user_id
            ).all()

            for resource_image in resource_images:
                if resource_image.image_url:
                    self.delete_s3_file(resource_image.image_url)

            self.db.query(LearningResourceImage).filter(
                LearningResourceImage.resource_id == resource.id,
                LearningResourceImage.user_id == user_id
            ).delete()

            # Delete associated flash cards
            self.db.query(FlashCard).filter(
                FlashCard.resource_id == resource.id,
                FlashCard.user_id == user_id
            ).delete()

            # Delete associated quiz questions
            self.db.query(MultipleChoiceQuestion).filter(
                MultipleChoiceQuestion.resource_id == resource.id,
                MultipleChoiceQuestion.user_id == user_id
            ).delete()

            # Delete the resource itself
            self.db.delete(resource)

    def chat_with_resource(
        self,
        resource_id: int,
        user_id: int,
        message: str,
        conversation_history: List[Dict[str, str]] = None
    ) -> str:
        """
        Chat with a learning resource using AI based on its content.

        Args:
            resource_id: ID of the resource to chat about
            user_id: ID of the current user (for security)
            message: The user's message/question
            conversation_history: Optional list of previous messages in format [{"role": "...", "content": "..."}]

        Returns:
            The AI-generated response string

        Raises:
            HTTPException: If resource not found or doesn't belong to user
        """
        # Query with undefer to explicitly load the transcript field
        resource = self.db.query(LearningResource).options(
            undefer(LearningResource.transcript)
        ).filter(
            LearningResource.id == resource_id,
            LearningResource.user_id == user_id
        ).first()

        if not resource:
            raise HTTPException(status_code=404, detail="Resource not found")

        # Build the context from the resource content
        context_parts = []

        if resource.title:
            context_parts.append(f"Resource Title: {resource.title}")

        if resource.summary_notes and resource.summary_notes.strip():
            context_parts.append(f"Summary Notes:\n{resource.summary_notes}")

        if not context_parts:
            raise HTTPException(
                status_code=400,
                detail="This resource doesn't have any content to chat about yet. Please wait for processing to complete."
            )

        resource_context = "\n\n".join(context_parts)

        # Build the system message with resource context
        system_message = f"""You are a helpful tutor assistant helping a student learn from their study materials.

Your role is to:
- Answer questions about the content clearly and accurately
- Help the student understand difficult concepts
- Provide examples and clarifications when needed
- Encourage learning and critical thinking
- Base your answers on the provided content, but you can also add relevant supplementary information

Always be supportive, patient, educational, but brief and succinct in your responses.

The student has provided you with the following learning resource context from their notes:

{resource_context}
"""

        # Build the messages array for OpenAI
        messages = [{"role": "system", "content": system_message}]

        # Add conversation history if provided
        if conversation_history:
            for msg in conversation_history:
                messages.append({
                    "role": msg.get("role", "user"),
                    "content": msg.get("content", "")
                })

        # Add the current user message
        messages.append({"role": "user", "content": message})

        try:
            # Initialize OpenAI client
            client = OpenAI()

            # Get response from OpenAI
            response = client.chat.completions.create(
                model="gpt-5",
                messages=messages,
            )

            # Extract and return the response message
            response_message = response.choices[0].message.content

            if not response_message or response_message.strip() == "":
                raise HTTPException(
                    status_code=500,
                    detail="Failed to generate a response. Please try again."
                )

            return response_message.strip()

        except Exception as e:
            logger.error(f"Failed to generate chat response for resource {resource_id}: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to generate response: {str(e)}"
            )