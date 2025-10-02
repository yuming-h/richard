from pydantic import BaseModel
from app.learning.models import LearningResource, FlashCard
from app.database import get_db
from sqlalchemy.orm import Session
from openai import OpenAI
from typing import List
import logging
import json


logger = logging.getLogger(__name__)

FLASH_CARD_GENERATION_PROMPT = """
You are a helpful tutor creating flash cards for a student to help them learn and review material.

You will be given text content (transcript, notes, or document content) and should generate flash cards based on the key concepts, facts, and important information presented.

Each flash card should have:
- A clear, concise question or prompt on the front
- A comprehensive but focused answer on the back

Generate flash cards that test understanding of:
- Key concepts and definitions
- Important facts and figures
- Cause and effect relationships
- Examples and applications
- Critical thinking about the material

Return your response as a JSON array of flash card objects, where each object has "front" and "back" fields.
Example format:
[
  {
    "front": "What is the main concept discussed in the material?",
    "back": "The main concept is..."
  },
  {
    "front": "Define [key term]",
    "back": "[Definition and explanation]"
  }
]

Generate 8-12 high-quality flash cards based on the content. Focus on the most important and testable information.
"""


def generate_flash_cards(resource_id: int):
    """
    Generate flash cards for a learning resource using OpenAI GPT.
    
    Args:
        resource_id: ID of the resource to generate flash cards for
    """
    # Create database session for background task
    db = next(get_db())
    
    try:
        resource = db.query(LearningResource).filter(LearningResource.id == resource_id).first()
        if not resource:
            raise Exception(f"Resource not found: {resource_id}")

        logger.info(f"Generating flash cards for resource {resource_id}")

        # Check if resource has content to work with
        if not resource.transcript or resource.transcript.strip() == "":
            logger.warning(f"No transcript available for resource {resource_id}, cannot generate flash cards")
            return

        # Initialize OpenAI client
        client = OpenAI()
        
        # Generate flash cards using GPT
        response = client.chat.completions.create(
            model="gpt-5",
            messages=[
                {
                    "role": "system",
                    "content": FLASH_CARD_GENERATION_PROMPT
                },
                {
                    "role": "user", 
                    "content": resource.transcript
                }
            ],
        )
        
        # Parse the JSON response
        generated_content = response.choices[0].message.content.strip()
        
        try:
            # Remove any markdown code block formatting if present
            if generated_content.startswith('```json'):
                generated_content = generated_content[7:-3]
            elif generated_content.startswith('```'):
                generated_content = generated_content[3:-3]
            
            flash_cards_data = json.loads(generated_content)
            
            if not isinstance(flash_cards_data, list):
                raise ValueError("Expected a list of flash cards")
            
            # Create flash cards in the database
            created_count = 0
            for card_data in flash_cards_data:
                if not isinstance(card_data, dict) or 'front' not in card_data or 'back' not in card_data:
                    logger.warning(f"Skipping invalid flash card data: {card_data}")
                    continue
                
                flash_card = FlashCard(
                    user_id=resource.user_id,
                    resource_id=resource.id,
                    front=card_data['front'].strip(),
                    back=card_data['back'].strip()
                )
                
                db.add(flash_card)
                created_count += 1
            
            db.commit()
            logger.info(f"Generated {created_count} flash cards for resource {resource_id}")
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response for flash cards: {e}")
            logger.error(f"Response content: {generated_content}")
        except Exception as e:
            logger.error(f"Failed to create flash cards in database: {e}")
            db.rollback()
            
    except Exception as e:
        logger.error(f"Failed to generate flash cards for resource {resource_id}: {e}")
        raise e
        
    finally:
        db.close()