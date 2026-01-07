from app.database import Base
from enum import Enum as PyEnum
from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Enum
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship, deferred


class LearningResourceFileType(str, PyEnum):
    PDF = "pdf"
    YOUTUBE_LINK = "youtube_link"
    AUDIO = "audio"
    TEXT = "text"
    IMAGE = "image"


class ResourceStatus(str, PyEnum):
    PROCESSING = "processing"
    TRANSCRIBING = "transcribing"
    SUMMARIZING = "summarizing"
    COMPLETED = "completed"
    FAILED = "failed"


class ResourceFolder(Base):
    __tablename__ = "resource_folders"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    name = Column(String)
    parent_folder_id = Column(Integer, ForeignKey("resource_folders.id"), nullable=True)
    created_at = Column(DateTime(timezone=False), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=False), server_default=func.now(), onupdate=func.now()
    )

    resources = relationship("LearningResource", back_populates="folder")
    subfolders = relationship("ResourceFolder", back_populates="parent_folder")
    parent_folder = relationship(
        "ResourceFolder", back_populates="subfolders", remote_side=[id]
    )


class LearningResource(Base):
    __tablename__ = "learning_resources"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    title = Column(String, nullable=True)
    transcript = deferred(Column(String, nullable=True)) # deferred to avoid loading the transcript into memory
    summary_notes = Column(String, nullable=True)
    resource_type = Column(String)
    folder_id = Column(Integer, ForeignKey("resource_folders.id"))
    file_url = Column(String, nullable=True)
    status = Column(String, default=ResourceStatus.PROCESSING.value)
    created_at = Column(DateTime(timezone=False), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=False), server_default=func.now(), onupdate=func.now()
    )

    folder = relationship("ResourceFolder", back_populates="resources", uselist=False)
    flash_cards = relationship("FlashCard", back_populates="resource")


class FlashCard(Base):
    __tablename__ = "flash_cards"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    resource_id = Column(Integer, ForeignKey("learning_resources.id"))
    front = Column(String)
    back = Column(String)
    created_at = Column(DateTime(timezone=False), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=False), server_default=func.now(), onupdate=func.now()
    )

    resource = relationship("LearningResource", back_populates="flash_cards")


class MultipleChoiceQuestion(Base):
    __tablename__ = "multiple_choice_questions"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    resource_id = Column(Integer, ForeignKey("learning_resources.id"))
    question = Column(String)
    options = Column(String)  # newline separated list of options
    correct_option = Column(String)
    created_at = Column(DateTime(timezone=False), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=False), server_default=func.now(), onupdate=func.now()
    )


class LearningResourceImage(Base):
    __tablename__ = "learning_resource_images"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    resource_id = Column(Integer, ForeignKey("learning_resources.id"))
    image_url = Column(String)
    created_at = Column(DateTime(timezone=False), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=False), server_default=func.now(), onupdate=func.now()
    )