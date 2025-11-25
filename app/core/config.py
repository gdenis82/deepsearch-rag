
import logging
import os
from typing import List, Optional

from dotenv import load_dotenv, find_dotenv
from pydantic import AnyHttpUrl, PostgresDsn
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)
load_dotenv(find_dotenv())

class Settings(BaseSettings):
    ENVIRONMENT: str
    PROJECT_NAME: str = "SmartTask FAQ"
    API_V1_STR: str = "/api/v1"

    # Security settings
    SECRET_KEY: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int
    ALGORITHM: str

    # CORS settings
    BACKEND_CORS_ORIGINS: List[AnyHttpUrl] = ["http://localhost:8000",
                                              "http://127.0.0.1:8000", ]


    POSTGRES_HOST: str = os.getenv('POSTGRES_HOST', 'localhost')
    POSTGRES_USER: str = os.getenv('POSTGRES_USER', 'faquser')
    POSTGRES_PASSWORD: str = os.getenv('POSTGRES_PASSWORD', 'faqpass')
    POSTGRES_DB: str = os.getenv('POSTGRES_DB', 'faqdb')
    POSTGRES_PORT: int = os.getenv('POSTGRES_PORT', 5432)
    DATABASE_URL: Optional[PostgresDsn] = None

    def __init__(self, **kwargs):

        # Call the parent class constructor
        super().__init__(**kwargs)

        # If in development and a local DB URL is provided, prefer it
        if (self.ENVIRONMENT or '').lower() == 'development':
            logger.info("Using development (backend running locally)")
            self.POSTGRES_HOST = 'localhost'

        self.DATABASE_URL = (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )



# Initialize settings with logging
try:
    settings = Settings()
    logger.info("Settings loaded successfully")
except Exception as e:
    logger.error(f"Error loading settings: {e}")
    raise