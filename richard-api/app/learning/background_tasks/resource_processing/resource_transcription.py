from youtube_transcript_api import YouTubeTranscriptApi
import re
import logging
from app.learning.models import LearningResource, LearningResourceFileType
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# ================================================
### YOUTUBE
# ================================================

def extract_youtube_video_id(url: str) -> str:
    """
    Extract video ID from various YouTube URL formats.
    
    Supports:
    - https://www.youtube.com/watch?v=VIDEO_ID
    - https://youtu.be/VIDEO_ID  
    - https://youtube.com/watch?v=VIDEO_ID
    - https://m.youtube.com/watch?v=VIDEO_ID
    """
    patterns = [
        r'(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([a-zA-Z0-9_-]{11})',
        r'youtube\.com/watch\?.*v=([a-zA-Z0-9_-]{11})',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    
    raise ValueError(f"Could not extract video ID from URL: {url}")

def format_transcript_for_display(transcript_list: list) -> str:
    """
    Format transcript segments for better readability with proper line breaks and punctuation.
    
    Args:
        transcript_list: List of transcript segments from YouTube API
        
    Returns:
        Formatted transcript text with proper line breaks and punctuation
    """
    if not transcript_list:
        return ""
    
    formatted_segments = []
    current_paragraph = []
    last_end_time = 0
    
    for i, entry in enumerate(transcript_list):
        text = entry['text'].strip()
        start_time = entry['start']
        
        # Skip empty segments
        if not text:
            continue
            
        # Add basic punctuation if missing at end of sentences
        if text and not text[-1] in '.!?':
            # Check if this looks like end of sentence (next segment starts with capital or big time gap)
            next_entry = transcript_list[i + 1] if i + 1 < len(transcript_list) else None
            if next_entry:
                next_text = next_entry['text'].strip()
                time_gap = next_entry['start'] - (start_time + entry['duration'])
                
                # Add period if next segment starts with capital or there's a significant pause
                if (next_text and next_text[0].isupper()) or time_gap > 2.0:
                    text += '.'
        
        # Capitalize first letter if it isn't already
        if text and text[0].islower():
            text = text[0].upper() + text[1:]
        
        current_paragraph.append(text)
        
        # Create paragraph break for significant time gaps (more than 3 seconds)
        time_gap = start_time - last_end_time if last_end_time > 0 else 0
        if time_gap > 3.0 and current_paragraph:
            # Join current paragraph and add to formatted segments
            paragraph_text = ' '.join(current_paragraph)
            formatted_segments.append(paragraph_text)
            current_paragraph = []
        
        last_end_time = start_time + entry['duration']
    
    # Add any remaining paragraph
    if current_paragraph:
        paragraph_text = ' '.join(current_paragraph)
        formatted_segments.append(paragraph_text)
    
    # Join paragraphs with double line breaks
    formatted_text = '\n\n'.join(formatted_segments)
    
    # Clean up extra spaces and fix common issues
    formatted_text = re.sub(r'\s+', ' ', formatted_text)  # Multiple spaces to single space
    formatted_text = re.sub(r'\s+([.!?])', r'\1', formatted_text)  # Remove space before punctuation
    formatted_text = re.sub(r'([.!?])\s*([a-z])', r'\1 \2', formatted_text)  # Ensure space after punctuation
    
    return formatted_text.strip()

def transcribe_youtube_link(resource: LearningResource, db: Session = None):
    """
    Fetch transcript from YouTube video using YouTube Transcript API and format for display.
    
    Args:
        resource: LearningResource with file_url containing YouTube URL
        
    Updates:
        resource.transcript: The formatted transcript text with proper line breaks
    """
    try:
        if not resource.file_url:
            raise ValueError("No YouTube URL provided in resource.file_url")
        
        logger.info(f"Starting transcript fetch for YouTube video: {resource.file_url}")
        
        # Extract video ID from URL
        video_id = extract_youtube_video_id(resource.file_url)
        logger.info(f"Extracted video ID: {video_id}")
        
        # Fetch transcript from YouTube
        try:
            # Create YouTubeTranscriptApi instance and fetch transcript
            ytt_api = YouTubeTranscriptApi()
            fetched_transcript = ytt_api.fetch(video_id)
            
            # Convert fetched transcript to list format for formatting function
            transcript_list = []
            for snippet in fetched_transcript:
                transcript_list.append({
                    'text': snippet.text,
                    'start': getattr(snippet, 'start', 0),
                    'duration': getattr(snippet, 'duration', 0)
                })
            
        except Exception as e:
            logger.error(f"Error fetching transcript: {e}")
            raise e
        
        # Format transcript for better readability
        formatted_transcript = format_transcript_for_display(transcript_list)
        
        # Save formatted transcript to resource
        resource.transcript = formatted_transcript
        
        logger.info(f"Transcript fetched and formatted successfully. Length: {len(formatted_transcript)} characters")
        
    except Exception as e:
        logger.error(f"Error fetching YouTube transcript: {e}")
        # Don't raise the exception, just log it - let the resource continue processing
        # Some videos might not have transcripts available
        resource.transcript = f"Transcript not available: {str(e)}"

# ================================================
### AUDIO
# ================================================

def transcribe_audio(resource: LearningResource, db: Session = None):
    """
    Transcribe audio file using OpenAI GPT-4o-transcribe model.

    Args:
        resource: LearningResource with file_url containing S3 URL to audio file
        db: Database session (optional, for future use)

    Updates:
        resource.transcript: The transcribed text from the audio file
    """
    import boto3
    import tempfile
    import os
    from openai import OpenAI
    from app.settings import settings

    try:
        if not resource.file_url:
            raise ValueError("No audio file URL provided in resource.file_url")

        logger.info(f"Starting transcription for audio resource: {resource.file_url}")

        # Parse S3 URL to get bucket and key
        # Handle both s3:// and https:// URLs
        if resource.file_url.startswith('s3://'):
            # Remove s3:// prefix and split bucket/key
            s3_path = resource.file_url[5:]  # Remove 's3://'
            bucket_name, s3_key = s3_path.split('/', 1)
        elif resource.file_url.startswith('https://') and '.s3.' in resource.file_url:
            # Parse HTTPS S3 URL format: https://bucket-name.s3.region.amazonaws.com/key
            import re
            match = re.match(r'https://([^.]+)\.s3\.[^/]+\.amazonaws\.com/(.+)', resource.file_url)
            if match:
                bucket_name = match.group(1)
                s3_key = match.group(2)
            else:
                raise ValueError(f"Unable to parse S3 bucket and key from URL: {resource.file_url}")
        else:
            raise ValueError(f"Invalid S3 URL format: {resource.file_url}. Expected s3:// or https:// S3 URL.")

        logger.info(f"Downloading audio file from S3: bucket={bucket_name}, key={s3_key}")

        # Download file from S3 to temporary file
        s3_client = boto3.client('s3')

        # Create temporary file with appropriate extension
        file_extension = os.path.splitext(s3_key)[1]
        if not file_extension:
            file_extension = '.wav'  # Default to wav if no extension

        with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as temp_file:
            temp_file_path = temp_file.name

        try:
            # Download from S3
            s3_client.download_file(bucket_name, s3_key, temp_file_path)
            logger.info(f"Successfully downloaded audio file to: {temp_file_path}")

            # Initialize OpenAI client
            client = OpenAI()

            # Transcribe audio using GPT-4o-transcribe
            logger.info("Starting transcription with GPT-4o-transcribe...")

            with open(temp_file_path, "rb") as audio_file:
                transcript_response = client.audio.transcriptions.create(
                    model="gpt-4o-transcribe",  # GPT-4o-transcribe model
                    file=audio_file,
                    response_format="text"
                )

            # The response is the transcribed text
            transcribed_text = transcript_response.strip()

            if not transcribed_text:
                raise ValueError("Transcription returned empty text")

            # Save transcription to resource
            resource.transcript = transcribed_text

            logger.info(f"Audio transcription completed successfully. Length: {len(transcribed_text)} characters")

        finally:
            # Clean up temporary file
            try:
                os.unlink(temp_file_path)
                logger.info(f"Cleaned up temporary file: {temp_file_path}")
            except OSError as e:
                logger.warning(f"Failed to clean up temporary file {temp_file_path}: {e}")

    except Exception as e:
        logger.error(f"Error transcribing audio: {e}")
        # Don't raise the exception, just log it - let the resource continue processing
        # Some audio files might not be transcribable
        resource.transcript = f"Transcription failed: {str(e)}"

# ================================================
### PDF
# ================================================
def transcribe_pdf(resource: LearningResource, db: Session = None):
    """
    Transcribe PDF file using pdf2image to convert pages to images and pytesseract for OCR.

    Dependencies Required:
    - poppler-utils (for pdf2image)
    - tesseract-ocr (for pytesseract)

    Args:
        resource: LearningResource with file_url containing S3 URL to PDF file
        db: Database session (optional, for future use)

    Updates:
        resource.transcript: The extracted text from all PDF pages
    """
    import boto3
    import tempfile
    import os
    from app.settings import settings

    try:
        # Check dependencies first
        try:
            from pdf2image import convert_from_path
        except ImportError as e:
            logger.error(f"pdf2image not installed: {e}")
            resource.transcript = "PDF processing unavailable: pdf2image library not installed. Please install pdf2image and poppler-utils."
            return

        try:
            import pytesseract
        except ImportError as e:
            logger.error(f"pytesseract not installed: {e}")
            resource.transcript = "PDF processing unavailable: pytesseract library not installed. Please install pytesseract and tesseract-ocr."
            return

        if not resource.file_url:
            raise ValueError("No PDF file URL provided in resource.file_url")

        logger.info(f"Starting PDF transcription for resource: {resource.file_url}")

        # Parse S3 URL to get bucket and key
        # Handle both s3:// and https:// URLs
        if resource.file_url.startswith('s3://'):
            # Remove s3:// prefix and split bucket/key
            s3_path = resource.file_url[5:]  # Remove 's3://'
            bucket_name, s3_key = s3_path.split('/', 1)
        elif resource.file_url.startswith('https://') and '.s3.' in resource.file_url:
            # Parse HTTPS S3 URL format: https://bucket-name.s3.region.amazonaws.com/key
            import re
            match = re.match(r'https://([^.]+)\.s3\.[^/]+\.amazonaws\.com/(.+)', resource.file_url)
            if match:
                bucket_name = match.group(1)
                s3_key = match.group(2)
            else:
                raise ValueError(f"Unable to parse S3 bucket and key from URL: {resource.file_url}")
        else:
            raise ValueError(f"Invalid S3 URL format: {resource.file_url}. Expected s3:// or https:// S3 URL.")

        logger.info(f"Downloading PDF file from S3: bucket={bucket_name}, key={s3_key}")

        # Download file from S3 to temporary file
        s3_client = boto3.client('s3')

        # Create temporary file with .pdf extension
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
            temp_pdf_path = temp_file.name

        try:
            # Download from S3
            s3_client.download_file(bucket_name, s3_key, temp_pdf_path)
            logger.info(f"Successfully downloaded PDF file to: {temp_pdf_path}")

            # Convert PDF pages to images with better error handling
            try:
                logger.info("Converting PDF pages to images...")
                images = convert_from_path(temp_pdf_path, dpi=200, fmt='jpeg')
                logger.info(f"Converted PDF to {len(images)} images")
            except Exception as pdf_error:
                error_msg = str(pdf_error).lower()
                if "poppler" in error_msg or "unable to get page count" in error_msg:
                    logger.error(f"Poppler dependency missing: {pdf_error}")
                    resource.transcript = "PDF processing failed: Poppler utilities not installed. Please install poppler-utils on the server."
                    return
                else:
                    raise pdf_error

            # Extract text from each page using OCR
            extracted_text_pages = []
            for i, image in enumerate(images):
                try:
                    logger.info(f"Processing page {i + 1}/{len(images)} with OCR...")

                    # Use pytesseract to extract text from image
                    page_text = pytesseract.image_to_string(image, lang='eng')

                    if page_text.strip():
                        extracted_text_pages.append(f"--- Page {i + 1} ---\n{page_text.strip()}")
                        logger.info(f"Extracted {len(page_text.strip())} characters from page {i + 1}")
                    else:
                        logger.warning(f"No text found on page {i + 1}")

                except Exception as ocr_error:
                    error_msg = str(ocr_error).lower()
                    if "tesseract" in error_msg or "not installed" in error_msg:
                        logger.error(f"Tesseract OCR dependency missing: {ocr_error}")
                        resource.transcript = "PDF processing failed: Tesseract OCR not installed. Please install tesseract-ocr on the server."
                        return
                    else:
                        logger.warning(f"OCR failed on page {i + 1}: {ocr_error}")
                        continue

            # Combine all pages into single transcript
            if extracted_text_pages:
                full_transcript = "\n\n".join(extracted_text_pages)
                resource.transcript = full_transcript
                logger.info(f"PDF transcription completed successfully. Total length: {len(full_transcript)} characters across {len(extracted_text_pages)} pages")
            else:
                resource.transcript = "No text could be extracted from this PDF file. The document may contain only images or be password protected."
                logger.warning("No text was extracted from any pages in the PDF")

        finally:
            # Clean up temporary PDF file
            try:
                os.unlink(temp_pdf_path)
                logger.info(f"Cleaned up temporary PDF file: {temp_pdf_path}")
            except OSError as e:
                logger.warning(f"Failed to clean up temporary PDF file {temp_pdf_path}: {e}")

    except Exception as e:
        logger.error(f"Error transcribing PDF: {e}")
        # Don't raise the exception, just log it - let the resource continue processing
        if "poppler" in str(e).lower():
            resource.transcript = "PDF processing failed: System dependencies missing. Please ensure poppler-utils and tesseract-ocr are installed on the server."
        else:
            resource.transcript = f"PDF transcription failed: {str(e)}"

# ================================================
### TEXT
# ================================================
def transcribe_text(resource: LearningResource, db: Session = None):
    """
    For text resources, the text content is already provided as summary_notes
    and should be used directly as the transcript.

    Args:
        resource: LearningResource with summary_notes containing the text content
        db: Database session (optional, for future use)

    Updates:
        resource.transcript: The text content from summary_notes
    """
    try:
        if not resource.summary_notes or resource.summary_notes.strip() == "":
            logger.warning(f"No text content available for resource {resource.id}")
            resource.transcript = "No text content provided"
            return

        logger.info(f"Processing text content for resource {resource.id}")

        # For text resources, use the summary_notes as the transcript
        resource.transcript = resource.summary_notes.strip()

        logger.info(f"Text processing completed for resource {resource.id}. Length: {len(resource.transcript)} characters")

    except Exception as e:
        logger.error(f"Error processing text content: {e}")
        resource.transcript = f"Text processing failed: {str(e)}"



RESOURCE_TYPE_TO_TRANSCRIBE_FUNCTION = {
    LearningResourceFileType.YOUTUBE_LINK: transcribe_youtube_link,
    LearningResourceFileType.PDF: transcribe_pdf,
    LearningResourceFileType.AUDIO: transcribe_audio,
    LearningResourceFileType.TEXT: transcribe_text,
}