"""
Invoice Routes — KeToanBackEnd
All invoice API endpoints.
- /api/v2/invoices  — full v2 CRUD + reconciliation
- /api/invoices     — legacy read-only endpoints (backward compat)
"""
from fastapi import APIRouter, Query, HTTPException, UploadFile, File
from fastapi.responses import JSONResponse
from typing import Optional, List
from google.cloud.firestore_v1 import FieldFilter

from app.config.firebase import get_supplies_db
from app.services.invoice_service import invoice_service

# ============================================================================
# V2 ROUTER  /api/v2/invoices
# ============================================================================

router = APIRouter(prefix='/api/v2/invoices', tags=['Invoices V2'])


@router.get('')
async def get_invoices(
    source: Optional[str] = Query(None),
    year: Optional[int] = Query(None),
    month_key: Optional[str] = Query(None, alias='monthKey'),
    from_date: Optional[str] = Query(None, alias='fromDate'),
    to_date: Optional[str] = Query(None, alias='toDate'),
    supplier_tax_code: Optional[str] = Query(None, alias='supplierTaxCode'),
    reconcile_status: Optional[str] = Query(None, alias='reconcileStatus'),
    page_size: int = Query(50, alias='pageSize', ge=1, le=100),
    cursor: Optional[str] = Query(None),
    direction: Optional[str] = Query('next')
):
    return invoice_service.get_invoices(
        source=source, year=year, month_key=month_key,
        from_date=from_date, to_date=to_date,
        supplier_tax_code=supplier_tax_code, reconcile_status=reconcile_status,
        page_size=page_size, cursor_doc_id=cursor, direction=direction
    )


@router.get('/default')
async def get_invoices_default(source: Optional[str] = Query(None)):
    return invoice_service.get_invoices_default(source=source)


@router.get('/suppliers')
async def get_suppliers(
    search: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500)
):
    suppliers = invoice_service.get_suppliers(search=search, limit=limit)
    return {'suppliers': suppliers, 'count': len(suppliers)}


@router.get('/providers')
async def get_providers():
    return {'providers': invoice_service.get_providers()}


@router.get('/reconciliation/summary')
async def get_reconciliation_summary(
    month_key: Optional[str] = Query(None, alias='monthKey'),
    year: Optional[int] = Query(None)
):
    return invoice_service.get_reconciliation_summary(month_key=month_key, year=year)


@router.post('/reconciliation/run')
async def run_reconciliation(data: dict = {}):
    month_key = data.get('monthKey') if data else None
    return invoice_service.run_reconciliation(month_key=month_key)


@router.get('/reconciliation/results')
async def get_reconciliation_results(
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500)
):
    db = get_supplies_db()
    query = db.collection('invoice_reconciliation')
    if status:
        query = query.where(filter=FieldFilter('status', '==', status))
    docs = list(query.limit(limit).stream())
    results = []
    for doc in docs:
        d = doc.to_dict()
        for ts_field in ('checkedAt', 'reconciledAt'):
            if ts_field in d and hasattr(d[ts_field], 'isoformat'):
                d[ts_field] = d[ts_field].isoformat()
        d['id'] = doc.id
        results.append(d)
    return {'results': results, 'count': len(results)}


@router.post('/reconciliation/save-live')
async def save_live_reconciliation(data: dict = {}):
    """Save live reconciliation results (Gmail vs GDT) to Firestore."""
    results = data.get('results', [])
    if not results:
        return {'success': False, 'error': 'No results to save', 'saved': 0}

    db = get_supplies_db()
    from datetime import datetime

    # Clear previous live reconciliation results
    for doc in db.collection('invoice_reconciliation').where(filter=FieldFilter('periodKey', '==', 'live')).stream():
        doc.reference.delete()

    # Save new results in batches
    batch = db.batch()
    batch_count = 0
    for rec in results:
        rec['periodKey'] = 'live'
        rec['source'] = 'live'
        rec['checkedAt'] = datetime.utcnow()
        doc_ref = db.collection('invoice_reconciliation').document()
        batch.set(doc_ref, rec)
        batch_count += 1
        if batch_count >= 500:
            batch.commit()
            batch = db.batch()
            batch_count = 0
    if batch_count > 0:
        batch.commit()

    return {'success': True, 'saved': len(results)}


@router.delete('/reconciliation/results/{result_id}')
async def delete_reconciliation_result(result_id: str):
    db = get_supplies_db()
    doc_ref = db.collection('invoice_reconciliation').document(result_id)
    if not doc_ref.get().exists:
        raise HTTPException(status_code=404, detail='Không tìm thấy kết quả đối chiếu')
    doc_ref.delete()
    return {'success': True, 'message': 'Đã xóa kết quả đối chiếu'}


@router.delete('/clear')
async def clear_invoices(source: Optional[str] = Query(None)):
    if not source:
        raise HTTPException(status_code=400, detail='Thiếu tham số source')
    return invoice_service.clear_invoices_by_source(source)


@router.delete('/clear-all')
async def clear_all_invoices():
    return invoice_service.clear_all_invoices()


@router.post('')
async def create_invoice(data: dict):
    source = data.get('source', 'AI_PDF')
    success, message, doc_id = invoice_service.create_invoice(data, source)
    return JSONResponse(
        status_code=200 if success else 400,
        content={'success': success, 'message': message, 'docId': doc_id}
    )


@router.post('/batch')
async def batch_import(data: dict):
    source = data.get('source', 'AI_PDF')
    invoices = data.get('invoices', [])
    if not invoices:
        raise HTTPException(status_code=400, detail='Không có hóa đơn để import')
    return invoice_service.batch_import_invoices(invoices, source)


@router.post('/import-xml')
async def import_xml(files: List[UploadFile] = File(...)):
    from app.services.invoice_parsers import TaxInvoiceXMLParser
    all_invoices = []
    parse_errors = []
    for file in files:
        if not file.filename:
            continue
        try:
            content = await file.read()
            invs, errors = TaxInvoiceXMLParser.parse(content)
            all_invoices.extend(invs)
            parse_errors.extend(errors)
        except Exception as e:
            parse_errors.append(f"{file.filename}: {str(e)}")

    if not all_invoices:
        return JSONResponse(status_code=400, content={
            'success': False, 'error': 'Không parse được hóa đơn nào', 'parseErrors': parse_errors
        })

    unified = [{
        'invoiceNo': inv.get('invoiceNo', ''),
        'invoiceSymbol': inv.get('invoiceSymbol', ''),
        'invoiceDate': inv.get('invoiceDate', ''),
        'sellerName': inv.get('sellerName', ''),
        'supplierTaxCode': inv.get('sellerTaxCode', ''),
        'sellerTaxCode': inv.get('sellerTaxCode', ''),
        'sellerAddress': inv.get('sellerAddress', ''),
        'buyerName': inv.get('buyerName', ''),
        'buyerTaxCode': inv.get('buyerTaxCode', ''),
        'buyerAddress': inv.get('buyerAddress', ''),
        'totalBeforeVat': inv.get('totalBeforeVat', 0),
        'vatRate': inv.get('vatRate', 0),
        'vatAmount': inv.get('vatAmount', 0),
        'totalAmount': inv.get('totalAmount', 0),
        'items': inv.get('items', [])
    } for inv in all_invoices]

    result = invoice_service.batch_import_invoices(unified, invoice_service.SOURCE_TAX_PORTAL)
    result['parseErrors'] = parse_errors
    return result


@router.get('/{doc_id}')
async def get_invoice_detail(doc_id: str, source: Optional[str] = Query('AI_PDF')):
    collection = invoice_service._get_collection_name(source)
    db = get_supplies_db()
    doc = db.collection(collection).document(doc_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail='Invoice not found')
    data = doc.to_dict()
    if 'createdAt' in data and hasattr(data['createdAt'], 'isoformat'):
        data['createdAt'] = data['createdAt'].isoformat()
    data['id'] = doc.id
    return {'invoice': data}


# ============================================================================
# LEGACY ROUTER  /api/invoices  (backward compat — read-only)
# ============================================================================

legacy_router = APIRouter(prefix='/api/invoices', tags=['Invoices'])


@legacy_router.get('/internal')
async def get_internal_invoices(
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    month_key: Optional[str] = Query(None, alias='monthKey'),
    year: Optional[int] = Query(None),
    supplier_tax_code: Optional[str] = Query(None, alias='supplierTaxCode'),
    invoice_provider: Optional[str] = Query(None, alias='invoiceProvider'),
    page_size: int = Query(50, alias='pageSize', ge=1, le=200),
    cursor: Optional[str] = Query(None),
    direction: Optional[str] = Query('next')
):
    import logging
    log = logging.getLogger(__name__)
    log.info(f"[/api/invoices/internal] from_date={from_date}, to_date={to_date}, "
             f"supplier={supplier_tax_code}, provider={invoice_provider}, pageSize={page_size}")
    result = invoice_service.get_invoices(
        source='AI_PDF',
        from_date=from_date, to_date=to_date, month_key=month_key, year=year,
        supplier_tax_code=supplier_tax_code,
        page_size=page_size, cursor_doc_id=cursor, direction=direction
    )
    log.info(f"[/api/invoices/internal] service returned {len(result.get('invoices', []))} invoices")
    if invoice_provider and result.get('invoices'):
        before = len(result['invoices'])
        result['invoices'] = [i for i in result['invoices'] if i.get('invoiceProvider') == invoice_provider]
        result['pagination']['count'] = len(result['invoices'])
        log.info(f"[/api/invoices/internal] provider filter '{invoice_provider}': {before} -> {len(result['invoices'])}")
    return result


@legacy_router.get('/internal/{doc_id}')
async def get_internal_invoice_detail(doc_id: str):
    db = get_supplies_db()
    doc = db.collection('internal_invoices').document(doc_id).get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail='Invoice not found')
    data = doc.to_dict()
    if 'createdAt' in data and hasattr(data['createdAt'], 'isoformat'):
        data['createdAt'] = data['createdAt'].isoformat()
    data['id'] = doc.id
    return {'invoice': data}


@legacy_router.get('/suppliers')
async def legacy_get_suppliers(
    limit: int = Query(50, ge=1, le=500),
    search: Optional[str] = Query(None)
):
    suppliers = invoice_service.get_suppliers(search=search, limit=limit)
    return {'suppliers': suppliers, 'count': len(suppliers)}


@legacy_router.get('/providers')
async def legacy_get_providers():
    return {'providers': invoice_service.get_providers()}
