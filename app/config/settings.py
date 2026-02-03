"""
Application Settings
"""
from pydantic_settings import BaseSettings
from typing import List, Optional
import os


class Settings(BaseSettings):
    # App info
    app_name: str = "TapHoa39KeToan API"
    app_version: str = "1.0.0"
    debug: bool = True

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # CORS
    cors_origins: str = "http://localhost:4200,http://127.0.0.1:4200"

    # Firebase - có thể dùng JSON string hoặc file path
    firebase_service_account: Optional[str] = None  # JSON string từ .env
    firebase_service_account_path: str = "./firebase-service-account.json"
    firebase_project_id: str = "songminhketoan-15041989"

    @property
    def cors_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.cors_origins.split(",")]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
