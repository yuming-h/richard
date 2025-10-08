from pydantic import Field
from pydantic_settings import BaseSettings
import os
from dotenv import load_dotenv

env_file = ".env.prod" if os.getenv("RICHARD_ENV") == "production" else ".env.dev"
load_dotenv(env_file)


class Settings(BaseSettings):
    database_url: str = Field(alias="RICHARD_DATABASE_URL")
    jwt_secret_key: str = Field(alias="RICHARD_JWT_SECRET_KEY")

    # S3
    files_s3_bucket_name: str = Field(alias="RICHARD_FILES_S3_BUCKET_NAME")

    webshare_proxy_username: str = "qdudxsmf"
    webshare_proxy_password: str = "5dov6jz6k5mf"


settings = Settings()
