from pydantic import BaseModel
from app.learning.models import LearningResource, MultipleChoiceQuestion
from app.database import get_db
from sqlalchemy.orm import Session
from openai import OpenAI
from typing import List
import logging
import json


logger = logging.getLogger(__name__)

QUIZ_GENERATION_PROMPT = """
You are a helpful tutor creating multiple choice quiz questions for a student to help them test their understanding of the material.

You will be given text content (transcript, notes, or document content) and should generate multiple choice questions based on the key concepts, facts, and important information presented.

Each question should have:
- A clear, specific question
- 4 multiple choice options (A, B, C, D)
- Only one correct answer
- Plausible distractors (incorrect options that seem reasonable)

Generate questions that test:
- Key concepts and definitions
- Important facts and figures
- Cause and effect relationships
- Applications and examples
- Analysis and critical thinking

Return your response as a JSON array of question objects, where each object has "question", "options", and "correct_option" fields.
The "options" field should be an array of 4 strings (the answer choices).
The "correct_option" field should be the exact text of the correct answer (not just A, B, C, or D).

Example format:
[
  {
    "question": "What is the main concept discussed in the material?",
    "options": [
      "Option A description",
      "Option B description", 
      "Option C description",
      "Option D description"
    ],
    "correct_option": "Option B description"
  }
]

Generate 8-12 high-quality multiple choice questions based on the content. Focus on the most important and testable information.
"""


def generate_quiz_questions(resource_id: int):
    """
    Generate multiple choice quiz questions for a learning resource using OpenAI GPT.
    
    Args:
        resource_id: ID of the resource to generate quiz questions for
    """
    # Create database session for background task
    db = next(get_db())
    
    try:
        resource = db.query(LearningResource).filter(LearningResource.id == resource_id).first()
        if not resource:
            raise Exception(f"Resource not found: {resource_id}")

        logger.info(f"Generating quiz questions for resource {resource_id}")

        # Check if resource has content to work with
        if not resource.transcript or resource.transcript.strip() == "":
            logger.warning(f"No transcript available for resource {resource_id}, cannot generate quiz questions")
            return

        # Initialize OpenAI client
        client = OpenAI()
        
        # Generate quiz questions using GPT
        response = client.chat.completions.create(
            model="gpt-5",
            messages=[
                {
                    "role": "system",
                    "content": QUIZ_GENERATION_PROMPT
                },
                {
                    "role": "user", 
                    "content": resource.transcript
                }
            ],
            max_completion_tokens=3000,
        )
        
        # Parse the JSON response
        generated_content = response.choices[0].message.content.strip()
        
        try:
            # Remove any markdown code block formatting if present
            if generated_content.startswith('```json'):
                generated_content = generated_content[7:-3]
            elif generated_content.startswith('```'):
                generated_content = generated_content[3:-3]
            
            quiz_questions_data = json.loads(generated_content)
            
            if not isinstance(quiz_questions_data, list):
                raise ValueError("Expected a list of quiz questions")
            
            # Create quiz questions in the database
            created_count = 0
            for question_data in quiz_questions_data:
                if not isinstance(question_data, dict) or 'question' not in question_data or 'options' not in question_data or 'correct_option' not in question_data:
                    logger.warning(f"Skipping invalid quiz question data: {question_data}")
                    continue
                
                # Validate that options is a list and correct_option is in options
                options = question_data['options']
                correct_option = question_data['correct_option']
                
                if not isinstance(options, list) or len(options) != 4:
                    logger.warning(f"Skipping question with invalid options: {question_data}")
                    continue
                
                if correct_option not in options:
                    logger.warning(f"Skipping question where correct_option is not in options: {question_data}")
                    continue
                
                # Convert options list to newline-separated string for database storage
                options_string = "\n".join(options)
                
                quiz_question = MultipleChoiceQuestion(
                    user_id=resource.user_id,
                    resource_id=resource.id,
                    question=question_data['question'].strip(),
                    options=options_string,
                    correct_option=correct_option.strip()
                )
                
                db.add(quiz_question)
                created_count += 1
            
            db.commit()
            logger.info(f"Generated {created_count} quiz questions for resource {resource_id}")
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response for quiz questions: {e}")
            logger.error(f"Response content: {generated_content}")
        except Exception as e:
            logger.error(f"Failed to create quiz questions in database: {e}")
            db.rollback()
            
    except Exception as e:
        logger.error(f"Failed to generate quiz questions for resource {resource_id}: {e}")
        raise e
        
    finally:
        db.close()