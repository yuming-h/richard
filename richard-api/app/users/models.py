from app.database import Base
from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey
from sqlalchemy.sql import func


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    first_name = Column(String)
    last_name = Column(String)
    google_sub = Column(String, unique=True, index=True)
    apple_sub = Column(String, unique=True, index=True)
    profile_picture_url = Column(String)
    root_folder_id = Column(Integer, ForeignKey("resource_folders.id"))
    resource_count = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=False), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=False), server_default=func.now(), onupdate=func.now()
    )
