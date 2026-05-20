"""
Gmail API routes for KeToanBackEnd.
GET /api/gmail/auth/url      — Redirect popup to Google OAuth (no uid needed)
GET /api/gmail/auth/callback — OAuth callback, saves tokens, postMessage uid+email
GET /api/gmail/labels        — List Gmail labels for a uid
GET /api/gmail/portal-links  — Fetch emails from Gmail, parse portal URLs
"""
import re
import secrets
import logging
from typing import Optional

from fastapi import APIRouter, Query, HTTPException, Request
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
import httpx

from app.config.firebase import get_gmail_db
from app.config.settings import settings
from app.services.gmail_service import GmailService, GmailTokenExpiredError
from app.services.email_body_parser import EmailBodyParser

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/gmail", tags=["Gmail"])

_pending_states: dict = {}


def _get_gmail_service(uid: str) -> GmailService:
    db = get_gmail_db()
    user_doc = db.collection('users').document(uid).get()

    if not user_doc.exists:
        raise HTTPException(status_code=404, detail=f"User {uid} not found in Gmail Firestore")

    user_data = user_doc.to_dict()
    tokens = user_data.get('gmailTokens', {})
    access_token = tokens.get('accessToken', '')
    refresh_token = tokens.get('refreshToken')

    if not access_token and not refresh_token:
        raise HTTPException(status_code=409, detail=f"No Gmail tokens found for user {uid}. Please connect Gmail.")

    gmail = GmailService(access_token=access_token, refresh_token=refresh_token)
    gmail._uid = uid
    gmail._db = db
    gmail._original_token = access_token
    return gmail


def _save_refreshed_token(gmail: GmailService):
    if not gmail._uid or not gmail._db:
        return
    new_token = gmail.credentials.token
    if new_token and new_token != gmail._original_token:
        gmail._db.collection('users').document(gmail._uid).update({
            'gmailTokens.accessToken': new_token
        })


def _build_flow(redirect_uri: str):
    from google_auth_oauthlib.flow import Flow
    return Flow.from_client_config(
        {
            "web": {
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect_uri]
            }
        },
        scopes=[
            'https://www.googleapis.com/auth/gmail.readonly',
            'openid',
            'https://www.googleapis.com/auth/userinfo.email'
        ]
    )


@router.get("/auth/url")
async def get_auth_url(request: Request):
    """GET /api/gmail/auth/url — Redirects popup browser to Google OAuth consent screen."""
    if not settings.google_client_id or not settings.google_client_secret:
        return JSONResponse(status_code=500, content={
            "success": False, "error": "GOOGLE_CLIENT_ID/SECRET not configured in .env"
        })

    redirect_uri = str(request.base_url).rstrip('/') + "/api/gmail/auth/callback"
    flow = _build_flow(redirect_uri)
    flow.redirect_uri = redirect_uri

    state = secrets.token_urlsafe(16)
    _pending_states[state] = True

    auth_url, _ = flow.authorization_url(
        access_type='offline',
        prompt='consent',
        state=state
    )
    print(f"🔗 [Gmail OAuth] Redirecting to Google consent, redirect_uri={redirect_uri}")
    return RedirectResponse(auth_url)


@router.get("/auth/callback")
async def auth_callback(
    request: Request,
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None)
):
    """GET /api/gmail/auth/callback — Google redirects here after user consents.
    Saves tokens to Firestore, returns HTML that postMessages uid+email to opener."""

    def _error_html(msg: str) -> HTMLResponse:
        return HTMLResponse(f"""<!DOCTYPE html><html><body>
    <h3 style="font-family:sans-serif;color:red;text-align:center;margin-top:40px;">
        Loi: {msg}
    </h3>
    <script>setTimeout(() => window.close(), 3000);</script>
</body></html>""")

    if error:
        return _error_html(error)
    if not code:
        return _error_html("Missing authorization code")

    try:
        redirect_uri = str(request.base_url).rstrip('/') + "/api/gmail/auth/callback"
        flow = _build_flow(redirect_uri)
        flow.redirect_uri = redirect_uri
        flow.fetch_token(code=code)
        credentials = flow.credentials

        # Get user email from Google
        async with httpx.AsyncClient() as client:
            userinfo_resp = await client.get(
                'https://www.googleapis.com/oauth2/v1/userinfo',
                headers={'Authorization': f'Bearer {credentials.token}'}
            )
        userinfo = userinfo_resp.json()
        email = userinfo.get('email', '')
        print(f"✅ [Gmail OAuth] Received tokens for: {email}")

        # Find or create user doc in quanlysongminh Firestore by email
        db = get_gmail_db()
        users_ref = db.collection('users')
        existing = list(users_ref.where('email', '==', email).limit(1).get())

        update_data: dict = {'gmailTokens.accessToken': credentials.token}
        if credentials.refresh_token:
            update_data['gmailTokens.refreshToken'] = credentials.refresh_token

        if existing:
            uid = existing[0].id
            users_ref.document(uid).update(update_data)
            print(f"✅ [Gmail OAuth] Updated uid={uid} email={email}")
        else:
            new_ref = users_ref.document()
            uid = new_ref.id
            new_ref.set({
                'email': email,
                'gmailTokens': {
                    'accessToken': credentials.token,
                    'refreshToken': credentials.refresh_token or ''
                }
            })
            print(f"✅ [Gmail OAuth] Created uid={uid} email={email}")

        return HTMLResponse(f"""<!DOCTYPE html><html><body>
    <h3 style="font-family:sans-serif;color:#4CAF50;text-align:center;margin-top:40px;">
        Da ket noi: {email}
    </h3>
    <script>
        if (window.opener) {{
            window.opener.postMessage({{ type: 'GMAIL_AUTH_SUCCESS', uid: '{uid}', email: '{email}' }}, '*');
        }}
        setTimeout(() => window.close(), 1500);
    </script>
</body></html>""")

    except Exception as e:
        print(f"❌ [Gmail OAuth] Callback error: {type(e).__name__}: {e}")
        return _error_html(str(e))


@router.get("/labels")
async def get_labels(uid: Optional[str] = Query(None, description="Firebase user UID")):
    """GET /api/gmail/labels — List Gmail labels. uid optional, falls back to GMAIL_UID in .env."""
    effective_uid = uid or settings.gmail_uid
    if not effective_uid:
        return JSONResponse(status_code=400, content={
            "success": False, "error": "uid is required. Connect Gmail first or set GMAIL_UID in .env"
        })
    print(f"🏷️ [Gmail] get_labels uid={effective_uid}")
    try:
        gmail = _get_gmail_service(effective_uid)
        labels = gmail.list_labels()
        _save_refreshed_token(gmail)
        print(f"✅ [Gmail] labels loaded: {len(labels)} total")
        return {"success": True, "labels": labels}
    except HTTPException:
        raise
    except GmailTokenExpiredError as e:
        print(f"❌ [Gmail] TOKEN_EXPIRED uid={effective_uid}: {e}")
        return JSONResponse(status_code=401, content={"success": False, "error": str(e), "code": "TOKEN_EXPIRED"})
    except Exception as e:
        print(f"❌ [Gmail] Unexpected error uid={effective_uid}: {type(e).__name__}: {e}")
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


# --- Portal Links: fetch emails from Gmail and parse portal URLs ---

_body_parser = EmailBodyParser()

_INVOICE_NO_PATTERNS = [
    re.compile(r'([A-Z]\d{2}[A-Z]{2,3}[-/]\d{5,8})', re.IGNORECASE),
    re.compile(r'(?:HD|hoa\s*don|invoice)\s*#?\s*([A-Z0-9]+-?\d+)', re.IGNORECASE),
    re.compile(r'(?:so|number)\s*:?\s*(\d{5,10})', re.IGNORECASE),
]


def _extract_supplier_name(subject: str, from_name: str) -> str:
    """Extract supplier name from email subject or fall back to from_name.

    Patterns:
    1. [COMPANY NAME] ... (EINVOICE, VIETTEL, etc.)
    2. COMPANY NAME gửi hóa đơn ... (MISA)
    """
    # Pattern 1: [COMPANY NAME]
    m = re.search(r'\[([^\]]+)\]', subject)
    if m:
        return m.group(1).strip()
    # Pattern 2: "COMPANY NAME gửi hóa đơn"
    m = re.search(r'^(.+?)\s+gửi\s+hóa\s+đơn', subject, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return from_name


def _extract_invoice_no(subject: str) -> str:
    """Try to extract invoice number from email subject line."""
    for pattern in _INVOICE_NO_PATTERNS:
        m = pattern.search(subject)
        if m:
            return m.group(1)
    return ''


@router.get("/portal-links")
def get_portal_links(
    uid: Optional[str] = Query(None),
    label_id: Optional[str] = Query(None, alias='label_id'),
    label_name: Optional[str] = Query(None, alias='label_name'),
    days_back: int = Query(default=30, ge=1, le=365),
    page_size: int = Query(default=30, ge=1, le=100),
):
    """GET /api/gmail/portal-links — Fetch emails from Gmail label, parse body for portal URLs."""
    effective_uid = uid or settings.gmail_uid
    if not effective_uid:
        return JSONResponse(status_code=400, content={
            "success": False, "error": "uid is required. Connect Gmail first or set GMAIL_UID in .env"
        })

    logger.info(f"[portal-links] uid={effective_uid}, label_id={label_id}, label_name={label_name}, "
                f"days_back={days_back}, page_size={page_size}")

    try:
        gmail = _get_gmail_service(effective_uid)

        # Resolve label_name to label_id if needed
        if label_name and not label_id:
            labels = gmail.list_labels()
            match = next((l for l in labels if l['name'] == label_name), None)
            if match:
                label_id = match['id']
                logger.info(f"[portal-links] Resolved label '{label_name}' -> id={label_id}")

        # List message stubs
        label_ids = [label_id] if label_id else None
        stubs = gmail.list_messages(
            days_back=days_back,
            max_results=page_size,
            label_ids=label_ids
        )
        logger.info(f"[portal-links] Gmail returned {len(stubs)} message stubs")

        # Fetch full messages sequentially (googleapiclient is NOT thread-safe)
        results = []
        parse_errors = 0
        for i, stub in enumerate(stubs):
            try:
                msg_data = gmail.get_message_full(stub['id'])
                if msg_data is None:
                    logger.warning(f"[portal-links] msg {i+1}/{len(stubs)} id={stub['id']}: get_message_full returned None")
                    parse_errors += 1
                    continue

                portal_info = {}
                if msg_data.get('bodyHtml'):
                    portal_info = _body_parser.extract_portal_url(msg_data['bodyHtml'])

                if not portal_info.get('portalUrl'):
                    body = msg_data.get('bodyHtml', '')
                    # Log a snippet of the body to help debug URL detection
                    body_snippet = body[:500].replace('\n', ' ').replace('\r', '') if body else 'EMPTY'
                    logger.warning(f"[portal-links] msg {i+1}/{len(stubs)}: no portalUrl found | "
                                f"subject={msg_data.get('subject', '')[:60]} | "
                                f"from={msg_data.get('from_address', '')} | "
                                f"bodyLen={len(body)} | bodySnippet={body_snippet}")

                # Extract supplierTaxCode from credentials if available
                credentials = portal_info.get('credentials', {})
                supplier_tax_code = credentials.get('taxCode', '')

                # Use body-extracted invoiceNo/invoiceSymbol as fallback
                invoice_no = _extract_invoice_no(msg_data.get('subject', ''))
                if not invoice_no and portal_info.get('invoiceNo'):
                    invoice_no = portal_info['invoiceNo']
                invoice_symbol = portal_info.get('invoiceSymbol', '')

                results.append({
                    'gmailId': msg_data['gmail_id'],
                    'gmailThreadId': msg_data.get('thread_id', msg_data['gmail_id']),
                    'invoiceNo': invoice_no,
                    'invoiceSymbol': invoice_symbol,
                    'supplierName': _extract_supplier_name(msg_data.get('subject', ''), msg_data.get('from_name', '')),
                    'supplierTaxCode': supplier_tax_code,
                    'issueDate': msg_data.get('date', ''),
                    'invoiceProvider': portal_info.get('provider', ''),
                    'portalUrl': portal_info.get('portalUrl', ''),
                    'portalPdfUrl': portal_info.get('portalPdfUrl', ''),
                    'portalCredentials': portal_info.get('credentials', {}),
                    'gmailFrom': msg_data.get('from_address', ''),
                    'gmailSubject': msg_data.get('subject', ''),
                    'attachments': msg_data.get('attachments', []),
                })
            except Exception as e:
                logger.error(f"[portal-links] msg {i+1}/{len(stubs)} id={stub['id']}: {type(e).__name__}: {e}")
                parse_errors += 1

        _save_refreshed_token(gmail)

        logger.info(f"[portal-links] Done: {len(results)} results, {parse_errors} errors, "
                    f"withPortalUrl={sum(1 for r in results if r['portalUrl'])}")

        return {
            "success": True,
            "portalLinks": results,
            "total": len(results),
            "fetchedFromGmail": len(stubs),
            "parseErrors": parse_errors,
        }

    except HTTPException:
        raise
    except GmailTokenExpiredError as e:
        logger.error(f"[portal-links] TOKEN_EXPIRED uid={effective_uid}: {e}")
        return JSONResponse(status_code=401, content={"success": False, "error": str(e), "code": "TOKEN_EXPIRED"})
    except Exception as e:
        logger.error(f"[portal-links] Error uid={effective_uid}: {type(e).__name__}: {e}")
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})
