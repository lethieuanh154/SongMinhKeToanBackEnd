"""
HDDT PROXY ROUTES (FastAPI)
Proxy để gọi API từ hoadondientu.gdt.gov.vn
Tránh vấn đề CORS khi gọi từ frontend
"""

import asyncio
import logging
import re
import time

import requests
from fastapi import APIRouter, HTTPException, Request, Query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/hddt", tags=["HDDT Proxy"])

HDDT_API_BASE = 'https://hoadondientu.gdt.gov.vn/api'


# ==================== SVG CAPTCHA SOLVER ====================

CAPTCHA_PATTERNS = {
    'MQQQQQZMQQQQQQQQQQQZMQQQQQQQQQQQQQQQQQQZMQQZ': 'A',
    'MQQQQQQQQQZMQQQQQQZMQQQQQQQQQQQQZMQQQQQQQQQQQQQQQQQZMQQQQQQQQZMQQQQQQQQZ': 'B',
    'MQQQQQQQQQQQQQQQQQQQQQZMQQQQQQQQQQQQQQQQQQQQQQQQZ': 'C',
    'MQQQQQQQQZMQQQQQQQQQQZMQQQQQQQQQQQQQQQZMQQQQQQQZ': 'D',
    'MQQQQQQQQQQQQQQQQQQZMQQQQQQQQQQQQQQQQQQQQQQQQQQQZ': 'E',
    'MQQQQQQQQQQQQQQZMQQQQQQQQQQQQQQQQQQQQQZ': 'F',
    'MQQQQQQQQQQQQQQQQQQQQQQQQQQQZMQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQZ': 'G',
    'MQQQQQQQQQQQQQQQZMQQQQQQQQQQQQQQQQQQQQQQQQZ': 'H',
    'MQQQQQQQQQQQQQQQZMQQQQQQQQQQQQQQQQQZ': 'J',
    'MQQQQQQQQQQQQQZMQQQQQQQQQQQQQQQQQQQQZ': 'K',
    'MQQQQQQQQQQQQQQQQQQQQQZMQQQQQQQQQQQQQQQQQQQQQQQQQZ': 'M',
    'MQQQQQQQQQQQQQQZMQQQQQQQQQQQQQQQQQQZ': 'N',
    'MQQQQQQZMQQQQQQQQQQZMQQQQQQQQQQQQQQQZMQQQQQQQQZ': 'P',
    'MQQQQQQQQQQQQQQQZMQQQQQQQQQQQQQQQZMQQQQQQQQQQQQQQQQQQQQQQZMQQQQQQQQQQQQZ': 'Q',
    'MQQQQQQZMQQQQQQQQQQQQZMQQQQQQQQQQQQQQQZMQQQQQQQQZ': 'R',
    'MQQQQQQQQQQQQQQQQQQQQQQQQQQZMQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQZ': 'S',
    'MQQQQQQQQQQQZMQQQQQQQQQQQQQQQQQQQZ': 'T',
    'MQQQQQQQQQQZMQQQQQQQQQQQQQQQQZ': 'V',
    'MQQQQQQQQQQQQQQQQQQQZMQQQQQQQQQQQQQQQQQQQQQQQQQQQZ': 'W',
    'MQQQQQQQQQQQQZMQQQQQQQQQQQQQQQQQQQQZ': 'X',
    'MQQQQQQQQQZMQQQQQQQQQQQQQZ': 'Y',
    'MQQQQQQQQQQQQQQQQZMQQQQQQQQQQQQQQQQQQQQQZ': 'Z',
    'MQQQQQQQQQQQQQQQQQQQQQQZMQQQQQQQQQQQQQQQQQQQQQQQQQQQQQZ': '2',
    'MQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQZMQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQZ': '3',
    'MQQQQZMQQQQQQQQQQQQQZMQQQQQQQQQQQQQQQQQQQQZMQQQQQZ': '4',
    'MQQQQQQQQQQQQQQQQQQQQQZMQQQQQQQQQQQQQQQQQQQQQQQQQQQQQQZ': '5',
    'MQQQQQQQQQZMQQQQQQQQQQQQQQQZMQQQQQQQQQQQQQQQQQQQQQZMQQQQQQQQZ': '6',
    'MQQQQQQQQQQQQQQQQQZMQQQQQQQQQQQQQQQQQQQQQQZ': '7',
    'MQQQQQQQQZMQQQQQQQZMQQQQQQQQQQQQQQQZMQQQQQQQQQQQQQQQQQQQQQZMQQQQQQQQQZMQQQQQQQZ': '8',
    'MQQQQQQQQZMQQQQQQQQQQQQQQQQQZMQQQQQQQQQQQQQQQQQQQQZMQQQQQQQQQQQZ': '9',
}


def solve_svg_captcha(svg_content: str) -> str:
    try:
        parts = svg_content.split(' d="')
        pattern = re.compile(r'([MQZ])([^MQZ]*)')
        chars = []

        for i in range(1, len(parts)):
            path_data = parts[i].split('"')[0]
            matches = list(pattern.finditer(path_data))
            if not matches:
                continue

            fingerprint = pattern.sub(r'\1', path_data)

            first_match = matches[0]
            sub = first_match.group(2).strip()
            x_pos = 0
            if sub:
                num_match = re.match(r'([\d.]+)', sub)
                if num_match:
                    x_pos = float(num_match.group(1))

            if fingerprint in CAPTCHA_PATTERNS:
                chars.append((x_pos, CAPTCHA_PATTERNS[fingerprint]))

        if not chars:
            return ''

        chars.sort(key=lambda c: c[0])
        return ''.join(c[1] for c in chars)

    except Exception as e:
        logger.error(f"[Captcha Solver] Error: {e}")
        return ''


# ==================== LOGIN ENDPOINTS ====================

@router.get("/captcha")
async def get_captcha():
    try:
        response = await asyncio.to_thread(
            requests.get,
            f"{HDDT_API_BASE}/captcha",
            params={"t": int(time.time() * 1000)},
            headers={"Cache-Control": "no-cache, no-store", "Pragma": "no-cache"},
            timeout=15,
            verify=True
        )

        if response.status_code == 200:
            data = response.json()
            captcha_key = data.get('key', '')
            captcha_svg = data.get('content', '')

            solved = solve_svg_captcha(captcha_svg)
            logger.info(f"[Captcha] key={captcha_key}, solved={solved}")

            return {
                'key': captcha_key,
                'content': captcha_svg,
                'solved': solved
            }
        else:
            raise HTTPException(status_code=response.status_code,
                                detail=f'GDT API Error: {response.status_code}')

    except requests.exceptions.Timeout:
        raise HTTPException(status_code=504, detail='Request timeout')
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[Captcha] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/login")
async def login(request: Request):
    try:
        body = await request.json()
        if not body:
            raise HTTPException(status_code=400, detail='Missing request body')

        username = body.get('username', '')
        password = body.get('password', '')
        ckey = body.get('ckey', '')
        cvalue = body.get('cvalue', '')

        if not all([username, password, ckey, cvalue]):
            raise HTTPException(status_code=400,
                                detail='Missing required fields: username, password, ckey, cvalue')

        auth_url = f"{HDDT_API_BASE}/security-taxpayer/authenticate"
        auth_payload = {
            'username': username,
            'password': password,
            'cvalue': cvalue,
            'ckey': ckey
        }

        auth_response = await asyncio.to_thread(
            requests.post, auth_url, json=auth_payload, timeout=15, verify=True
        )

        if auth_response.status_code != 200:
            error_detail = auth_response.text
            logger.error(f"[Login] Auth failed: {auth_response.status_code} - {error_detail}")
            raise HTTPException(
                status_code=auth_response.status_code,
                detail=error_detail or 'Đăng nhập thất bại'
            )

        auth_data = auth_response.json()
        token = auth_data.get('token', '')

        if not token:
            raise HTTPException(status_code=500, detail='Không nhận được token từ GDT')

        # Lấy profile
        profile = None
        try:
            profile_response = await asyncio.to_thread(
                requests.get,
                f"{HDDT_API_BASE}/security-taxpayer/profile",
                headers={'Authorization': f'Bearer {token}'},
                timeout=15, verify=True
            )
            if profile_response.status_code == 200:
                profile = profile_response.json()
        except Exception as e:
            logger.warning(f"[Login] Failed to get profile: {e}")

        return {'token': token, 'profile': profile}

    except requests.exceptions.Timeout:
        raise HTTPException(status_code=504, detail='Request timeout')
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[Login] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== HELPER ====================

def _get_auth_header(request: Request) -> str:
    auth_header = request.headers.get('Authorization')
    if not auth_header:
        raise HTTPException(status_code=401, detail='Missing Authorization header')
    return auth_header


def _fetch_all_pages_sync(url: str, headers: dict, sort: str, size: str,
                          search: str, max_pages: int = 20):
    all_datas = []
    state = None
    page = 0

    while page < max_pages:
        page += 1
        params = {'sort': sort, 'size': size, 'search': search}
        if state:
            params['state'] = state

        logger.info(f"[HDDT Proxy] Page {page}: GET {url} (state={'yes' if state else 'none'})")

        response = requests.get(url, params=params, headers=headers, timeout=30, verify=True)

        if response.status_code != 200:
            logger.error(f"[HDDT Proxy] Page {page} Error: {response.status_code} - {response.text}")
            if page == 1:
                return None, response.status_code, response.text
            else:
                break

        data = response.json()
        datas = data.get('datas', [])
        all_datas.extend(datas)

        logger.info(f"[HDDT Proxy] Page {page}: got {len(datas)} items (total: {len(all_datas)})")

        next_state = data.get('state')
        if not next_state or len(datas) < int(size):
            break

        state = next_state

    return all_datas, 200, None


# ==================== INVOICE ENDPOINTS ====================

@router.get("/purchase")
async def get_purchase_invoices(request: Request,
                                sort: str = Query(default='tdlap:desc'),
                                size: str = Query(default='50'),
                                search: str = Query(default='')):
    try:
        auth_header = _get_auth_header(request)
        url = f"{HDDT_API_BASE}/query/invoices/purchase"
        headers = {'Authorization': auth_header, 'Content-Type': 'application/json'}

        all_datas, status, error_text = await asyncio.to_thread(
            _fetch_all_pages_sync, url, headers, sort, size, search
        )

        if all_datas is None:
            raise HTTPException(status_code=status,
                                detail={'error': f'HDDT API Error: {status}', 'detail': error_text})

        return {'datas': all_datas, 'total': len(all_datas)}

    except HTTPException:
        raise
    except requests.exceptions.Timeout:
        raise HTTPException(status_code=504, detail='Request timeout')
    except Exception as e:
        logger.exception(f"[HDDT Proxy] Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/purchase-sco")
async def get_purchase_invoices_sco(request: Request,
                                    sort: str = Query(default='tdlap:desc'),
                                    size: str = Query(default='50'),
                                    search: str = Query(default='')):
    try:
        auth_header = _get_auth_header(request)
        url = f"{HDDT_API_BASE}/sco-query/invoices/purchase"
        headers = {'Authorization': auth_header, 'Content-Type': 'application/json'}

        all_datas, status, error_text = await asyncio.to_thread(
            _fetch_all_pages_sync, url, headers, sort, size, search
        )

        if all_datas is None:
            raise HTTPException(status_code=status,
                                detail={'error': f'HDDT API Error: {status}', 'detail': error_text})

        return {'datas': all_datas, 'total': len(all_datas)}

    except HTTPException:
        raise
    except requests.exceptions.Timeout:
        raise HTTPException(status_code=504, detail='Request timeout')
    except Exception as e:
        logger.exception(f"[HDDT Proxy] Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sold")
async def get_sold_invoices(request: Request,
                            sort: str = Query(default='tdlap:desc'),
                            size: str = Query(default='50'),
                            search: str = Query(default='')):
    try:
        auth_header = _get_auth_header(request)
        url = f"{HDDT_API_BASE}/sco-query/invoices/sold"
        headers = {'Authorization': auth_header, 'Content-Type': 'application/json'}

        all_datas, status, error_text = await asyncio.to_thread(
            _fetch_all_pages_sync, url, headers, sort, size, search
        )

        if all_datas is None:
            raise HTTPException(status_code=status,
                                detail={'error': f'HDDT API Error: {status}', 'detail': error_text})

        return {'datas': all_datas, 'total': len(all_datas)}

    except HTTPException:
        raise
    except requests.exceptions.Timeout:
        raise HTTPException(status_code=504, detail='Request timeout')
    except Exception as e:
        logger.exception(f"[HDDT Proxy] Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sold-detail")
async def get_sold_invoice_detail(request: Request,
                                   nbmst: str = Query(...),
                                   khhdon: str = Query(...),
                                   shdon: str = Query(...),
                                   khmshdon: str = Query(...)):
    try:
        auth_header = _get_auth_header(request)
        url = f"{HDDT_API_BASE}/sco-query/invoices/detail"
        params = {'nbmst': nbmst, 'khhdon': khhdon, 'shdon': shdon, 'khmshdon': khmshdon}
        headers = {'Authorization': auth_header, 'Content-Type': 'application/json'}

        logger.info(f"[HDDT Proxy] GET {url} with params: {params}")

        response = await asyncio.to_thread(
            requests.get, url, params=params, headers=headers, timeout=30, verify=True
        )

        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"[HDDT Proxy] Error: {response.status_code} - {response.text}")
            raise HTTPException(status_code=response.status_code,
                                detail={'error': f'HDDT API Error: {response.status_code}',
                                        'detail': response.text})

    except HTTPException:
        raise
    except requests.exceptions.Timeout:
        raise HTTPException(status_code=504, detail='Request timeout')
    except Exception as e:
        logger.exception(f"[HDDT Proxy] Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/invoice/{invoice_id}")
async def get_invoice_detail_by_id(invoice_id: str, request: Request):
    try:
        auth_header = _get_auth_header(request)
        url = f"{HDDT_API_BASE}/query/invoices/{invoice_id}"
        headers = {'Authorization': auth_header, 'Content-Type': 'application/json'}

        logger.info(f"[HDDT Proxy] GET {url}")

        response = await asyncio.to_thread(
            requests.get, url, headers=headers, timeout=30, verify=True
        )

        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"[HDDT Proxy] Error: {response.status_code} - {response.text}")
            raise HTTPException(status_code=response.status_code,
                                detail={'error': f'HDDT API Error: {response.status_code}',
                                        'detail': response.text})

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"[HDDT Proxy] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/detail")
async def get_invoice_detail(request: Request,
                              nbmst: str = Query(...),
                              khhdon: str = Query(...),
                              shdon: str = Query(...),
                              khmshdon: str = Query(...)):
    try:
        auth_header = _get_auth_header(request)
        params = {'nbmst': nbmst, 'khhdon': khhdon, 'shdon': shdon, 'khmshdon': khmshdon}
        headers = {'Authorization': auth_header, 'Content-Type': 'application/json'}

        # Thử /query trước (HĐ điện tử thông thường)
        url1 = f"{HDDT_API_BASE}/query/invoices/detail"
        logger.info(f"[HDDT Proxy] GET {url1} with params: {params}")
        response = await asyncio.to_thread(
            requests.get, url1, params=params, headers=headers, timeout=30, verify=True
        )

        if response.status_code == 200:
            return response.json()

        # Fallback sang /sco-query (HĐ máy tính tiền)
        url2 = f"{HDDT_API_BASE}/sco-query/invoices/detail"
        logger.info(f"[HDDT Proxy] Fallback GET {url2} with params: {params}")
        response2 = await asyncio.to_thread(
            requests.get, url2, params=params, headers=headers, timeout=30, verify=True
        )

        if response2.status_code == 200:
            return response2.json()

        logger.error(f"[HDDT Proxy] Both endpoints failed: {response.status_code}, {response2.status_code}")
        raise HTTPException(status_code=response2.status_code,
                            detail={'error': f'HDDT API Error: {response2.status_code}',
                                    'detail': response2.text})

    except HTTPException:
        raise
    except requests.exceptions.Timeout:
        raise HTTPException(status_code=504, detail='Request timeout')
    except Exception as e:
        logger.exception(f"[HDDT Proxy] Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
