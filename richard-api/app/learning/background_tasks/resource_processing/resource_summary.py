from openai import OpenAI
from app.learning.models import LearningResource, LearningResourceFileType
from sqlalchemy.orm import Session
import re
import logging
import yt_dlp
import json

logger = logging.getLogger(__name__)

GET_TITLE_PROMPT = """
You are helping to name 'documents' based on text that will be given to you by the user.
The user will provide text and you should give the 'document' a title based on the content of the text.
It will only be the beginning/introduction of the text and may be cut off, so keep this in mind.
The title should be short and concise, like the title of an article or a ChatGPT conversation name.
"""

SUMMARIZE_TEXT_PROMPT = """
You are a tutor that is helping a student learn.
You will be given a string of text by the student. This text may be the transcript of a lecture, a book, or other documents wherein the user wants to learn from.
Your job is to provide summary notes in markdown format for the student to learn from.
The summary should cover all the key points and main ideas presented in the original text, while also condensing the information into a concise and easy-to-understand format. Please ensure that the summary includes relevant details and examples that support the main ideas, while avoiding any unnecessary information or repetition. The length of the summary should be appropriate for the length and complexity of the original text, providing a clear and accurate overview without omitting any important information.
Also choose a single emoji that best represents the text.
"""

def generate_resource_title(resource: LearningResource, db: Session = None):
    """
    Generate a title for the learning resource using OpenAI GPT based on the transcript content.
    
    Args:
        resource: LearningResource object with transcript content
        db: Database session for saving the generated title
    """

    CHAR_LIMIT = 2000
    try:
        if not resource.summary_notes or resource.summary_notes.strip() == "":
            logger.warning(f"No summary notes available for resource {resource.id}, cannot generate title")
            return

        if resource.title and resource.title.strip() != "":
            logger.info(f"Resource {resource.id} already has a title: {resource.title}")
            return

        logger.info(f"Generating title for resource {resource.id}")

        # Use first 1500 characters of summary notes for title generation to stay within token limits
        summary_sample = resource.summary_notes[:1500]
        if len(resource.summary_notes) > 1500:
            # Find the last complete sentence within the limit
            last_sentence_end = max(
                summary_sample.rfind('.'),
                summary_sample.rfind('!'),
                summary_sample.rfind('?')
            )
            if last_sentence_end > 750:  # Ensure we have meaningful content
                summary_sample = summary_sample[:last_sentence_end + 1]
        
        # Initialize OpenAI client
        client = OpenAI()
        
        # Generate title using gpt-5
        response = client.chat.completions.create(
            model="gpt-5",
            messages=[
                {
                    "role": "system",
                    "content": GET_TITLE_PROMPT
                },
                {
                    "role": "user",
                    "content": summary_sample
                }
            ],
        )
        
        # Extract the generated title
        generated_title = response.choices[0].message.content

        if not generated_title or generated_title.strip() == "":
            logger.error(f"OpenAI returned empty title for resource {resource.id}")
            return

        generated_title = generated_title.strip()

        # Clean up the title (remove quotes if GPT added them, limit length)
        generated_title = generated_title.strip('"\'')
        if len(generated_title) > 200:  # Limit title length
            generated_title = generated_title[:200].strip()

        if not generated_title:
            logger.error(f"Title became empty after cleanup for resource {resource.id}")
            return

        # Save the title to the resource
        resource.title = generated_title

        if db:
            db.commit()
            db.refresh(resource)

        logger.info(f"Generated title for resource {resource.id}: {generated_title}")
        
    except Exception as e:
        logger.error(f"Failed to generate title for resource {resource.id}: {e}")
        # Don't raise the exception - title generation is not critical
        # The resource can still function without a custom title

def summarize_text(resource: LearningResource, db: Session = None):
    """
    Generate summary notes for the learning resource using OpenAI GPT based on the transcript content.
    
    Args:
        resource: LearningResource object with transcript content
        db: Database session for saving the generated summary
    """
    try:
        if not resource.transcript or resource.transcript.strip() == "":
            logger.warning(f"No transcript available for resource {resource.id}, cannot generate summary")
            return
        
        if resource.summary_notes and resource.summary_notes.strip() != "":
            logger.info(f"Resource {resource.id} already has summary notes")
            return
        
        logger.info(f"Generating summary for resource {resource.id}")
        
        # Initialize OpenAI client
        client = OpenAI()
        
        response_schema = {
            "name": "summary_with_emoji",
            "schema": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Summary notes of the text in markdown."
                    },
                    "emoji": {
                        "type": "string",
                        "description": "A single emoji that best represents the text."
                    },
                },
                "required": ["summary", "emoji"],
                "additionalProperties": False,
            },
        }

        # Generate summary using gpt-5
        response = client.chat.completions.create(
            model="gpt-5",
            messages=[
                {
                    "role": "system",
                    "content": SUMMARIZE_TEXT_PROMPT
                },
                {
                    "role": "user",
                    "content": resource.transcript
                }
            ],
            response_format={
                "type": "json_schema",
                "json_schema": response_schema,
            },
        )
        
        raw_content = response.choices[0].message.content
        try:
            parsed_content = json.loads(raw_content or "")
        except json.JSONDecodeError as e:
            logger.error(f"OpenAI returned invalid JSON for resource {resource.id}: {e}")
            return

        generated_summary = (parsed_content.get("summary") or "").strip()
        generated_emoji = (parsed_content.get("emoji") or "").strip()

        if not generated_summary or generated_summary.strip() == "":
            logger.error(f"OpenAI returned empty summary for resource {resource.id}")
            return

        # Save the summary to the resource
        resource.summary_notes = generated_summary
        resource.emoji = generated_emoji or resource.emoji

        if db:
            db.commit()
            db.refresh(resource)

        logger.info(f"Generated summary for resource {resource.id} (length: {len(generated_summary)} chars)")
        
    except Exception as e:
        logger.error(f"Failed to generate summary for resource {resource.id}: {e}")
        # Don't raise the exception - summary generation is not critical


def gen_youtube_title(resource: LearningResource, db: Session = None):
    """
    Extract the title from a YouTube video URL and save it to the resource.
    
    Args:
        resource: LearningResource object with YouTube URL in file_url
        db: Database session for saving the extracted title
    """
    try:
        if not resource.file_url or resource.file_url.strip() == "":
            logger.warning(f"No file_url available for resource {resource.id}, cannot extract YouTube title")
            return
        
        if resource.title and resource.title.strip() != "":
            logger.info(f"Resource {resource.id} already has a title: {resource.title}")
            return
        
        logger.info(f"Extracting YouTube title for resource {resource.id} from URL: {resource.file_url}")
        
        # Configure yt-dlp options for quiet operation
        ydl_opts = {
            'skip_download': True,  # don't download video
            'quiet': True,
            'no_warnings': True,
        }
        
        # Extract video information without downloading
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(resource.file_url, download=False)
            title = info_dict.get('title', None)
            
            if title:
                # Clean up the title and limit length
                title = title.strip()
                if len(title) > 200:  # Limit title length
                    title = title[:200].strip()
                
                # Save the title to the resource
                resource.title = title
                
                if db:
                    db.commit()
                    db.refresh(resource)
                
                logger.info(f"Extracted YouTube title for resource {resource.id}: {title}")
            else:
                logger.warning(f"Could not extract title from YouTube URL for resource {resource.id}")
        
    except Exception as e:
        logger.error(f"Failed to extract YouTube title for resource {resource.id}: {e}")
        # Don't raise the exception - title extraction is not critical


# Map resource types to their title generation functions
RESOURCE_TYPE_TO_GEN_TITLE_FUNCTION = {
    LearningResourceFileType.YOUTUBE_LINK: generate_resource_title,
    LearningResourceFileType.PDF: generate_resource_title,
    LearningResourceFileType.AUDIO: generate_resource_title,
    LearningResourceFileType.TEXT: generate_resource_title,
}