"""
Invoice Service — KeToanBackEnd
Reads/writes tax_invoices, internal_invoices, invoice_reconciliation
in taphoa39-supplies-invoices Firestore project.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from google.cloud.firestore_v1.base_query import FieldFilter
from firebase_admin import firestore

from app.config.firebase import get_supplies_db

logger = logging.getLogger(__name__)


class InvoiceService:
    DEFAULT_PAGE_SIZE = 50
    MAX_PAGE_SIZE = 100

    COLLECTION_TAX_INVOICES = 'tax_invoices'
    COLLECTION_INTERNAL_INVOICES = 'internal_invoices'
    COLLECTION_RECONCILIATION = 'invoice_reconciliation'

    SOURCE_TAX_PORTAL = 'TAX_PORTAL'
    SOURCE_AI_PDF = 'AI_PDF'

    # =========================================================================
    # HELPERS
    # =========================================================================

    @property
    def db(self):
        return get_supplies_db()

    def _get_collection_name(self, source: Optional[str]) -> str:
        if source == self.SOURCE_TAX_PORTAL:
            return self.COLLECTION_TAX_INVOICES
        elif source == self.SOURCE_AI_PDF:
            return self.COLLECTION_INTERNAL_INVOICES
        return self.COLLECTION_TAX_INVOICES

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        if not date_str:
            return None
        for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%Y/%m/%d', '%d.%m.%Y'):
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        return None

    def _normalize_date_string(self, date_str: str) -> str:
        parsed = self._parse_date(str(date_str))
        return parsed.strftime('%Y-%m-%d') if parsed else date_str

    def _detect_date_format(self, collection_name: str) -> str:
        try:
            docs = list(self.db.collection(collection_name).limit(5).stream())
            if not docs:
                return 'YYYY-MM-DD'
            # Sample multiple docs to detect the dominant format
            formats = {'TIMESTAMP': 0, 'YYYY-MM-DD': 0, 'DD/MM/YYYY': 0}
            for doc in docs:
                invoice_date = doc.to_dict().get('invoiceDate')
                if invoice_date is None:
                    continue
                if hasattr(invoice_date, 'isoformat'):
                    formats['TIMESTAMP'] += 1
                elif isinstance(invoice_date, str):
                    if '/' in invoice_date:
                        formats['DD/MM/YYYY'] += 1
                    elif '-' in invoice_date and len(invoice_date) == 10:
                        formats['YYYY-MM-DD'] += 1
            # Return most common format, prefer YYYY-MM-DD over DD/MM/YYYY
            if formats['TIMESTAMP'] > 0:
                return 'TIMESTAMP'
            if formats['YYYY-MM-DD'] >= formats['DD/MM/YYYY']:
                return 'YYYY-MM-DD'
            return 'DD/MM/YYYY'
        except Exception as e:
            logger.error(f"Error detecting date format: {e}")
        return 'YYYY-MM-DD'

    def _normalize_date_for_query(self, date_str: str, target_format: str = 'YYYY-MM-DD') -> Optional[str]:
        parsed = self._parse_date(date_str)
        if not parsed:
            return date_str
        if target_format == 'DD/MM/YYYY':
            return parsed.strftime('%d/%m/%Y')
        return parsed.strftime('%Y-%m-%d')

    def _normalize_invoice_data(self, data: Dict, source: str) -> Dict:
        invoice_date = data.get('invoiceDate', '')
        if hasattr(invoice_date, 'isoformat'):
            issue_date = invoice_date.isoformat()
        else:
            issue_date = invoice_date or ''

        supplier = data.get('supplier', {})
        normalized = {
            'invoiceNo': data.get('invoiceNo', ''),
            'invoiceSymbol': data.get('invoiceSymbol', ''),
            'invoiceKey': data.get('invoiceKey', ''),
            'issueDate': issue_date,
            'totalAmount': float(data.get('totalAmount', 0)),
            'vatAmount': float(data.get('vatAmount', 0)),
            'totalBeforeVat': float(data.get('totalBeforeVat', 0)),
            'vatRate': float(data.get('vatRate', 0)),
            'source': source,
            'supplierTaxCode': supplier.get('taxCode', '') or data.get('supplierTaxCode', '') or data.get('sellerTaxCode', ''),
            'supplierName': supplier.get('name', '') or data.get('supplierName', '') or data.get('sellerName', ''),
            'supplierAddress': supplier.get('address', '') or data.get('supplierAddress', '') or data.get('sellerAddress', ''),
            'reconcileStatus': data.get('reconcileStatus', 'PENDING'),
            'confidence': data.get('confidence', data.get('ocrConfidence', 0)),
            'items': data.get('items', []),
            'buyer': data.get('buyer', {}),
            # Portal/Email fields (internal_invoices)
            'portalUrl': data.get('portalUrl', ''),
            'portalPdfUrl': data.get('portalPdfUrl', ''),
            'invoiceProvider': data.get('invoiceProvider', ''),
            'portalCredentials': data.get('portalCredentials', {}),
            'sourceTab': data.get('sourceTab', ''),
            'gmailFrom': data.get('gmailFrom', ''),
            'gmailMessageId': data.get('gmailMessageId', ''),
            'gmailDate': data.get('gmailDate', ''),
            'processingMethod': data.get('processingMethod', ''),
            'attachmentType': data.get('attachmentType', ''),
        }
        created_at = data.get('createdAt')
        if created_at and hasattr(created_at, 'isoformat'):
            normalized['createdAt'] = created_at.isoformat()
        else:
            normalized['createdAt'] = created_at or ''
        return normalized

    # =========================================================================
    # QUERY
    # =========================================================================

    def get_invoices(
        self,
        source: Optional[str] = None,
        year: Optional[int] = None,
        month_key: Optional[str] = None,
        from_date: Optional[str] = None,
        to_date: Optional[str] = None,
        supplier_tax_code: Optional[str] = None,
        reconcile_status: Optional[str] = None,
        page_size: int = DEFAULT_PAGE_SIZE,
        cursor_doc_id: Optional[str] = None,
        direction: str = 'next'
    ) -> Dict:
        try:
            page_size = min(page_size, self.MAX_PAGE_SIZE)
            collection_name = self._get_collection_name(source)
            logger.info(f"[get_invoices] source={source}, collection={collection_name}, "
                        f"from_date={from_date}, to_date={to_date}, supplier={supplier_tax_code}, "
                        f"page_size={page_size}, cursor={cursor_doc_id}")

            # Convert year/month_key to date range
            if not from_date and not to_date:
                if month_key:
                    try:
                        year_part, month_part = month_key.split('-')
                        y, m = int(year_part), int(month_part)
                        from_date = f"{y}-{m:02d}-01"
                        if m == 12:
                            to_date = f"{y}-12-31"
                        else:
                            last_day = datetime(y, m + 1, 1) - timedelta(days=1)
                            to_date = last_day.strftime('%Y-%m-%d')
                    except Exception:
                        pass
                elif year:
                    from_date = f"{year}-01-01"
                    to_date = f"{year}-12-31"

            query = self.db.collection(collection_name)

            use_client_side_date = False
            parsed_from = None
            parsed_to = None

            if from_date or to_date:
                date_format = self._detect_date_format(collection_name)
                logger.info(f"[get_invoices] detected date_format={date_format}, from={from_date}, to={to_date}")
                if date_format == 'TIMESTAMP':
                    if from_date:
                        p = self._parse_date(from_date)
                        if p:
                            query = query.where(filter=FieldFilter('invoiceDate', '>=', p))
                    if to_date:
                        p = self._parse_date(to_date)
                        if p:
                            query = query.where(filter=FieldFilter('invoiceDate', '<=', p.replace(hour=23, minute=59, second=59)))
                elif date_format == 'YYYY-MM-DD':
                    if from_date:
                        norm = self._normalize_date_for_query(from_date, 'YYYY-MM-DD')
                        if norm:
                            query = query.where(filter=FieldFilter('invoiceDate', '>=', norm))
                    if to_date:
                        norm = self._normalize_date_for_query(to_date, 'YYYY-MM-DD')
                        if norm:
                            query = query.where(filter=FieldFilter('invoiceDate', '<=', norm))
                else:
                    use_client_side_date = True
                    parsed_from = self._parse_date(from_date) if from_date else None
                    parsed_to = self._parse_date(to_date) if to_date else None
                    if parsed_to:
                        parsed_to = parsed_to.replace(hour=23, minute=59, second=59)

            query = query.order_by('invoiceDate', direction=firestore.Query.DESCENDING)

            if cursor_doc_id:
                cursor_doc = self.db.collection(collection_name).document(cursor_doc_id).get()
                if cursor_doc.exists:
                    if direction == 'next':
                        query = query.start_after(cursor_doc)
                    else:
                        query = query.end_before(cursor_doc)

            # Fetch more docs when using client-side filtering to avoid empty pages
            needs_client_filter = use_client_side_date or supplier_tax_code or reconcile_status
            fetch_limit = (page_size * 5 + 1) if needs_client_filter else (page_size + 1)
            logger.info(f"[get_invoices] use_client_side_date={use_client_side_date}, "
                        f"needs_client_filter={needs_client_filter}, fetch_limit={fetch_limit}")

            docs = list(query.limit(fetch_limit).stream())
            logger.info(f"[get_invoices] Firestore returned {len(docs)} docs")

            invoices = []
            first_doc_id = None
            last_doc_id = None

            for doc in docs:
                if len(invoices) >= page_size:
                    break

                data = doc.to_dict()

                if use_client_side_date:
                    inv_date = self._parse_date(str(data.get('invoiceDate', '')))
                    if inv_date:
                        if parsed_from and inv_date < parsed_from:
                            continue
                        if parsed_to and inv_date > parsed_to:
                            continue

                if supplier_tax_code:
                    s = data.get('supplier', {})
                    doc_tax = s.get('taxCode', '') or data.get('supplierTaxCode', '') or data.get('sellerTaxCode', '')
                    if doc_tax != supplier_tax_code:
                        continue

                if reconcile_status:
                    if data.get('reconcileStatus', 'PENDING') != reconcile_status:
                        continue

                normalized = self._normalize_invoice_data(data, source or self.SOURCE_TAX_PORTAL)
                normalized['id'] = doc.id
                invoices.append(normalized)

                if first_doc_id is None:
                    first_doc_id = doc.id
                last_doc_id = doc.id

            has_next = len(docs) > fetch_limit - 1 or len(invoices) >= page_size
            logger.info(f"[get_invoices] After filtering: {len(invoices)} invoices, has_next={has_next}")
            if docs and len(invoices) < 3:
                # Log sample docs for debugging when few results
                for d in docs[:3]:
                    dd = d.to_dict()
                    logger.info(f"  sample doc: id={d.id}, invoiceDate={dd.get('invoiceDate')}, "
                                f"supplierTaxCode={dd.get('supplierTaxCode') or dd.get('supplier', {}).get('taxCode')}, "
                                f"invoiceNo={dd.get('invoiceNo')}")

            return {
                'invoices': invoices,
                'pagination': {
                    'hasNext': has_next,
                    'hasPrev': cursor_doc_id is not None,
                    'firstDocId': first_doc_id,
                    'lastDocId': last_doc_id,
                    'pageSize': page_size,
                    'count': len(invoices)
                }
            }

        except Exception as e:
            logger.error(f"Error querying invoices: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {
                'invoices': [],
                'pagination': {'hasNext': False, 'hasPrev': False, 'firstDocId': None, 'lastDocId': None, 'pageSize': page_size, 'count': 0},
                'error': str(e)
            }

    def get_invoices_default(self, source: Optional[str] = None) -> Dict:
        from_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        return self.get_invoices(source=source, from_date=from_date, page_size=self.DEFAULT_PAGE_SIZE)

    # =========================================================================
    # CREATE
    # =========================================================================

    def create_invoice(self, invoice_data: Dict, source: str) -> Tuple[bool, str, Optional[str]]:
        try:
            collection_name = self._get_collection_name(source)
            invoice_no = str(invoice_data.get('invoiceNo', '')).strip()

            if source == self.SOURCE_TAX_PORTAL:
                supplier_tax_code = str(invoice_data.get('sellerTaxCode', '') or invoice_data.get('supplierTaxCode', '')).strip()
            else:
                supplier_tax_code = str(invoice_data.get('supplierTaxCode', '') or invoice_data.get('supplier', {}).get('taxCode', '')).strip()

            if not invoice_no or not supplier_tax_code:
                return False, "Thiếu số hóa đơn hoặc MST nhà cung cấp", None

            invoice_symbol = str(invoice_data.get('invoiceSymbol', '')).strip()
            if invoice_symbol:
                invoice_key = f"{invoice_symbol}_{invoice_no}|{supplier_tax_code}"
            else:
                invoice_key = f"{invoice_no}|{supplier_tax_code}"

            existing = list(self.db.collection(collection_name).where(
                filter=FieldFilter('invoiceKey', '==', invoice_key)
            ).limit(1).get())

            if existing:
                return False, f"Hóa đơn {invoice_no} từ nguồn {source} đã tồn tại", None

            issue_date_str = invoice_data.get('invoiceDate', '') or invoice_data.get('issueDate', '')

            if source == self.SOURCE_TAX_PORTAL:
                supplier_name = invoice_data.get('sellerName', '') or invoice_data.get('supplierName', '')
                supplier_address = invoice_data.get('sellerAddress', '') or invoice_data.get('supplierAddress', '')
                items = []
                for item_data in invoice_data.get('items', []):
                    items.append({
                        'name': item_data.get('name', '') or item_data.get('itemName', ''),
                        'unit': item_data.get('unit', '') or item_data.get('unitName', ''),
                        'quantity': float(item_data.get('quantity', 0)),
                        'unitPrice': float(item_data.get('unitPrice', 0)),
                        'amount': float(item_data.get('amount', 0) or item_data.get('totalAmount', 0)),
                    })
                doc_data = {
                    'invoiceNo': invoice_no,
                    'invoiceSymbol': invoice_symbol,
                    'invoiceDate': issue_date_str,
                    'invoiceKey': invoice_key,
                    'supplier': {'name': supplier_name, 'taxCode': supplier_tax_code, 'address': supplier_address},
                    'buyer': {
                        'name': invoice_data.get('buyerName', ''),
                        'taxCode': invoice_data.get('buyerTaxCode', ''),
                        'address': invoice_data.get('buyerAddress', ''),
                    },
                    'items': items,
                    'totalBeforeVat': float(invoice_data.get('totalBeforeVat', 0)),
                    'vatRate': float(invoice_data.get('vatRate', 0)),
                    'vatAmount': float(invoice_data.get('vatAmount', 0)),
                    'totalAmount': float(invoice_data.get('totalAmount', 0)),
                    'source': 'gdt',
                    'createdAt': datetime.utcnow()
                }
            else:
                supplier = invoice_data.get('supplier', {})
                supplier_name = supplier.get('name', '') or invoice_data.get('supplierName', '')
                supplier_address = supplier.get('address', '') or invoice_data.get('supplierAddress', '')
                items = []
                for item in invoice_data.get('items', []):
                    items.append({
                        'name': item.get('name', ''),
                        'unit': item.get('unit', ''),
                        'quantity': float(item.get('quantity', 0)),
                        'unitPrice': float(item.get('unitPrice', 0)),
                        'amount': float(item.get('amount', 0))
                    })
                doc_data = {
                    'invoiceNo': invoice_no,
                    'invoiceSymbol': invoice_symbol,
                    'invoiceDate': issue_date_str,
                    'invoiceKey': invoice_key,
                    'supplier': {'name': supplier_name, 'taxCode': supplier_tax_code, 'address': supplier_address},
                    'buyer': invoice_data.get('buyer', {}),
                    'items': items,
                    'totalBeforeVat': float(invoice_data.get('totalBeforeVat', 0)),
                    'vatRate': float(invoice_data.get('vatRate', 0)),
                    'vatAmount': float(invoice_data.get('vatAmount', 0)),
                    'totalAmount': float(invoice_data.get('totalAmount', 0)),
                    'source': 'ai_pdf',
                    'aiModel': invoice_data.get('aiModel', 'gemini-3-flash'),
                    'confidence': float(invoice_data.get('confidence', 0)),
                    'createdAt': datetime.utcnow(),
                    # Portal/Email fields
                    'sourceTab': invoice_data.get('sourceTab', ''),
                    'gmailMessageId': invoice_data.get('gmailMessageId', ''),
                    'gmailFrom': invoice_data.get('gmailFrom', ''),
                    'gmailDate': invoice_data.get('gmailDate', ''),
                    'portalUrl': invoice_data.get('portalUrl', ''),
                    'portalPdfUrl': invoice_data.get('portalPdfUrl', ''),
                    'invoiceProvider': invoice_data.get('invoiceProvider', ''),
                    'portalCredentials': invoice_data.get('portalCredentials', {}),
                    'processingMethod': invoice_data.get('processingMethod', ''),
                    'attachmentType': invoice_data.get('attachmentType', ''),
                }

            doc_ref = self.db.collection(collection_name).add(doc_data)
            return True, "Tạo hóa đơn thành công", doc_ref[1].id

        except Exception as e:
            logger.error(f"Error creating invoice: {e}")
            return False, f"Lỗi: {str(e)}", None

    def batch_import_invoices(self, invoices: List[Dict], source: str) -> Dict:
        imported = duplicates = failed = 0
        errors = []
        for inv in invoices:
            ok, msg, doc_id = self.create_invoice(inv, source)
            if ok:
                imported += 1
            elif 'đã tồn tại' in msg:
                duplicates += 1
            else:
                failed += 1
                errors.append(f"{inv.get('invoiceNo', 'N/A')}: {msg}")
        return {
            'success': failed == 0,
            'imported': imported,
            'duplicates': duplicates,
            'failed': failed,
            'errors': errors[:10]
        }

    # =========================================================================
    # SUPPLIERS
    # =========================================================================

    def get_suppliers(self, search: Optional[str] = None, limit: int = 50) -> List[Dict]:
        try:
            suppliers_map: Dict = {}

            for col, tax_code_field in [
                (self.COLLECTION_TAX_INVOICES, 'sellerTaxCode'),
                (self.COLLECTION_INTERNAL_INVOICES, 'supplierTaxCode')
            ]:
                for doc in self.db.collection(col).stream():
                    data = doc.to_dict()
                    s = data.get('supplier', {})
                    tax_code = s.get('taxCode', '') or data.get(tax_code_field, '')
                    name = s.get('name', '') or data.get('supplierName', '') or data.get('sellerName', '')
                    address = s.get('address', '') or data.get('supplierAddress', '') or data.get('sellerAddress', '')
                    if not tax_code:
                        continue
                    if tax_code in suppliers_map:
                        suppliers_map[tax_code]['invoiceCount'] += 1
                    else:
                        suppliers_map[tax_code] = {'id': tax_code, 'taxCode': tax_code, 'name': name, 'address': address, 'invoiceCount': 1}

            suppliers = list(suppliers_map.values())
            suppliers.sort(key=lambda x: x['invoiceCount'], reverse=True)

            if search:
                sl = search.lower()
                suppliers = [s for s in suppliers if sl in s['name'].lower() or sl in s['taxCode'].lower()]

            return suppliers[:limit]

        except Exception as e:
            logger.error(f"Error getting suppliers: {e}")
            return []

    def get_providers(self) -> List[Dict]:
        try:
            providers: Dict = {}
            for doc in self.db.collection(self.COLLECTION_INTERNAL_INVOICES).select(['invoiceProvider']).limit(1000).stream():
                p = doc.to_dict().get('invoiceProvider', '')
                if p:
                    providers[p] = providers.get(p, 0) + 1
            return [{'name': n, 'count': c} for n, c in sorted(providers.items(), key=lambda x: x[1], reverse=True)]
        except Exception as e:
            logger.error(f"Error getting providers: {e}")
            return []

    # =========================================================================
    # DELETE
    # =========================================================================

    def clear_invoices_by_source(self, source: str) -> Dict:
        try:
            collection_name = self._get_collection_name(source)
            docs = self.db.collection(collection_name).stream()
            deleted = 0
            batch = self.db.batch()
            batch_count = 0
            for doc in docs:
                batch.delete(doc.reference)
                batch_count += 1
                deleted += 1
                if batch_count >= 500:
                    batch.commit()
                    batch = self.db.batch()
                    batch_count = 0
            if batch_count > 0:
                batch.commit()
            return {'success': True, 'deleted': deleted}
        except Exception as e:
            logger.error(f"Error clearing invoices: {e}")
            return {'success': False, 'deleted': 0, 'error': str(e)}

    def clear_all_invoices(self) -> Dict:
        tax = self.clear_invoices_by_source(self.SOURCE_TAX_PORTAL)
        ai = self.clear_invoices_by_source(self.SOURCE_AI_PDF)
        return {
            'success': tax['success'] and ai['success'],
            'taxDeleted': tax.get('deleted', 0),
            'aiDeleted': ai.get('deleted', 0)
        }

    # =========================================================================
    # RECONCILIATION
    # =========================================================================

    def get_reconciliation_summary(self, month_key: Optional[str] = None, year: Optional[int] = None) -> Dict:
        try:
            tax_docs = list(self.db.collection(self.COLLECTION_TAX_INVOICES).stream())
            ai_docs = list(self.db.collection(self.COLLECTION_INTERNAL_INVOICES).stream())
            recon_docs = list(self.db.collection(self.COLLECTION_RECONCILIATION).stream())

            matched = unmatched = mismatch = 0
            for doc in recon_docs:
                status = doc.to_dict().get('status', '')
                if status == 'MATCH':
                    matched += 1
                elif status in ('MISSING_INTERNAL', 'MISSING_TAX'):
                    unmatched += 1
                elif status == 'MISMATCH':
                    mismatch += 1

            return {
                'taxPortalCount': len(tax_docs),
                'aiPdfCount': len(ai_docs),
                'matchedCount': matched,
                'unmatchedCount': unmatched,
                'mismatchCount': mismatch
            }
        except Exception as e:
            logger.error(f"Error getting reconciliation summary: {e}")
            return {'taxPortalCount': 0, 'aiPdfCount': 0, 'matchedCount': 0, 'unmatchedCount': 0, 'mismatchCount': 0, 'error': str(e)}

    def run_reconciliation(self, month_key: Optional[str] = None) -> Dict:
        try:
            tax_docs = list(self.db.collection(self.COLLECTION_TAX_INVOICES).stream())
            internal_docs = list(self.db.collection(self.COLLECTION_INTERNAL_INVOICES).stream())

            def match_key(data: Dict, tax_code_field: str) -> str:
                invoice_no = data.get('invoiceNo', '')
                s = data.get('supplier', {})
                tax_code = s.get('taxCode', '') or data.get(tax_code_field, '')
                return f"{invoice_no}|{tax_code}"

            def display_key(data: Dict, tax_code_field: str) -> str:
                invoice_no = data.get('invoiceNo', '')
                symbol = data.get('invoiceSymbol', '')
                s = data.get('supplier', {})
                tax_code = s.get('taxCode', '') or data.get(tax_code_field, '')
                return f"{symbol}_{invoice_no}|{tax_code}" if symbol else f"{invoice_no}|{tax_code}"

            tax_map = {}
            for doc in tax_docs:
                d = doc.to_dict()
                d['id'] = doc.id
                d['_displayKey'] = display_key(d, 'sellerTaxCode')
                tax_map[match_key(d, 'sellerTaxCode')] = d

            internal_map = {}
            for doc in internal_docs:
                d = doc.to_dict()
                d['id'] = doc.id
                d['_displayKey'] = display_key(d, 'supplierTaxCode')
                internal_map[match_key(d, 'supplierTaxCode')] = d

            all_keys = set(tax_map.keys()) | set(internal_map.keys())
            reconciliations = []
            summary = {'totalTax': len(tax_docs), 'totalInternal': len(internal_docs), 'matched': 0, 'missingInternal': 0, 'missingTax': 0, 'mismatch': 0}

            for key in all_keys:
                tax_inv = tax_map.get(key)
                internal_inv = internal_map.get(key)

                dk = key
                if tax_inv and tax_inv.get('_displayKey'):
                    dk = tax_inv['_displayKey']
                elif internal_inv and internal_inv.get('_displayKey'):
                    dk = internal_inv['_displayKey']

                rec = {
                    'invoiceKey': dk,
                    'matchKey': key,
                    'taxInvoiceId': tax_inv['id'] if tax_inv else None,
                    'internalInvoiceId': internal_inv['id'] if internal_inv else None,
                    'status': None,
                    'fieldDiffs': [],
                    'checkedAt': datetime.utcnow()
                }

                if tax_inv and internal_inv:
                    diffs = self._compare_invoice_fields(tax_inv, internal_inv)
                    if not diffs:
                        rec['status'] = 'MATCH'
                        summary['matched'] += 1
                    else:
                        rec['status'] = 'MISMATCH'
                        rec['fieldDiffs'] = diffs
                        summary['mismatch'] += 1
                elif tax_inv:
                    rec['status'] = 'MISSING_INTERNAL'
                    summary['missingInternal'] += 1
                else:
                    rec['status'] = 'MISSING_TAX'
                    summary['missingTax'] += 1

                if tax_inv:
                    ts = tax_inv.get('supplier', {}) or tax_inv.get('seller', {})
                    tb = tax_inv.get('buyer', {})
                    rec['taxData'] = {
                        'invoiceNo': tax_inv.get('invoiceNo', ''),
                        'invoiceSymbol': tax_inv.get('invoiceSymbol', ''),
                        'invoiceDate': tax_inv.get('invoiceDate', ''),
                        'supplierName': ts.get('name', '') or tax_inv.get('sellerName', '') or tax_inv.get('supplierName', ''),
                        'supplierTaxCode': ts.get('taxCode', '') or tax_inv.get('sellerTaxCode', '') or tax_inv.get('supplierTaxCode', ''),
                        'supplierAddress': ts.get('address', '') or tax_inv.get('sellerAddress', '') or tax_inv.get('supplierAddress', ''),
                        'buyerName': tb.get('name', '') or tax_inv.get('buyerName', ''),
                        'buyerTaxCode': tb.get('taxCode', '') or tax_inv.get('buyerTaxCode', ''),
                        'totalBeforeVat': tax_inv.get('totalBeforeVat', 0),
                        'vatRate': tax_inv.get('vatRate', 0),
                        'vatAmount': tax_inv.get('vatAmount', 0),
                        'totalAmount': tax_inv.get('totalAmount', 0),
                        'items': tax_inv.get('items', [])
                    }

                if internal_inv:
                    s = internal_inv.get('supplier', {})
                    b = internal_inv.get('buyer', {})
                    rec['internalData'] = {
                        'invoiceNo': internal_inv.get('invoiceNo', ''),
                        'invoiceSymbol': internal_inv.get('invoiceSymbol', ''),
                        'invoiceDate': internal_inv.get('invoiceDate', ''),
                        'supplierName': s.get('name', '') or internal_inv.get('supplierName', ''),
                        'supplierTaxCode': s.get('taxCode', '') or internal_inv.get('supplierTaxCode', ''),
                        'supplierAddress': s.get('address', '') or internal_inv.get('supplierAddress', ''),
                        'buyerName': b.get('name', '') or internal_inv.get('buyerName', ''),
                        'buyerTaxCode': b.get('taxCode', '') or internal_inv.get('buyerTaxCode', ''),
                        'totalBeforeVat': internal_inv.get('totalBeforeVat', 0),
                        'vatRate': internal_inv.get('vatRate', 0),
                        'vatAmount': internal_inv.get('vatAmount', 0),
                        'totalAmount': internal_inv.get('totalAmount', 0),
                        'items': internal_inv.get('items', [])
                    }

                reconciliations.append(rec)

            self._save_reconciliation_results(reconciliations, month_key)
            self._update_reconcile_status(reconciliations)

            return {
                'success': True,
                'processed': len(all_keys),
                'matched': summary['matched'],
                'unmatched': summary['missingInternal'] + summary['missingTax'],
                'mismatch': summary['mismatch'],
                'summary': summary
            }

        except Exception as e:
            logger.error(f"Error running reconciliation: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return {'success': False, 'error': str(e)}

    def _save_reconciliation_results(self, reconciliations: List[Dict], month_key: Optional[str] = None):
        try:
            period_key = month_key or 'all'
            for doc in self.db.collection(self.COLLECTION_RECONCILIATION).where(filter=FieldFilter('periodKey', '==', period_key)).stream():
                doc.reference.delete()

            batch = self.db.batch()
            batch_count = 0
            for rec in reconciliations:
                rec['periodKey'] = period_key
                doc_ref = self.db.collection(self.COLLECTION_RECONCILIATION).document()
                batch.set(doc_ref, rec)
                batch_count += 1
                if batch_count >= 500:
                    batch.commit()
                    batch = self.db.batch()
                    batch_count = 0
            if batch_count > 0:
                batch.commit()
        except Exception as e:
            logger.error(f"Error saving reconciliation results: {e}")

    def _update_reconcile_status(self, reconciliations: List[Dict]):
        try:
            status_map = {'MATCH': 'MATCHED', 'MISMATCH': 'MISMATCH', 'MISSING_INTERNAL': 'UNMATCHED', 'MISSING_TAX': 'UNMATCHED'}
            batch = self.db.batch()
            batch_count = 0
            for rec in reconciliations:
                inv_status = status_map.get(rec.get('status', ''), 'PENDING')
                if rec.get('taxInvoiceId'):
                    ref = self.db.collection(self.COLLECTION_TAX_INVOICES).document(rec['taxInvoiceId'])
                    batch.update(ref, {'reconcileStatus': inv_status, 'matchedInvoiceId': rec.get('internalInvoiceId'), 'reconciledAt': datetime.utcnow()})
                    batch_count += 1
                if rec.get('internalInvoiceId'):
                    ref = self.db.collection(self.COLLECTION_INTERNAL_INVOICES).document(rec['internalInvoiceId'])
                    batch.update(ref, {'reconcileStatus': inv_status, 'matchedInvoiceId': rec.get('taxInvoiceId'), 'reconciledAt': datetime.utcnow()})
                    batch_count += 1
                if batch_count >= 500:
                    batch.commit()
                    batch = self.db.batch()
                    batch_count = 0
            if batch_count > 0:
                batch.commit()
        except Exception as e:
            logger.error(f"Error updating reconcile status: {e}")

    def _compare_invoice_fields(self, tax_inv: Dict, internal_inv: Dict) -> List[Dict]:
        diffs = []

        def get_supplier(inv: Dict):
            s = inv.get('supplier', {})
            return (s.get('name', '') or inv.get('supplierName', ''), s.get('taxCode', '') or inv.get('supplierTaxCode', ''))

        tax_sname, tax_stax = get_supplier(tax_inv)
        int_sname, int_stax = get_supplier(internal_inv)

        fields = [
            ('totalAmount', 'totalAmount', 'Tổng tiền thanh toán', 'number', 1),
            ('vatAmount', 'vatAmount', 'Tiền thuế GTGT', 'number', 1),
            ('totalBeforeVat', 'totalBeforeVat', 'Tổng tiền trước thuế', 'number', 1),
            ('invoiceNo', 'invoiceNo', 'Số hóa đơn', 'string', 0),
            ('invoiceSymbol', 'invoiceSymbol', 'Ký hiệu hóa đơn', 'string', 0),
            ('invoiceDate', 'invoiceDate', 'Ngày hóa đơn', 'date', 0),
            ('vatRate', 'vatRate', 'Thuế suất (%)', 'number', 0),
        ]

        for tf, inf, label, dtype, tol in fields:
            tv = tax_inv.get(tf)
            iv = internal_inv.get(inf)
            if tv is None:
                tv = 0 if dtype == 'number' else ''
            if iv is None:
                iv = 0 if dtype == 'number' else ''

            has_diff = False
            diff_val = None

            if dtype == 'number':
                tn, iv_n = float(tv) if tv else 0, float(iv) if iv else 0
                diff_val = tn - iv_n
                has_diff = abs(diff_val) > tol
            elif dtype == 'string':
                ts, is_ = str(tv).strip().lower(), str(iv).strip().lower()
                if tf == 'invoiceNo':
                    ts, is_ = ts.lstrip('0') or '0', is_.lstrip('0') or '0'
                has_diff = ts != is_
                diff_val = f"'{tv}' vs '{iv}'"
            elif dtype == 'date':
                has_diff = self._normalize_date_string(str(tv)) != self._normalize_date_string(str(iv))
                diff_val = f"'{tv}' vs '{iv}'"

            if has_diff:
                diffs.append({'field': tf, 'fieldLabel': label, 'taxValue': tv, 'internalValue': iv, 'diff': diff_val, 'diffType': dtype})

        if tax_sname.lower() != int_sname.lower():
            diffs.append({'field': 'supplierName', 'fieldLabel': 'Tên nhà cung cấp', 'taxValue': tax_sname, 'internalValue': int_sname, 'diff': f"'{tax_sname}' vs '{int_sname}'", 'diffType': 'string'})

        if tax_stax != int_stax:
            diffs.append({'field': 'supplierTaxCode', 'fieldLabel': 'MST nhà cung cấp', 'taxValue': tax_stax, 'internalValue': int_stax, 'diff': f"'{tax_stax}' vs '{int_stax}'", 'diffType': 'string'})

        return diffs


invoice_service = InvoiceService()
