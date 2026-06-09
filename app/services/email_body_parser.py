"""
EmailBodyParser — Extract portal URL from invoice email HTML body.

Parses email HTML to extract:
- Portal URL for viewing/downloading the original invoice
- Invoice provider identification (11 providers, 3 groups)
- Credentials for Group B providers (tax code, secret code, etc.)

Groups:
  A — Direct URL (href contains full params)
  B — URL + Credentials (URL has no params, credentials in email text)
  C — AWS Tracking Wrapper (unwrap awstrack.me -> actual URL)
"""

import re
import html as html_module
import logging
from typing import Dict, Optional
from urllib.parse import unquote

logger = logging.getLogger(__name__)

# Try importing BeautifulSoup, fallback to regex-only parsing
try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False
    logger.warning("beautifulsoup4 not installed. EmailBodyParser will use regex-only parsing.")


PROVIDER_PATTERNS = {
    # -- GROUP A: Direct URL extract --
    'VIN_HOADON': {
        'group': 'A',
        'url_contains': ['vin-hoadon.com'],
        'href_pattern': r'https?://tracuu\.vin-hoadon\.com/tracuuhoadon/thongtinchung\?[^"\'>\s]+',
        'pdf_href_pattern': r'https?://tracuu\.vin-hoadon\.com/File/TaiPdfLinkTraCuu\?[^"\'>\s]+',
    },
    'MISA': {
        'group': 'A',
        'url_contains': ['meinvoice.vn'],
        'href_pattern': r'https?://www\.meinvoice\.vn/tra-cuu/\?sc=[^"\'>\s]+',
        'body_extract_patterns': {
            'invoiceNo': r'S[oố]\s*:\s*(\d+)',
            'invoiceSymbol': r'[Kk][yýYÝ]\s*hi[eệ]u\s*:?\s*([A-Z0-9]{3,10})',
            'lookupCode': r'(?:nh[aậ]p\s*m[aã]\s*s[oố]|m[aã]\s*s[oố])\s*[:\s]\s*([A-Za-z0-9_]+)',
        },
    },
    'VNPT': {
        'group': 'A',
        'url_contains': ['vnpt-invoice.com.vn'],
        'href_pattern': r'https?://[a-z0-9-]+\.vnpt-invoice\.com\.vn/Email/EmailInvoiceView\?token=[^"\'>\s]+',
        'pdf_href_pattern': r'https?://[a-z0-9-]+\.vnpt-invoice\.com\.vn/Email/PdfDownload\?token=[^"\'>\s]+',
    },
    'ASIAINVOICE': {
        'group': 'A',
        'url_contains': ['asiainvoice.vn'],
        'href_pattern': r'https?://[a-z0-9]+\.asiainvoice\.vn/EinvoiceView\?token=[^"\'>\s]+',
    },
    'KIOTVIET': {
        'group': 'A',
        'url_contains': ['kiotviet.vn'],
        'href_pattern': r'https?://tracuuhoadon\.kiotviet\.vn/\?shd=[^"\'>\s]+',
        'body_extract_patterns': {
            'invoiceNo': r'[?&]shd=(\d+)',
        },
    },
    'FASTINVOICE': {
        'group': 'A',
        'url_contains': ['einvoice.fast.com.vn'],
        'href_pattern': r'https?://einvoice\.fast\.com\.vn/index\.aspx\?type=1&[^"\'>\s]+',
        'pdf_href_pattern': r'https?://einvoice\.fast\.com\.vn/index\.aspx\?type=3&[^"\'>\s]+',
        'body_extract_patterns': {
            'invoiceNo': r'S[oố]\s+h[oó]a\s+[dđ][oơ]n\s*(?:\([^)]+\))?\s*:\s*(\d+)',
            'invoiceSymbol': r'K[yý]\s+hi[eệ]u\s+h[oó]a\s+[dđ][oơ]n\s*(?:\([^)]+\))?\s*:\s*([A-Z0-9]+)',
        },
    },
    'EHOADON': {
        'group': 'A',
        'url_contains': ['ehoadon.vn'],
        'href_pattern': r'https?://tracuu\.ehoadon\.vn/[A-Z0-9]+',
    },

    # -- GROUP B: URL + Credentials extract --
    'MOBIFONE': {
        'group': 'B',
        'url_contains': ['mobifoneinvoice.vn'],
        'href_pattern': r'https?://tracuuhoadon\.mobifoneinvoice\.vn/?',
        'portal_url': 'http://tracuuhoadon.mobifoneinvoice.vn/',
        'credential_patterns': {
            'taxCode': r'Mã\s*đơn\s*vị\s*[:\s]+(\d{10,13})',
            'secretCode': r'Mã\s*bảo\s*mật\s*[:\s]+([A-Za-z0-9]+)',
        },
    },
    'VIETTEL': {
        'group': 'B',
        'url_contains': ['vinvoice.viettel.vn', 'sinvoice.viettel.vn'],
        'href_pattern': r'https?://(?:vinvoice|sinvoice)\.viettel\.vn/(?:utilities/invoice-search|tracuuhoadon)',
        'portal_url': None,  # Use matched URL from email
        'credential_patterns': {
            'taxCode': r'mã\s*số\s*thuế\s*bên\s*bán\s+(\d{10,14})',
            'secretCode': r'mã\s*số\s*bí\s*mật\s+([A-Z0-9]+)',
        },
        'body_extract_patterns': {
            'invoiceNo': r's[oố]\s+[A-Z]\d+[A-Z]+(\d+)',
            'invoiceSymbol': r's[oố]\s+([A-Z]\d+[A-Z]+)\d+',
        },
    },
    'MINVOICE': {
        'group': 'B',
        'url_contains': ['minvoice.vn', 'minvoice.com.vn'],
        'href_pattern': r'https?://tracuuhoadon\.minvoice\.(?:vn|com\.vn)/?',
        'portal_url': 'http://tracuuhoadon.minvoice.com.vn/tra-cuu-hoa-don',
        'credential_patterns': {
            'taxCode': r'Bước 2[^<]*<strong>(\d{10,13})</strong>',
            'secretCode': r'Bước 3[^<]*<strong>\s*([A-Z0-9]+)</strong>',
        },
    },
    'EINVOICE': {
        'group': 'A',
        'url_contains': ['easyinvoice.com.vn'],
        'href_pattern': r'https?://[^.\s/]+\.easyinvoice\.com\.vn/Invoice/ViewFromEmail\?token=[^"\'>\s]+',
        'pdf_href_pattern': r'https?://[^.\s/]+\.easyinvoice\.com\.vn/Invoice/DownloadInvPdf\?token=[^"\'>\s]+',
        'body_extract_patterns': {
            'invoiceNo': r'Số\s+hóa\s+đơn\s*:?\s*(\d+)(?!\w)',
            'invoiceSymbol': r'Ký\s+hiệu\s+mẫu\s+số\s+hóa\s+đơn\s*:?\s*([A-Z0-9]+)',
            'taxCode': r'(?<!\()(?:[Mm][aã]\s*s[oố]\s*thu[eế]|MST)\s*:?\s*(\d{10,13})',
        },
    },

    # -- GROUP C: AWS Tracking Wrapper (unwrap) --
    'WININVOICE': {
        'group': 'C',
        'url_contains': ['wininvoice.vn'],
        'awstrack_pattern': r'https?://[^/]+\.awstrack\.me/L0/(https?:%2F%2Ftracuu\.wininvoice\.vn[^"\'>\s]*)/\d+/',
        'href_pattern': r'https?://tracuu\.wininvoice\.vn[^"\'>\s]*',
    },
}

# Generic patterns to extract invoice info from email body (clean text, no HTML tags)
_GENERIC_BODY_PATTERNS = {
    'invoiceNo': r'(?:S[oố]\s+h[oó]a\s*[dđ][oơ]n|[Hh][oó]a\s*[dđ][oơ]n\s+s[oố])\s*:?\s*(\d+)',
    'invoiceSymbol': r'[Kk][yýYÝ]\s*hi[eệ]u\s*:?\s*([A-Z0-9]{3,10})',
    'taxCode': r'(?<!\()(?:[Mm][aã]\s*s[oố]\s*thu[eế]|MST)\s*:?\s*(\d{10,13})',
}


class EmailBodyParser:
    """Parse email HTML body to extract portal URL for invoice lookup."""

    def extract_portal_url(self, email_html: str) -> Dict:
        """
        Parse HTML -> extract portal URL.

        Returns:
            {
                'portalUrl': str,
                'provider': str,
                'portalPdfUrl': str (if available),
                'credentials': dict (Group B only),
            }
        """
        if not email_html:
            return {}

        # Extract all href URLs from HTML
        hrefs = self._extract_hrefs(email_html)

        # Also extract plain-text URLs (for emails where URLs aren't wrapped in <a> tags)
        plain_urls = re.findall(r'https?://[^\s<>"\']+', email_html)
        all_urls = hrefs + [u for u in plain_urls if u not in hrefs]

        # Try each provider
        for provider_key, config in PROVIDER_PATTERNS.items():
            group = config['group']

            # Check if any URL (href or plain text) matches this provider
            matched_href = None
            for href in all_urls:
                for domain in config['url_contains']:
                    if domain in href.lower():
                        matched_href = href
                        break
                if matched_href:
                    break

            if not matched_href:
                # Group C: also check for awstrack wrapper
                if group == 'C' and 'awstrack_pattern' in config:
                    for href in all_urls:
                        if 'awstrack.me' in href.lower():
                            unwrapped = self._unwrap_awstrack_from_href(href, config)
                            if unwrapped:
                                matched_href = unwrapped
                                break
                if not matched_href:
                    continue

            result = {'provider': provider_key}

            if group == 'A':
                # Extract full URL with params
                portal_url = self._extract_pattern(email_html, config['href_pattern'])
                result['portalUrl'] = portal_url or matched_href

                # Check for bonus PDF URL
                if 'pdf_href_pattern' in config:
                    pdf_url = self._extract_pattern(email_html, config['pdf_href_pattern'])
                    if pdf_url:
                        result['portalPdfUrl'] = pdf_url

            elif group == 'B':
                result['portalUrl'] = config.get('portal_url') or matched_href
                credentials = self._extract_credentials(email_html, config)
                if credentials:
                    result['credentials'] = credentials

            elif group == 'C':
                # Try awstrack unwrap first
                if 'awstrack_pattern' in config:
                    unwrapped = self._extract_awstrack_url(email_html, config['awstrack_pattern'])
                    if unwrapped:
                        result['portalUrl'] = unwrapped
                    else:
                        result['portalUrl'] = matched_href
                else:
                    result['portalUrl'] = matched_href

            # Extract body fields (invoiceNo, invoiceSymbol, etc.)
            # Use provider-specific patterns if configured, otherwise use generic patterns
            extract_patterns = config.get('body_extract_patterns', _GENERIC_BODY_PATTERNS)
            decoded = html_module.unescape(email_html)
            clean_text = re.sub(r'<[^>]+>', ' ', decoded)
            clean_text = re.sub(r'\s+', ' ', clean_text)
            for field, pattern in extract_patterns.items():
                m = re.search(pattern, clean_text, re.IGNORECASE | re.DOTALL)
                if m:
                    result[field] = m.group(1).strip()
                    logger.info(f"[body_extract] {provider_key}.{field} = {result[field]}")

            if result.get('portalUrl'):
                logger.info(f"Extracted portal URL for {provider_key}: {result['portalUrl'][:80]}...")
                return result

        return {}

    def detect_provider(self, email_html: str, from_address: str = '') -> str:
        """Detect invoice provider from email content + sender domain."""
        if not email_html:
            return ''

        hrefs = self._extract_hrefs(email_html)
        plain_urls = re.findall(r'https?://[^\s<>"\']+', email_html)
        all_urls = hrefs + [u for u in plain_urls if u not in hrefs]

        for provider_key, config in PROVIDER_PATTERNS.items():
            for href in all_urls:
                for domain in config['url_contains']:
                    if domain in href.lower():
                        return provider_key

            # Group C: check awstrack
            if config['group'] == 'C':
                for href in all_urls:
                    if 'awstrack.me' in href.lower():
                        for domain in config['url_contains']:
                            if domain in href.lower():
                                return provider_key

        # Fallback: check from_address domain
        if from_address:
            from_domain = from_address.split('@')[-1].lower() if '@' in from_address else ''
            for provider_key, config in PROVIDER_PATTERNS.items():
                for domain in config['url_contains']:
                    if domain in from_domain:
                        return provider_key

        return ''

    def _extract_hrefs(self, html: str) -> list:
        """Extract all href URLs from HTML."""
        if HAS_BS4:
            try:
                soup = BeautifulSoup(html, 'html.parser')
                hrefs = []
                for a_tag in soup.find_all('a', href=True):
                    hrefs.append(a_tag['href'])
                return hrefs
            except Exception:
                pass

        # Fallback: regex extraction
        return re.findall(r'href=["\']([^"\']+)["\']', html)

    def _extract_pattern(self, html: str, pattern: str) -> Optional[str]:
        """Extract first match of regex pattern from HTML."""
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            return html_module.unescape(match.group(0))
        return None

    def _extract_credentials(self, html: str, config: dict) -> Dict:
        """Extract credentials from email body for Group B providers."""
        credentials = {}
        patterns = config.get('credential_patterns', {})

        decoded_html = html_module.unescape(html)
        clean_text = re.sub(r'<[^>]+>', ' ', decoded_html)
        clean_text = re.sub(r'\s+', ' ', clean_text)

        for key, pattern in patterns.items():
            # Try clean text first (handles plain text emails and simple HTML)
            match = re.search(pattern, clean_text, re.IGNORECASE)
            if not match:
                # Fallback: raw HTML (for patterns anchored on HTML tags like <strong>)
                match = re.search(pattern, decoded_html, re.IGNORECASE | re.DOTALL)
            if match:
                credentials[key] = match.group(1).strip()
            else:
                for keyword in ['tra cứu', 'bí mật', 'bảo mật', 'mã số', 'lookup', 'secret']:
                    idx = decoded_html.lower().find(keyword)
                    if idx >= 0:
                        snippet = decoded_html[max(0, idx-30):idx+120].replace('\n', ' ').replace('\r', '')
                        logger.warning(f"[credentials] key={key} pattern NOT matched, but found '{keyword}' at pos {idx}: ...{snippet}...")
                        break
                else:
                    logger.warning(f"[credentials] key={key} pattern NOT matched, no keyword found in decoded HTML ({len(decoded_html)} chars)")

        return credentials

    def _extract_awstrack_url(self, html: str, pattern: str) -> Optional[str]:
        """Extract and decode awstrack.me wrapped URL."""
        match = re.search(pattern, html, re.IGNORECASE)
        if match:
            encoded_url = match.group(1)
            return self._decode_awstrack(encoded_url)
        return None

    def _unwrap_awstrack_from_href(self, href: str, config: dict) -> Optional[str]:
        """Try to unwrap awstrack URL from a single href."""
        if 'awstrack_pattern' not in config:
            return None

        match = re.search(config['awstrack_pattern'], href, re.IGNORECASE)
        if match:
            return self._decode_awstrack(match.group(1))

        # Fallback: find url_contains domain in encoded href
        for domain in config['url_contains']:
            encoded_domain = domain.replace('.', '%2E')
            if encoded_domain in href or domain in href:
                # Try to extract the actual URL after /L0/
                l0_match = re.search(r'/L0/(https?[^/\s]+)', href)
                if l0_match:
                    return self._decode_awstrack(l0_match.group(1))
        return None

    @staticmethod
    def _decode_awstrack(encoded_url: str) -> str:
        """URL-decode awstrack.me wrapper -> actual portal URL."""
        decoded = unquote(encoded_url)
        # Handle double encoding
        if '%2F' in decoded or '%3F' in decoded:
            decoded = unquote(decoded)
        # Remove port :443 for https
        decoded = re.sub(r':443(?=/)', '', decoded)
        return decoded
