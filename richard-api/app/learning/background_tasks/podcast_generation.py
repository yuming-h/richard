from openai import OpenAI
from app.learning.models import LearningResource, Podcast, ResourceStatus
from sqlalchemy.orm import Session
import logging
from app.database import get_db # Added for db session management

logger = logging.getLogger(__name__)

PODCAST_SCRIPT_PROMPT = """
You are an expert podcast scriptwriter. Your task is to transform the provided text into a compelling and engaging podcast script.

Here are the guidelines:
1.  **Format**: The script should be in a narrative style, suitable for a single host. No need for multiple characters or dialogue tags.
2.  **Engagement**: Make it conversational and easy to listen to. Use language that would resonate with a general audience.
3.  **Clarity**: Explain complex topics simply and clearly.
4.  **Structure**:
    -   **Introduction**: Hook the listener and introduce the main topic.
    -   **Body**: Elaborate on the key points from the original text, breaking them down into logical segments.
    -   **Conclusion**: Summarize the main takeaways and offer a thought-provoking closing statement or call to action (if appropriate).
5.  **Length**: Aim for a script that would translate to a 5-10 minute podcast segment. Adjust verbosity based on the input text's length.
6.  **Tone**: Informative, enthusiastic, and approachable.
7.  **No filler**: Do not include any intros like "Here is your podcast script:" or similar. Just provide the script directly.
"""

def generate_podcast_script(resource_id: int):
    """
    Generate a podcast script from the learning resource's transcript using OpenAI GPT.
    
    Args:
        resource_id: ID of the resource to generate the podcast for.
    """
    db = next(get_db())
    try:
        resource = db.query(LearningResource).filter(LearningResource.id == resource_id).first()
        if not resource:
            logger.error(f"Resource not found: {resource_id}")
            return

        if not resource.transcript or resource.transcript.strip() == "":
            logger.warning(f"No transcript available for resource {resource_id}, cannot generate podcast script")
            resource.status = ResourceStatus.FAILED.value
            db.commit()
            db.refresh(resource)
            return

        logger.info(f"Generating podcast script for resource {resource_id}")
        
        client = OpenAI()
        
        response = client.chat.completions.create(
            model="gpt-4", # Using gpt-4 for potentially better script generation
            messages=[
                {
                    "role": "system",
                    "content": PODCAST_SCRIPT_PROMPT
                },
                {
                    "role": "user",
                    "content": resource.transcript
                }
            ],
            temperature=0.7, # A bit more creative
        )
        
        generated_script = response.choices[0].message.content.strip()

        if not generated_script:
            logger.error(f"OpenAI returned empty podcast script for resource {resource.id}")
            resource.status = ResourceStatus.FAILED.value
            db.commit()
            db.refresh(resource)
            return

        # Always create a new podcast entry, as a resource can have many podcasts
        podcast = Podcast(learning_resource_id=resource.id, transcript=generated_script)
        db.add(podcast)
        
        db.commit()
        db.refresh(podcast)

        logger.info(f"Generated podcast script for resource {resource_id} (length: {len(generated_script)} chars)")
        
    except Exception as e:
        logger.error(f"Failed to generate podcast script for resource {resource_id}: {e}")
        if resource.status != ResourceStatus.FAILED.value: # Avoid overwriting if already failed
            resource.status = ResourceStatus.FAILED.value
            db.commit()
            db.refresh(resource)
    finally:
        db.close()
