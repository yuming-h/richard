from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.settings import settings
from sqlalchemy.pool import QueuePool

# Create SQLAlchemy engine
engine = create_engine(
    settings.database_url,
    poolclass=QueuePool,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,  # Validates connections before use
    pool_recycle=300,  # Recycle connections every 5 minutes
    connect_args=(
        {
            "options": "-c timezone=utc",
            "sslmode": "require" if "sslmode" not in settings.database_url else None,
        }
        if settings.database_url and "postgresql" in settings.database_url
        else {}
    ),
)

# Create SessionLocal class
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create Base class for models
Base = declarative_base()


# Dependency to get database session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
