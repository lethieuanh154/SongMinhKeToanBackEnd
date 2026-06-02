"""
Gmail API routes for KeToanBackEnd.
GET  /api/gmail/auth/url         — Redirect popup to Google OAuth (no uid needed)
GET  /api/gmail/auth/callback    — OAuth callback, saves tokens, postMessage uid+email
GET  /api/gmail/labels           — List Gmail labels for a uid
GET  /api/gmail/portal-links     — Fetch emails from Gmail, parse portal URLs + optional attachment parsing
POST /api/gmail/emails/{id}/process  — Process single email: download attachment → parse XML/PDF
POST /api/gmail/scrape-portal-xml    — Download XML from portal URLs via Playwright, cache amounts
"""
import re
import base64
import secrets
import logging
import asyncio
from typing import Optional

from fastapi import APIRouter, Query, HTTPException, Request, Body
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel
import httpx

from app.config.firebase import get_gmail_db
from app.config.settings import settings
from app.services.gmail_service import GmailService, GmailTokenExpiredError
from app.services.email_body_parser import EmailBodyParser
from app.services.invoice_parsers import TaxInvoiceXMLParser
from app.services.zip_extractor import extract_xml_from_zip, extract_pdf_from_zip
from app.services.playwright_scraper import scrape_xml as playwright_scrape_xml, get_provider_config as get_scraper_config

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


# --- Process Email: download attachment → parse XML/PDF ---

@router.post("/emails/{email_id}/process")
def process_email(
    email_id: str,
    body: dict = Body(default={}),
    uid: Optional[str] = Query(None),
):
    """POST /api/gmail/emails/{email_id}/process
    Auto-detect attachment type and process:
    - XML → parse with TaxInvoiceXMLParser
    - ZIP → extract XML → parse (or extract PDF → return for Gemini)
    - PDF → return base64 for frontend Gemini processing
    - None → return type='none'
    """
    effective_uid = body.get('uid') or uid or settings.gmail_uid
    if not effective_uid:
        return JSONResponse(status_code=400, content={
            "success": False, "error": "uid is required"
        })

    try:
        gmail = _get_gmail_service(effective_uid)
        metadata = gmail.get_message_metadata(email_id)

        if not metadata:
            _save_refreshed_token(gmail)
            return JSONResponse(status_code=404, content={
                "success": False, "error": "Email not found"
            })

        # Extract portal URL from email body HTML
        portal_info = {}
        try:
            email_body_html = gmail.get_email_body_html(email_id)
            if email_body_html:
                portal_info = _body_parser.extract_portal_url(email_body_html)
        except Exception as e:
            logger.warning(f"Failed to extract portal URL: {e}")

        attachments = metadata.get('attachments', [])
        attachments_lower = [a.lower() for a in attachments]

        has_xml = any(a.endswith('.xml') for a in attachments_lower)
        has_zip = any(a.endswith('.zip') for a in attachments_lower)
        has_pdf = any(a.endswith('.pdf') for a in attachments_lower)

        portal_fields = {
            'portalUrl': portal_info.get('portalUrl', ''),
            'invoiceProvider': portal_info.get('provider', ''),
            'portalPdfUrl': portal_info.get('portalPdfUrl', ''),
            'portalCredentials': portal_info.get('credentials', {}),
        }

        # Priority 1: Direct XML attachment
        if has_xml:
            xml_bytes = gmail.get_xml_attachment(email_id)
            if xml_bytes:
                invoices, errors = TaxInvoiceXMLParser.parse(xml_bytes)
                _save_refreshed_token(gmail)
                return {
                    'success': True,
                    'type': 'xml',
                    'invoices': invoices,
                    'parse_errors': errors,
                    'email': metadata,
                    **portal_fields
                }

        # Priority 2: ZIP → extract XML first, then PDF
        if has_zip:
            zip_result = gmail.get_zip_attachment(email_id)
            if zip_result:
                zip_bytes, zip_name = zip_result

                xml_result = extract_xml_from_zip(zip_bytes)
                if xml_result:
                    xml_bytes, xml_name = xml_result
                    invoices, errors = TaxInvoiceXMLParser.parse(xml_bytes)
                    _save_refreshed_token(gmail)
                    return {
                        'success': True,
                        'type': 'zip_xml',
                        'invoices': invoices,
                        'parse_errors': errors,
                        'source_file': xml_name,
                        'email': metadata,
                        **portal_fields
                    }

                pdf_result = extract_pdf_from_zip(zip_bytes)
                if pdf_result:
                    pdf_bytes, pdf_name = pdf_result
                    pdf_b64 = base64.b64encode(pdf_bytes).decode('utf-8')
                    _save_refreshed_token(gmail)
                    return {
                        'success': True,
                        'type': 'zip_pdf',
                        'needs_gemini': True,
                        'pdf_base64': pdf_b64,
                        'pdf_filename': pdf_name,
                        'email': metadata,
                        **portal_fields
                    }

        # Priority 3: Direct PDF attachment
        if has_pdf:
            pdf_result = gmail.get_pdf_attachment(email_id)
            if pdf_result:
                pdf_bytes, pdf_name = pdf_result
                pdf_b64 = base64.b64encode(pdf_bytes).decode('utf-8')
                _save_refreshed_token(gmail)
                return {
                    'success': True,
                    'type': 'pdf',
                    'needs_gemini': True,
                    'pdf_base64': pdf_b64,
                    'pdf_filename': pdf_name,
                    'email': metadata,
                    **portal_fields
                }

        # No processable attachment
        _save_refreshed_token(gmail)
        return {
            'success': True,
            'type': 'none',
            'message': 'Không có file đính kèm xử lý được.',
            'email': metadata,
            **portal_fields
        }

    except HTTPException:
        raise
    except GmailTokenExpiredError as e:
        return JSONResponse(status_code=401, content={
            "success": False, "error": str(e), "code": "TOKEN_EXPIRED"
        })
    except Exception as e:
        logger.error(f"Error processing email {email_id}: {e}")
        return JSONResponse(status_code=500, content={
            "success": False, "error": str(e)
        })


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
    # Pattern 3: "... số_ NUMBER - COMPANY kính gửi ..." (EasyInvoice)
    m = re.search(r'\d+\s*-\s*(.+?)\s+kính\s+gửi', subject, re.IGNORECASE)
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


_INVOICE_NO_BODY_PATTERN = re.compile(r'Số\s+hóa\s+đơn\s*:?\s*(\d+)', re.IGNORECASE)
_INVOICE_SYMBOL_BODY_PATTERN = re.compile(r'Ký\s+hiệu\s*:?\s*([A-Z0-9]+)', re.IGNORECASE)
# Attachment filename format: {mst}-{kyHieu}-{soHD_padded}.{ext}
# e.g. 0402114198-1C26TAN-0000074.pdf
_ATTACHMENT_INVOICE_PATTERN = re.compile(r'^\d{10,13}-([A-Z0-9]+)-(\d+)\.(xml|pdf)$', re.IGNORECASE)


def _extract_invoice_fields_from_body(body_html: str) -> tuple:
    """Extract (invoiceNo, invoiceSymbol) from email body HTML."""
    text = re.sub(r'<[^>]+>', ' ', body_html)
    invoice_no = ''
    m = _INVOICE_NO_BODY_PATTERN.search(text)
    if m:
        invoice_no = m.group(1)
    invoice_symbol = ''
    m = _INVOICE_SYMBOL_BODY_PATTERN.search(text)
    if m:
        invoice_symbol = m.group(1)
    return invoice_no, invoice_symbol


def _extract_invoice_fields_from_attachments(attachments: list) -> tuple:
    """Extract (invoiceNo, invoiceSymbol) from attachment filenames.
    Format: {mst}-{kyHieu}-{soHD_padded}.xml|pdf → (invoiceNo_stripped, invoiceSymbol)
    """
    for name in attachments:
        m = _ATTACHMENT_INVOICE_PATTERN.match(name)
        if m:
            symbol = m.group(1)
            no = str(int(m.group(2)))  # 0000074 → 74
            return no, symbol
    return '', ''


def _parse_attachment_for_amounts(gmail: GmailService, email_id: str, attachments: list) -> dict:
    """Download and parse XML/ZIP attachment to extract invoice amounts.
    Returns dict with amounts or empty dict if no parseable attachment."""
    attachments_lower = [a.lower() for a in attachments]

    has_xml = any(a.endswith('.xml') for a in attachments_lower)
    has_zip = any(a.endswith('.zip') for a in attachments_lower)
    has_pdf = any(a.endswith('.pdf') for a in attachments_lower)

    # Priority 1: XML attachment
    if has_xml:
        try:
            xml_bytes = gmail.get_xml_attachment(email_id)
            if xml_bytes:
                invoices, _ = TaxInvoiceXMLParser.parse(xml_bytes)
                if invoices:
                    inv = invoices[0]
                    return {
                        'hasAmounts': True,
                        'parseSource': 'xml_attachment',
                        'needsAiProcessing': False,
                        'invoiceNo': inv.get('invoiceNo', ''),
                        'invoiceSymbol': inv.get('invoiceSymbol', ''),
                        'invoiceDate': inv.get('invoiceDate', ''),
                        'supplierTaxCode': inv.get('sellerTaxCode', ''),
                        'supplierName': inv.get('sellerName', ''),
                        'totalBeforeVat': inv.get('totalBeforeVat', 0),
                        'vatAmount': inv.get('vatAmount', 0),
                        'vatRate': inv.get('vatRate', 0),
                        'totalAmount': inv.get('totalAmount', 0),
                        'items': inv.get('items', []),
                    }
        except Exception as e:
            logger.warning(f"[parse_attachment] XML parse failed for {email_id}: {e}")

    # Priority 2: ZIP → extract XML
    if has_zip:
        try:
            zip_result = gmail.get_zip_attachment(email_id)
            if zip_result:
                zip_bytes, _ = zip_result
                xml_result = extract_xml_from_zip(zip_bytes)
                if xml_result:
                    xml_bytes, _ = xml_result
                    invoices, _ = TaxInvoiceXMLParser.parse(xml_bytes)
                    if invoices:
                        inv = invoices[0]
                        return {
                            'hasAmounts': True,
                            'parseSource': 'zip_xml',
                            'needsAiProcessing': False,
                            'invoiceNo': inv.get('invoiceNo', ''),
                            'invoiceSymbol': inv.get('invoiceSymbol', ''),
                            'invoiceDate': inv.get('invoiceDate', ''),
                            'supplierTaxCode': inv.get('sellerTaxCode', ''),
                            'supplierName': inv.get('sellerName', ''),
                            'totalBeforeVat': inv.get('totalBeforeVat', 0),
                            'vatAmount': inv.get('vatAmount', 0),
                            'vatRate': inv.get('vatRate', 0),
                            'totalAmount': inv.get('totalAmount', 0),
                            'items': inv.get('items', []),
                        }
        except Exception as e:
            logger.warning(f"[parse_attachment] ZIP parse failed for {email_id}: {e}")

    # Priority 3: PDF — cannot parse server-side (needs Gemini AI)
    if has_pdf:
        return {
            'hasAmounts': False,
            'parseSource': 'none',
            'needsAiProcessing': True,
        }

    return {
        'hasAmounts': False,
        'parseSource': 'none',
        'needsAiProcessing': False,
    }


@router.get("/portal-links")
def get_portal_links(
    uid: Optional[str] = Query(None),
    label_id: Optional[str] = Query(None, alias='label_id'),
    label_name: Optional[str] = Query(None, alias='label_name'),
    days_back: int = Query(default=30, ge=1, le=365),
    page_size: int = Query(default=30, ge=1, le=500),
    parse_attachments: bool = Query(default=False, description="Parse XML/ZIP attachments to extract invoice amounts"),
):
    """GET /api/gmail/portal-links — Fetch emails from Gmail label, parse body for portal URLs.
    When parse_attachments=true, also downloads XML/ZIP attachments and parses invoice data."""
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

                # Extract supplierTaxCode from credentials if available, fallback to body-extracted taxCode
                credentials = portal_info.get('credentials', {})
                supplier_tax_code = credentials.get('taxCode', '') or portal_info.get('taxCode', '')

                # Extract invoiceNo: subject → portal_info → attachments → body HTML
                invoice_no = _extract_invoice_no(msg_data.get('subject', ''))
                invoice_symbol = portal_info.get('invoiceSymbol', '')
                if not invoice_no:
                    if portal_info.get('invoiceNo'):
                        invoice_no = portal_info['invoiceNo']
                    if not invoice_no:
                        att_no, att_symbol = _extract_invoice_fields_from_attachments(msg_data.get('attachments', []))
                        if att_no:
                            invoice_no = att_no
                        if not invoice_symbol and att_symbol:
                            invoice_symbol = att_symbol
                    if not invoice_no and msg_data.get('bodyHtml'):
                        body_no, body_symbol = _extract_invoice_fields_from_body(msg_data['bodyHtml'])
                        invoice_no = body_no
                        if not invoice_symbol:
                            invoice_symbol = body_symbol

                # KIOTVIET: extract invoiceSymbol + seller MST from subject
                if portal_info.get('provider') == 'KIOTVIET':
                    subj = msg_data.get('subject', '')
                    if not invoice_symbol:
                        m = re.search(r's[oố]\s+\d+\s+([A-Z][A-Z0-9]{2,})', subj)
                        if m:
                            invoice_symbol = m.group(1)
                    if not supplier_tax_code:
                        m = re.search(r'\bMST\s+(\d{10,13})(?:-\d+)?', subj)
                        if m:
                            supplier_tax_code = m.group(1)

                result_item = {
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
                }

                # Parse XML/ZIP attachment to extract amounts when requested
                if parse_attachments:
                    parsed = _parse_attachment_for_amounts(
                        gmail, msg_data['gmail_id'], msg_data.get('attachments', [])
                    )
                    result_item.update(parsed)
                    # Override metadata fields with parsed data (more accurate than regex)
                    if parsed.get('hasAmounts'):
                        if parsed.get('invoiceNo'):
                            result_item['invoiceNo'] = parsed['invoiceNo']
                        if parsed.get('invoiceSymbol'):
                            result_item['invoiceSymbol'] = parsed['invoiceSymbol']
                        if parsed.get('supplierTaxCode'):
                            result_item['supplierTaxCode'] = parsed['supplierTaxCode']
                        if parsed.get('supplierName'):
                            result_item['supplierName'] = parsed['supplierName']
                        if parsed.get('invoiceDate'):
                            result_item['invoiceDate'] = parsed['invoiceDate']

                results.append(result_item)
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


# --- Scrape portal XML via Playwright ---

class ScrapePortalItem(BaseModel):
    gmailId: str
    portalUrl: str
    provider: str = ''
    credentials: dict = {}

class ScrapePortalRequest(BaseModel):
    items: list[ScrapePortalItem]

_SCRAPE_SEMAPHORE = asyncio.Semaphore(3)  # max 3 concurrent browser sessions


async def _scrape_one(item: ScrapePortalItem) -> dict:
    async with _SCRAPE_SEMAPHORE:
        try:
            db = get_gmail_db()
            pconfig = get_scraper_config(db, item.provider) if item.provider else None
            xml_bytes = await playwright_scrape_xml(
                item.portalUrl, item.provider, item.credentials or None,
                provider_config=pconfig
            )
            if not xml_bytes:
                return {'gmailId': item.gmailId, 'success': False, 'error': 'no_xml'}

            invoices, errors = TaxInvoiceXMLParser.parse(xml_bytes)
            if not invoices:
                return {'gmailId': item.gmailId, 'success': False, 'error': f'parse_failed: {errors}'}

            inv = invoices[0]
            amounts = {
                'hasAmounts': True,
                'parseSource': 'portal_xml',
                'totalBeforeVat': inv.get('totalBeforeVat', 0),
                'vatAmount': inv.get('vatAmount', 0),
                'vatRate': inv.get('vatRate', 0),
                'totalAmount': inv.get('totalAmount', 0),
                'supplierTaxCode': inv.get('sellerTaxCode', ''),
                'supplierName': inv.get('sellerName', ''),
                'invoiceNo': inv.get('invoiceNo', ''),
                'invoiceSymbol': inv.get('invoiceSymbol', ''),
                'invoiceDate': inv.get('invoiceDate', ''),
            }

            # Cache to Firestore (gmail db)
            try:
                db = get_gmail_db()
                db.collection('portal_link_amounts').document(item.gmailId).set(amounts)
                logger.info(f"[scrape] Cached amounts for gmailId={item.gmailId}")
            except Exception as e:
                logger.warning(f"[scrape] Firestore cache failed for {item.gmailId}: {e}")

            return {'gmailId': item.gmailId, 'success': True, 'amounts': amounts}

        except Exception as e:
            logger.error(f"[scrape] Error for gmailId={item.gmailId}: {e}")
            return {'gmailId': item.gmailId, 'success': False, 'error': str(e)}


@router.post("/scrape-portal-xml")
async def scrape_portal_xml(body: ScrapePortalRequest):
    """POST /api/gmail/scrape-portal-xml
    Download XML from invoice portal URLs, parse amounts, cache in Firestore.
    Returns per-item results.
    """
    if not body.items:
        return {'success': True, 'results': []}

    # Check Firestore cache first
    db = get_gmail_db()
    items_to_scrape = []
    cached_results = []
    for item in body.items:
        try:
            doc = db.collection('portal_link_amounts').document(item.gmailId).get()
            if doc.exists:
                cached = doc.to_dict()
                if cached.get('hasAmounts'):
                    cached_results.append({'gmailId': item.gmailId, 'success': True, 'amounts': cached, 'cached': True})
                    logger.info(f"[scrape] Cache hit for gmailId={item.gmailId}")
                    continue
        except Exception:
            pass
        items_to_scrape.append(item)

    logger.info(f"[scrape] {len(cached_results)} cached, {len(items_to_scrape)} to scrape")

    scraped = await asyncio.gather(*[_scrape_one(i) for i in items_to_scrape])

    return {
        'success': True,
        'results': cached_results + list(scraped),
        'cached': len(cached_results),
        'scraped': len(items_to_scrape),
    }
