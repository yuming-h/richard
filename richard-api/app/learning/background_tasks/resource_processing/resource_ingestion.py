from app.learning.models import LearningResource, LearningResourceFileType, ResourceStatus
from app.database import get_db
from sqlalchemy.orm import Session
from fastapi import Depends

import re
import logging
from app.learning.background_tasks.resource_processing.resource_transcription import RESOURCE_TYPE_TO_TRANSCRIBE_FUNCTION
from app.learning.background_tasks.resource_processing.resource_summary import RESOURCE_TYPE_TO_GEN_TITLE_FUNCTION, summarize_text
logger = logging.getLogger(__name__)



def save_resource_status(resource: LearningResource, status: ResourceStatus, db: Session = None):
    resource.status = status
    db.commit()
    db.refresh(resource)



def ingest_resource(resource_id: int):
    """
    Process a learning resource by transcribing/extracting content and updating status.
    
    Args:
        resource_id: ID of the resource to process
        
    Returns:
        The processed LearningResource object
    """
    # Create database session for background task
    db = next(get_db())
    
    try:
        resource = db.query(LearningResource).filter(LearningResource.id == resource_id).first()
        if not resource:
            raise Exception(f"Resource not found: {resource_id}")

        logger.info(f"Processing resource {resource_id} of type {resource.resource_type}")

        if resource.resource_type in RESOURCE_TYPE_TO_TRANSCRIBE_FUNCTION:
            save_resource_status(resource, ResourceStatus.TRANSCRIBING, db)
            RESOURCE_TYPE_TO_TRANSCRIBE_FUNCTION[resource.resource_type](resource, db)

        save_resource_status(resource, ResourceStatus.SUMMARIZING, db)


        summarize_text(resource, db)
        
        if resource.resource_type in RESOURCE_TYPE_TO_GEN_TITLE_FUNCTION:
            RESOURCE_TYPE_TO_GEN_TITLE_FUNCTION[resource.resource_type](resource, db)
        
        save_resource_status(resource, ResourceStatus.COMPLETED, db)
        
        logger.info(f"Resource {resource_id} processed successfully")
        return resource
        
    except Exception as e:
        # Mark resource as failed if processing fails
        logger.error(f"Failed to process resource {resource_id}: {e}")
        try:
            resource = db.query(LearningResource).filter(LearningResource.id == resource_id).first()
            if resource:
                resource.status = ResourceStatus.FAILED
                db.commit()
        except Exception as commit_error:
            logger.error(f"Failed to update resource status to failed: {commit_error}")
        raise e
        
    finally:
        db.close()