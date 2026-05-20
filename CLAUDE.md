# TapHoa39KeToanBackEnd

FastAPI backend ke toan. Firebase project: `songminhketoan-15041989`.

## Architecture
`HTTP Request → app/routes/*.py → app/services/*.py → Firestore`

## API
- `/api/cash-vouchers` - CRUD phieu thu/chi + stats
- `/api/warehouse-vouchers` - CRUD phieu nhap/xuat kho + stats
- Swagger: `/docs`, ReDoc: `/redoc`

## Critical Rules
- Voucher: DRAFT → POSTED → CANCELLED (chi sua/xoa khi DRAFT)
- Auto-numbering: PT/PC/PNK/PXK + year + seq (VD: PT202501001)
- Firestore: `cash_vouchers`, `warehouse_vouchers`, `counters`
- Firebase creds: env `FIREBASE_SERVICE_ACCOUNT_KETOAN` > file > default
- CORS: localhost:4200, host 0.0.0.0:8000
