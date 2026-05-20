"""
Firebase Admin SDK Configuration
"""
import firebase_admin
from firebase_admin import credentials, firestore
import os
import json
from .settings import settings

db = None
supplies_db = None
gmail_db = None


def initialize_firebase():
    """Initialize Firebase Admin SDK"""
    global db

    if firebase_admin._apps.get('[DEFAULT]'):
        db = firestore.client()
        return db

    try:
        cred = None

        # Priority 1: Load from FIREBASE_SERVICE_ACCOUNT env var (JSON string)
        if settings.firebase_service_account_ketoan:
            try:
                service_account_info = json.loads(settings.firebase_service_account_ketoan)
                cred = credentials.Certificate(service_account_info)
                print("✅ Firebase initialized from FIREBASE_SERVICE_ACCOUNT env variable")
            except json.JSONDecodeError as e:
                print(f"⚠️ Invalid JSON in FIREBASE_SERVICE_ACCOUNT: {e}")

        # Priority 2: Load from service account file
        if cred is None:
            service_account_path = settings.firebase_service_account_ketoan_path
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


def initialize_supplies_firebase():
    """Initialize Firebase Admin SDK for taphoa39-supplies-invoices project"""
    global supplies_db

    app_name = 'supplies-invoices'

    if firebase_admin._apps.get(app_name):
        supplies_db = firestore.client(firebase_admin.get_app(app_name))
        return supplies_db

    try:
        cred = None

        # Priority 1: Load from env var (JSON string)
        if settings.firebase_service_account_supplies_invoices:
            try:
                service_account_info = json.loads(settings.firebase_service_account_supplies_invoices)
                cred = credentials.Certificate(service_account_info)
                print("✅ Supplies Firebase initialized from env variable")
            except json.JSONDecodeError as e:
                print(f"⚠️ Invalid JSON in FIREBASE_SERVICE_ACCOUNT_SUPPLIES_INVOICES: {e}")

        # Priority 2: Load from service account file
        if cred is None:
            service_account_path = settings.firebase_service_account_supplies_invoices_path
            if os.path.exists(service_account_path):
                cred = credentials.Certificate(service_account_path)
                print(f"✅ Supplies Firebase initialized from file: {service_account_path}")

        # Priority 3: Initialize with project ID only
        if cred is None:
            app = firebase_admin.initialize_app(
                options={'projectId': settings.firebase_supplies_invoices_project_id},
                name=app_name
            )
            print(f"✅ Supplies Firebase initialized with project ID: {settings.firebase_supplies_invoices_project_id}")
        else:
            app = firebase_admin.initialize_app(cred, name=app_name)

        supplies_db = firestore.client(app)
        return supplies_db

    except Exception as e:
        print(f"❌ Supplies Firebase initialization error: {e}")
        raise e


def get_db():
    """Get Firestore database client (songminhketoan)"""
    global db
    if db is None:
        initialize_firebase()
    return db


def get_supplies_db():
    """Get Firestore database client (taphoa39-supplies-invoices)"""
    global supplies_db
    if supplies_db is None:
        initialize_supplies_firebase()
    return supplies_db


def initialize_gmail_firebase():
    """Initialize Firebase Admin SDK for quanlysongminh (Gmail OAuth tokens) project"""
    global gmail_db

    app_name = 'gmail-app'

    if firebase_admin._apps.get(app_name):
        gmail_db = firestore.client(firebase_admin.get_app(app_name))
        return gmail_db

    try:
        cred = None

        if settings.firebase_service_account_gmail:
            try:
                service_account_info = json.loads(settings.firebase_service_account_gmail)
                cred = credentials.Certificate(service_account_info)
                print("✅ Gmail Firebase initialized from env variable")
            except json.JSONDecodeError as e:
                print(f"⚠️ Invalid JSON in FIREBASE_SERVICE_ACCOUNT_GMAIL: {e}")

        if cred is None:
            service_account_path = settings.firebase_service_account_gmail_path
            if os.path.exists(service_account_path):
                cred = credentials.Certificate(service_account_path)
                print(f"✅ Gmail Firebase initialized from file: {service_account_path}")

        if cred is None:
            app = firebase_admin.initialize_app(
                options={'projectId': settings.firebase_gmail_project_id},
                name=app_name
            )
            print(f"✅ Gmail Firebase initialized with project ID: {settings.firebase_gmail_project_id}")
        else:
            app = firebase_admin.initialize_app(cred, name=app_name)

        gmail_db = firestore.client(app)
        return gmail_db

    except Exception as e:
        print(f"❌ Gmail Firebase initialization error: {e}")
        raise e


def get_gmail_db():
    """Get Firestore database client (quanlysongminh - Gmail tokens)"""
    global gmail_db
    if gmail_db is None:
        initialize_gmail_firebase()
    return gmail_db
