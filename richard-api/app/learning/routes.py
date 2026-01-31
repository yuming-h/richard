from fastapi import (
    APIRouter,
    Depends,
    UploadFile,
    File,
    Form,
    BackgroundTasks,
    Query,
    HTTPException,
    Request,
)
from pydantic import BaseModel
from typing import Optional, List, Literal, Union, Any
from datetime import datetime
from app.auth_dependencies import get_current_user
from app.users.models import User
from app.learning.models import LearningResourceFileType, ResourceStatus
from app.learning.background_tasks.resource_processing.resource_ingestion import (
    ingest_resource,
)
from app.learning.background_tasks.flash_card_generation import generate_flash_cards
from app.learning.background_tasks.quiz_generation import generate_quiz_questions
from app.learning.learning_service import LearningService


router = APIRouter(prefix="/learning", tags=["learning"])


class CreateResourceRequest(BaseModel):
    folder_id: int
    resource_type: LearningResourceFileType
    summary_notes: str = ""
    file: Optional[UploadFile] = File(None)
    file_url: Optional[str] = None


class CreateFolderRequest(BaseModel):
    name: str
    parent_folder_id: Optional[int] = None  # None for root level folders


class FolderItem(BaseModel):
    id: int
    name: Optional[str] = None  # For folders
    title: Optional[str] = None  # For resources
    emoji: Optional[str] = None  # For resources
    parent_folder_id: Optional[int] = None  # For folders
    resource_type: Optional[LearningResourceFileType] = None  # For resources
    folder_id: Optional[int] = None  # For resources
    file_url: Optional[str] = None  # For resources
    status: Optional[ResourceStatus] = None  # For resources
    created_at: datetime
    updated_at: datetime
    type: str  # "folder" or "resource"


class FolderContentsResponse(BaseModel):
    folder_id: int
    folder_name: str
    created_at: datetime
    items: List[FolderItem]


class FolderResponse(BaseModel):
    id: int
    name: str
    parent_folder_id: Optional[int]
    created_at: datetime
    updated_at: datetime


class ResourceResponse(BaseModel):
    id: int
    title: Optional[str]
    emoji: Optional[str]
    resource_type: LearningResourceFileType
    folder_id: int
    file_url: Optional[str]
    image_urls: List[str] = []
    summary_notes: Optional[str]
    status: ResourceStatus
    created_at: datetime
    updated_at: datetime


class ResourceStatusResponse(BaseModel):
    id: int
    title: Optional[str]
    resource_type: LearningResourceFileType
    status: ResourceStatus
    created_at: datetime
    updated_at: datetime


class FlashCardResponse(BaseModel):
    id: int
    resource_id: int
    front: str
    back: str
    created_at: datetime
    updated_at: datetime


class TranscriptResponse(BaseModel):
    resource_id: int
    transcript: Optional[str]


class FlashCardsExistResponse(BaseModel):
    resource_id: int
    has_flash_cards: bool


class QuizQuestionsExistResponse(BaseModel):
    resource_id: int
    has_quiz_questions: bool


class TranscriptExistResponse(BaseModel):
    resource_id: int
    has_transcript: bool


class SummaryNotesExistResponse(BaseModel):
    resource_id: int
    has_summary_notes: bool


class QuizQuestionResponse(BaseModel):
    id: int
    resource_id: int
    question: str
    options: List[str]
    correct_option: str
    created_at: datetime
    updated_at: datetime


class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    conversation_history: List[ChatMessage] = []


class ChatResponse(BaseModel):
    message: str


@router.get("/folders", response_model=List[FolderResponse])
async def list_folders(
    current_user: User = Depends(get_current_user),
    learning_service: LearningService = Depends(LearningService),
):
    """
    List all folders that belong to the current user.

    Returns a list of all folders owned by the authenticated user,
    ordered by creation date (most recent first).
    """
    folders = learning_service.list_user_folders(user_id=current_user.id)

    return [
        FolderResponse(
            id=folder.id,
            name=folder.name,
            parent_folder_id=folder.parent_folder_id,
            created_at=folder.created_at,
            updated_at=folder.updated_at,
        )
        for folder in folders
    ]


@router.get("/folder/{folder_id}", response_model=FolderContentsResponse)
async def get_folder_contents(
    folder_id: int,
    item_type: Optional[Literal["folder", "resource"]] = Query(
        None,
        description="Filter by item type: 'folder' or 'resource'. If empty, returns all items.",
    ),
    current_user: User = Depends(get_current_user),
    learning_service: LearningService = Depends(LearningService),
):
    """
    Get contents of a specific folder by ID.

    - **folder_id**: The ID of the folder to retrieve contents from
    - **item_type**: Optional filter - 'folder' for subfolders only, 'resource' for resources only, or omit for both

    Returns a list of items (folders and/or resources) in the specified folder.
    """

    result = learning_service.get_folder_contents(
        folder_id=folder_id, user_id=current_user.id, item_type=item_type
    )

    # Convert dictionary items to FolderItem models
    items = [FolderItem(**item) for item in result["items"]]

    return FolderContentsResponse(
        folder_id=result["folder_id"],
        folder_name=result["folder_name"],
        created_at=result["created_at"],
        items=items,
    )


@router.post("/folder", response_model=FolderResponse)
async def create_folder(
    request: CreateFolderRequest,
    current_user: User = Depends(get_current_user),
    learning_service: LearningService = Depends(LearningService),
):
    """
    Create a new folder.

    - **name**: Name of the folder
    - **parent_folder_id**: ID of the parent folder (optional, None for root level)

    Returns the created folder information.
    """
    folder = learning_service.create_folder(
        name=request.name,
        user_id=current_user.id,
        parent_folder_id=request.parent_folder_id,
    )

    return FolderResponse(
        id=folder.id,
        name=folder.name,
        parent_folder_id=folder.parent_folder_id,
        created_at=folder.created_at,
        updated_at=folder.updated_at,
    )


@router.delete("/folder/{folder_id}")
async def delete_folder(
    folder_id: int,
    current_user: User = Depends(get_current_user),
    learning_service: LearningService = Depends(LearningService),
):
    """
    Delete a folder and all its contents recursively.

    - **folder_id**: The ID of the folder to delete

    This endpoint recursively deletes:
    - The folder itself
    - All subfolders within the folder
    - All resources within the folder and its subfolders
    - Associated flash cards and quiz questions for each resource
    - S3 files associated with resources (if they're from our bucket)

    Note: The root folder (ID=1) cannot be deleted.
    Only folders that belong to the authenticated user can be deleted.
    """

    learning_service.delete_folder(folder_id=folder_id, user_id=current_user.id)

    return {
        "message": f"Folder {folder_id} and all its contents deleted successfully",
        "folder_id": folder_id,
    }


@router.post("/resources")
async def create_resource(
    request: Request,
    background_tasks: BackgroundTasks,
    learning_service: LearningService = Depends(LearningService),
    current_user: User = Depends(get_current_user),
    folder_id: Optional[int] = Form(None),
    resource_type: Optional[LearningResourceFileType] = Form(None),
    transcript: Optional[str] = Form(None),
    file_url: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    files: Optional[List[UploadFile]] = File(None),
):
    """
    Create a new learning resource
    Accepts either:
    - JSON body (for URL-based resources like YouTube links and TEXT resources)
    - Form data (for file uploads like PDF, AUDIO, IMAGE)
    """
    content_type = request.headers.get("content-type", "")

    # Handle JSON request
    if "application/json" in content_type:
        body = await request.json()
        folder_id = body.get("folder_id")
        resource_type = LearningResourceFileType(body.get("resource_type"))
        transcript = body.get("transcript", "")
        file_url = body.get("file_url")
        file = None
        files = None

        if not folder_id or not resource_type:
            raise HTTPException(
                status_code=400,
                detail="folder_id and resource_type are required"
            )

    # Handle form data request
    elif "multipart/form-data" in content_type:
        if folder_id is None or resource_type is None:
            raise HTTPException(
                status_code=400,
                detail="folder_id and resource_type are required in form data"
            )
        transcript = transcript or ""

    else:
        raise HTTPException(
            status_code=400,
            detail="Content-Type must be either application/json or multipart/form-data"
        )

    resource = await learning_service.create_resource(
        folder_id=folder_id,
        user_id=current_user.id,
        resource_type=resource_type,
        transcript=transcript,
        file_url=file_url,
        file=file,
        files=files,
    )

    background_tasks.add_task(ingest_resource, resource.id)

    return {
        "message": f"Resource created by {current_user.email}",
        "resource_id": resource.id,
        "user_id": current_user.id,
    }


@router.get("/resources/{resource_id}/status", response_model=ResourceStatusResponse)
async def get_resource_status(
    resource_id: int,
    current_user: User = Depends(get_current_user),
    learning_service: LearningService = Depends(LearningService),
):
    """
    Get lightweight status information for a resource (optimized for polling).

    - **resource_id**: The ID of the resource

    Returns only essential fields without large content like summary_notes.
    Use this endpoint for status polling to reduce network overhead.
    """
    resource = learning_service.get_resource(
        resource_id=resource_id, user_id=current_user.id
    )

    return ResourceStatusResponse(
        id=resource.id,
        title=resource.title,
        resource_type=resource.resource_type,
        status=resource.status,
        created_at=resource.created_at,
        updated_at=resource.updated_at,
    )


@router.get("/resources/{resource_id}", response_model=ResourceResponse)
async def get_resource(
    resource_id: int,
    current_user: User = Depends(get_current_user),
    learning_service: LearningService = Depends(LearningService),
):
    """
    Get a specific learning resource by ID.

    - **resource_id**: The ID of the resource to retrieve

    Returns the complete resource information including metadata, content details, and status.
    For image resources, includes a list of image URLs in the order they were uploaded.
    Only returns resources that belong to the authenticated user.
    """

    resource = learning_service.get_resource(
        resource_id=resource_id, user_id=current_user.id
    )

    # Fetch image URLs for image resources
    image_urls = []
    if resource.resource_type == LearningResourceFileType.IMAGE:
        image_urls = learning_service.get_resource_images(
            resource_id=resource_id, user_id=current_user.id
        )

    return ResourceResponse(
        id=resource.id,
        title=resource.title,
        emoji=resource.emoji,
        resource_type=resource.resource_type,
        folder_id=resource.folder_id,
        file_url=resource.file_url,
        image_urls=image_urls,
        summary_notes=resource.summary_notes,
        status=resource.status,
        created_at=resource.created_at,
        updated_at=resource.updated_at,
    )


@router.get("/resources/{resource_id}/transcript", response_model=TranscriptResponse)
async def get_resource_transcript(
    resource_id: int,
    current_user: User = Depends(get_current_user),
    learning_service: LearningService = Depends(LearningService),
):
    """
    Get the transcript for a specific learning resource by ID.

    - **resource_id**: The ID of the resource to retrieve the transcript for

    Returns the transcript content for the resource.
    Only returns transcripts for resources that belong to the authenticated user.
    """

    transcript = learning_service.get_resource_transcript(
        resource_id=resource_id, user_id=current_user.id
    )

    return TranscriptResponse(resource_id=resource_id, transcript=transcript)


@router.get(
    "/resources/{resource_id}/flash-cards", response_model=List[FlashCardResponse]
)
async def get_flash_cards(
    resource_id: int,
    current_user: User = Depends(get_current_user),
    learning_service: LearningService = Depends(LearningService),
):
    """
    Get the flash cards for a specific learning resource by ID.

    - **resource_id**: The ID of the resource to get flash cards for

    Returns a list of flash cards associated with the resource.
    Only returns flash cards that belong to the authenticated user.
    """

    flash_cards = learning_service.get_flash_cards(
        resource_id=resource_id, user_id=current_user.id
    )

    return [
        FlashCardResponse(
            id=card.id,
            resource_id=card.resource_id,
            front=card.front,
            back=card.back,
            created_at=card.created_at,
            updated_at=card.updated_at,
        )
        for card in flash_cards
    ]


@router.get(
    "/resources/{resource_id}/flash-cards/exists",
    response_model=FlashCardsExistResponse,
)
async def check_flash_cards_exist(
    resource_id: int,
    current_user: User = Depends(get_current_user),
    learning_service: LearningService = Depends(LearningService),
):
    """
    Check if flash cards exist for a specific learning resource by ID.

    - **resource_id**: The ID of the resource to check for flash cards

    Returns a boolean indicating whether the resource has any associated flash cards.
    Only checks resources that belong to the authenticated user.
    """

    has_flash_cards = learning_service.check_flash_cards_exist(
        resource_id=resource_id, user_id=current_user.id
    )

    return FlashCardsExistResponse(
        resource_id=resource_id, has_flash_cards=has_flash_cards
    )


@router.get(
    "/resources/{resource_id}/quiz-questions/exists",
    response_model=QuizQuestionsExistResponse,
)
async def check_quiz_questions_exist(
    resource_id: int,
    current_user: User = Depends(get_current_user),
    learning_service: LearningService = Depends(LearningService),
):
    """
    Check if quiz questions exist for a specific learning resource by ID.

    - **resource_id**: The ID of the resource to check for quiz questions

    Returns a boolean indicating whether the resource has any associated quiz questions.
    Only checks resources that belong to the authenticated user.
    """

    has_quiz_questions = learning_service.check_quiz_questions_exist(
        resource_id=resource_id, user_id=current_user.id
    )

    return QuizQuestionsExistResponse(
        resource_id=resource_id, has_quiz_questions=has_quiz_questions
    )


@router.get(
    "/resources/{resource_id}/transcript/exists", response_model=TranscriptExistResponse
)
async def check_transcript_exists(
    resource_id: int,
    current_user: User = Depends(get_current_user),
    learning_service: LearningService = Depends(LearningService),
):
    """
    Check if a transcript exists for a specific learning resource by ID.

    - **resource_id**: The ID of the resource to check for transcript

    Returns a boolean indicating whether the resource has an associated transcript.
    Only checks resources that belong to the authenticated user.
    """

    has_transcript = learning_service.check_transcript_exists(
        resource_id=resource_id, user_id=current_user.id
    )

    return TranscriptExistResponse(
        resource_id=resource_id, has_transcript=has_transcript
    )


@router.get(
    "/resources/{resource_id}/summary-notes/exists",
    response_model=SummaryNotesExistResponse,
)
async def check_summary_notes_exist(
    resource_id: int,
    current_user: User = Depends(get_current_user),
    learning_service: LearningService = Depends(LearningService),
):
    """
    Check if summary notes exist for a specific learning resource by ID.

    - **resource_id**: The ID of the resource to check for summary notes

    Returns a boolean indicating whether the resource has associated summary notes.
    Only checks resources that belong to the authenticated user.
    """

    has_summary_notes = learning_service.check_summary_notes_exist(
        resource_id=resource_id, user_id=current_user.id
    )

    return SummaryNotesExistResponse(
        resource_id=resource_id, has_summary_notes=has_summary_notes
    )


@router.post("/resources/{resource_id}/flash-cards/ai")
async def generate_flash_cards_for_resource(
    resource_id: int,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    learning_service: LearningService = Depends(LearningService),
):
    """
    Generate flash cards for a specific learning resource using AI.

    - **resource_id**: The ID of the resource to generate flash cards for

    This endpoint starts a background task to generate flash cards using AI based on the resource's transcript content.
    The flash cards will be created asynchronously and can be retrieved using the GET flash cards endpoint.
    Only works for resources that belong to the authenticated user.
    """

    # Verify the resource exists and belongs to the user
    resource = learning_service.get_resource(
        resource_id=resource_id, user_id=current_user.id
    )

    # Add background task to generate flash cards
    background_tasks.add_task(generate_flash_cards, resource_id)

    return {
        "message": f"Flash card generation started for resource {resource_id}",
        "resource_id": resource_id,
        "status": "processing",
    }


@router.get(
    "/resources/{resource_id}/quiz-questions", response_model=List[QuizQuestionResponse]
)
async def get_quiz_questions(
    resource_id: int,
    current_user: User = Depends(get_current_user),
    learning_service: LearningService = Depends(LearningService),
):
    """
    Get the quiz questions for a specific learning resource by ID.

    - **resource_id**: The ID of the resource to get quiz questions for

    Returns a list of multiple choice questions associated with the resource.
    Only returns quiz questions that belong to the authenticated user.
    """

    quiz_questions = learning_service.get_quiz_questions(
        resource_id=resource_id, user_id=current_user.id
    )

    return [
        QuizQuestionResponse(
            id=question.id,
            resource_id=question.resource_id,
            question=question.question,
            options=question.options.split(
                "\n"
            ),  # Convert newline-separated string back to list
            correct_option=question.correct_option,
            created_at=question.created_at,
            updated_at=question.updated_at,
        )
        for question in quiz_questions
    ]


@router.post("/resources/{resource_id}/quiz-questions/ai")
async def generate_quiz_questions_for_resource(
    resource_id: int,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    learning_service: LearningService = Depends(LearningService),
):
    """
    Generate quiz questions for a specific learning resource using AI.

    - **resource_id**: The ID of the resource to generate quiz questions for

    This endpoint starts a background task to generate quiz questions using AI based on the resource's transcript content.
    The quiz questions will be created asynchronously and can be retrieved using the GET quiz questions endpoint.
    Only works for resources that belong to the authenticated user.
    """

    # Verify the resource exists and belongs to the user
    resource = learning_service.get_resource(
        resource_id=resource_id, user_id=current_user.id
    )

    # Add background task to generate quiz questions
    background_tasks.add_task(generate_quiz_questions, resource_id)

    return {
        "message": f"Quiz question generation started for resource {resource_id}",
        "resource_id": resource_id,
        "status": "processing",
    }


@router.delete("/resources/{resource_id}")
async def delete_resource(
    resource_id: int,
    current_user: User = Depends(get_current_user),
    learning_service: LearningService = Depends(LearningService),
):
    """
    Delete a learning resource by ID.

    - **resource_id**: The ID of the resource to delete

    This endpoint deletes a learning resource and all its associated data:
    - The resource record from the database
    - Associated flash cards
    - Associated quiz questions
    - The S3 file (if it's from our bucket)

    Only resources that belong to the authenticated user can be deleted.
    """

    learning_service.delete_resource(resource_id=resource_id, user_id=current_user.id)

    return {
        "message": f"Resource {resource_id} deleted successfully",
        "resource_id": resource_id,
    }


@router.post("/resources/{resource_id}/flash-cards/manual")
async def manual_create_flash_card(
    resource_id: int,
    current_user: User = Depends(get_current_user),
    learning_service: LearningService = Depends(LearningService),
):
    """
    Create a new flash card for a specific learning resource by ID.
    """

@router.post("/resources/{resource_id}/chat", response_model=ChatResponse)
async def send_resource_chat_message(
    resource_id: int,
    chat_request: ChatRequest,
    current_user: User = Depends(get_current_user),
    learning_service: LearningService = Depends(LearningService),
):
    """
    Chat with a specific learning resource by ID.

    - **resource_id**: The ID of the resource to chat about
    - **message**: The user's message/question
    - **conversation_history**: Optional list of previous messages in the conversation

    Returns an AI-generated response based on the resource's content (summary notes and transcript).
    The conversation context is managed client-side - pass previous messages in conversation_history.
    """

    # Verify the resource exists and belongs to the user
    resource = learning_service.get_resource(
        resource_id=resource_id, user_id=current_user.id
    )

    # Convert Pydantic models to dictionaries for the service layer
    conversation_history_dicts = [
        {"role": msg.role, "content": msg.content}
        for msg in chat_request.conversation_history
    ]

    # Get AI response
    response_message = learning_service.chat_with_resource(
        resource_id=resource_id,
        user_id=current_user.id,
        message=chat_request.message,
        conversation_history=conversation_history_dicts
    )

    return ChatResponse(message=response_message)