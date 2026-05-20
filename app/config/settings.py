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

    # Server (local: 127.0.0.1:5000, Render sets HOST=0.0.0.0 PORT=10000)
    host: str = "127.0.0.1"
    port: int = 5000

    # CORS
    cors_origins: str = "http://localhost:4200,http://127.0.0.1:4200"

    # Firebase - có thể dùng JSON string hoặc file path
    firebase_service_account_ketoan: Optional[str] = None  # JSON string từ .env
    firebase_service_account_ketoan_path: str = "./firebase-service-account.json"
    firebase_project_id: str = "songminhketoan-15041989"

    # Firebase - Supplies Invoices project (shared với TapHoa39BanHang)
    firebase_service_account_supplies_invoices: Optional[str] = None  # JSON string từ .env
    firebase_service_account_supplies_invoices_path: str = "./firebase-supplies-invoices-service-account.json"
    firebase_supplies_invoices_project_id: str = "taphoa39-supplies-invoices"

    # Firebase - Gmail / QuanLySongMinh project (stores Gmail OAuth tokens)
    firebase_service_account_gmail: Optional[str] = None  # JSON string từ .env
    firebase_service_account_gmail_path: str = "./firebase-gmail-service-account.json"
    firebase_gmail_project_id: str = "quanlysongminh"

    # Gmail UID - Firebase UID của tài khoản Gmail công ty (set một lần trong .env)
    gmail_uid: str = ""

    # Google OAuth (for Gmail token refresh)
    google_client_id: str = ""
    google_client_secret: str = ""

    @property
    def cors_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.cors_origins.split(",")]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
