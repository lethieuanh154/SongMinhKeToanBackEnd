"""
Firebase Admin SDK Configuration
"""
import firebase_admin
from firebase_admin import credentials, firestore
import os
import json
from .settings import settings

db = None


def initialize_firebase():
    """Initialize Firebase Admin SDK"""
    global db

    if firebase_admin._apps:
        # Already initialized
        db = firestore.client()
        return db

    try:
        cred = None

        # Priority 1: Load from FIREBASE_SERVICE_ACCOUNT env var (JSON string)
        if settings.firebase_service_account:
            try:
                service_account_info = json.loads(settings.firebase_service_account)
                cred = credentials.Certificate(service_account_info)
                print("✅ Firebase initialized from FIREBASE_SERVICE_ACCOUNT env variable")
            except json.JSONDecodeError as e:
                print(f"⚠️ Invalid JSON in FIREBASE_SERVICE_ACCOUNT: {e}")

        # Priority 2: Load from service account file
        if cred is None:
            service_account_path = settings.firebase_service_account_path
            if os.path.exists(service_account_path):
                cred = credentials.Certificate(service_account_path)
                print(f"✅ Firebase initialized from service account file: {service_account_path}")

        # Priority 3: Initialize with project ID only (for environments with default credentials)
        if cred is None:
            firebase_admin.initialize_app(options={
                'projectId': settings.firebase_project_id
            })
            print(f"✅ Firebase initialized with project ID: {settings.firebase_project_id}")
        else:
            firebase_admin.initialize_app(cred)

        db = firestore.client()
        return db

    except Exception as e:
        print(f"❌ Firebase initialization error: {e}")
        raise e


def get_db():
    """Get Firestore database client"""
    global db
    if db is None:
        initialize_firebase()
    return db
