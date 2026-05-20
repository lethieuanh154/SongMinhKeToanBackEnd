"""
Gmail API Service.
Reads Gmail tokens from Firestore (quanlysongminh project / users/{uid}).
"""
import re
import base64
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

from google.oauth2.credentials import Credentials
from google.auth.exceptions import RefreshError
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.config.settings import settings

logger = logging.getLogger(__name__)


class GmailTokenExpiredError(Exception):
    """Raised when Gmail access token is expired and cannot be refreshed."""
    pass


class GmailService:
    SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

    def __init__(self, access_token: str, refresh_token: Optional[str] = None):
        self.credentials = Credentials(
            token=access_token,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
            scopes=self.SCOPES,
        )
        self.service = build('gmail', 'v1', credentials=self.credentials)
        self._uid: Optional[str] = None
        self._db = None
        self._original_token = access_token

    def list_labels(self) -> List[Dict[str, Any]]:
        """List user-created Gmail labels."""
        try:
            response = self.service.users().labels().list(userId='me').execute()
            labels = response.get('labels', [])
            user_labels = [
                {'id': l.get('id'), 'name': l.get('name'), 'type': l.get('type')}
                for l in labels if l.get('type') == 'user'
            ]
            user_labels.sort(key=lambda x: x['name'].lower())
            return user_labels
        except RefreshError as e:
            raise GmailTokenExpiredError(f"Gmail token hết hạn. Vui lòng đăng nhập lại. ({e})")
        except Exception as e:
            raise e

    def list_messages(
        self,
        days_back: int = 7,
        max_results: int = 50,
        query: Optional[str] = None,
        label_ids: Optional[List[str]] = None
    ) -> List[Dict[str, str]]:
        """List message stubs from Gmail with optional label and date filters."""
        after_date = datetime.now() - timedelta(days=days_back)
        full_query = f"after:{after_date.strftime('%Y/%m/%d')}"
        if query:
            full_query = f"{full_query} {query}"

        messages = []
        page_token = None

        try:
            while len(messages) < max_results:
                params = {
                    'userId': 'me',
                    'q': full_query,
                    'maxResults': min(max_results - len(messages), 100),
                }
                if page_token:
                    params['pageToken'] = page_token
                if label_ids:
                    params['labelIds'] = label_ids

                response = self.service.users().messages().list(**params).execute()
                if 'messages' in response:
                    messages.extend(response['messages'])

                page_token = response.get('nextPageToken')
                if not page_token:
                    break
        except RefreshError as error:
            raise GmailTokenExpiredError(f"Gmail token hết hạn. Vui lòng đăng nhập lại. ({error})")
        except HttpError as error:
            if error.resp.status == 401:
                raise GmailTokenExpiredError("Gmail token hết hạn. Vui lòng đăng nhập lại.")
            logger.error(f"Gmail API error listing messages: {error}")
            raise

        return messages[:max_results]

    def get_message_full(self, message_id: str) -> Optional[Dict[str, Any]]:
        """Get full message (headers + body) in a single API call.
        Returns dict with metadata fields + 'bodyHtml' field."""
        try:
            message = self.service.users().messages().get(
                userId='me', id=message_id, format='full'
            ).execute()

            headers = {h['name']: h['value'] for h in message.get('payload', {}).get('headers', [])}
            from_raw = headers.get('From', '')
            from_email = self._extract_email(from_raw)

            payload = message.get('payload', {})
            body_html = self._extract_body_html(payload)

            return {
                'gmail_id': message_id,
                'thread_id': message.get('threadId', message_id),
                'from_address': from_email,
                'from_name': self._extract_from_name(from_raw),
                'from_domain': self._extract_domain(from_email),
                'subject': headers.get('Subject', ''),
                'date': self._parse_date(headers.get('Date', '')).isoformat(),
                'snippet': message.get('snippet', ''),
                'internal_date': int(message.get('internalDate', 0)),
                'bodyHtml': body_html,
                'attachments': self._extract_attachments(message),
            }
        except RefreshError as error:
            raise GmailTokenExpiredError(f"Gmail token hết hạn. ({error})")
        except HttpError as error:
            if error.resp.status == 401:
                raise GmailTokenExpiredError("Gmail token hết hạn. Vui lòng đăng nhập lại.")
            logger.error(f"Error fetching message {message_id}: {error}")
            return None

    def _extract_body_html(self, payload: Dict) -> Optional[str]:
        """Recursively extract HTML body from email payload."""
        mime_type = payload.get('mimeType', '')

        # Direct HTML body
        if mime_type == 'text/html':
            data = payload.get('body', {}).get('data', '')
            if data:
                return base64.urlsafe_b64decode(data).decode('utf-8', errors='replace')

        # Multipart: search parts recursively
        parts = payload.get('parts', [])
        for part in parts:
            part_mime = part.get('mimeType', '')
            if part_mime == 'text/html':
                data = part.get('body', {}).get('data', '')
                if data:
                    return base64.urlsafe_b64decode(data).decode('utf-8', errors='replace')
            if 'parts' in part:
                result = self._extract_body_html(part)
                if result:
                    return result

        # Fallback: plain text
        for part in parts:
            if part.get('mimeType') == 'text/plain':
                data = part.get('body', {}).get('data', '')
                if data:
                    return base64.urlsafe_b64decode(data).decode('utf-8', errors='replace')

        return None

    def _extract_attachments(self, message: Dict) -> List[str]:
        """Extract attachment filenames from message."""
        filenames = []

        def extract(parts):
            for part in parts:
                fn = part.get('filename', '')
                if fn:
                    filenames.append(fn)
                if 'parts' in part:
                    extract(part['parts'])

        payload = message.get('payload', {})
        if 'parts' in payload:
            extract(payload['parts'])
        return filenames

    # --- helpers ---

    def _extract_email(self, from_header: str) -> str:
        match = re.search(r'<([^>]+)>', from_header)
        if match:
            return match.group(1).lower()
        match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', from_header)
        return match.group(0).lower() if match else from_header.lower()

    def _extract_from_name(self, from_header: str) -> str:
        """Extract display name from 'Name <email>' format."""
        match = re.match(r'^"?([^"<]+)"?\s*<', from_header)
        return match.group(1).strip() if match else from_header.split('@')[0]

    def _extract_domain(self, email: str) -> str:
        parts = email.split('@')
        return parts[1] if len(parts) > 1 else ''

    def _parse_date(self, date_str: str) -> datetime:
        from email.utils import parsedate_to_datetime
        try:
            return parsedate_to_datetime(date_str)
        except Exception:
            return datetime.now()
