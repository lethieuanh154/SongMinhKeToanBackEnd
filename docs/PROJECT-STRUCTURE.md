# TapHoa39KeToanBackEnd - Cấu Trúc Dự Án

## Tổng Quan

FastAPI backend kế toán hộ kinh doanh, chuẩn TT 133/2016 + TT 78/2021. Firebase project: `songminhketoan-15041989`.

- **Framework:** FastAPI 0.109
- **Entry point:** `main.py`
- **Dev server:** `uvicorn main:app --host 0.0.0.0 --port 8000 --reload`
- **Swagger:** `/docs` | **ReDoc:** `/redoc`

---

## Cấu Trúc Thư Mục

```
TapHoa39KeToanBackEnd/
├── main.py                          # FastAPI app entry point
├── requirements.txt                 # Python dependencies
├── .env                             # Firebase credentials
│
├── app/
│   ├── config/
│   │   ├── settings.py              # Environment & config
│   │   └── firebase.py              # Firebase initialization
│   │
│   ├── models/
│   │   ├── cash_voucher.py          # Phiếu Thu/Chi (Pydantic)
│   │   └── warehouse_voucher.py     # Phiếu Nhập/Xuất Kho (Pydantic)
│   │
│   ├── routes/
│   │   ├── cash_voucher_routes.py   # /api/cash-vouchers
│   │   ├── warehouse_voucher_routes.py # /api/warehouse-vouchers
│   │   ├── hddt_proxy_routes.py     # /api/hddt-proxy (tax authority)
│   │   ├── invoice_routes.py        # /api/invoices
│   │   └── gmail_routes.py          # /api/gmail
│   │
│   └── services/
│       ├── cash_voucher_service.py  # Cash voucher logic
│       ├── warehouse_voucher_service.py # Warehouse voucher logic
│       ├── invoice_service.py       # Invoice CRUD + reconciliation
│       ├── gmail_service.py         # Email sync & parsing
│       ├── invoice_parsers.py       # XML parser (7 vendor formats)
│       ├── email_body_parser.py     # Email content extraction
│       ├── playwright_scraper.py    # Tax portal scraper
│       └── zip_extractor.py         # Invoice file extraction
│
└── docs/                            # Documentation
```

---

## API Endpoints

### Cash Vouchers (`/api/cash-vouchers`)
| Method | Path | Mô tả |
|--------|------|-------|
| GET | `/api/cash-vouchers` | Danh sách phiếu thu/chi |
| GET | `/api/cash-vouchers/{id}` | Chi tiết phiếu |
| POST | `/api/cash-vouchers` | Tạo phiếu mới |
| PUT | `/api/cash-vouchers/{id}` | Cập nhật phiếu |
| DELETE | `/api/cash-vouchers/{id}` | Xóa phiếu |
| GET | `/api/cash-vouchers/stats` | Thống kê thu/chi |

### Warehouse Vouchers (`/api/warehouse-vouchers`)
| Method | Path | Mô tả |
|--------|------|-------|
| GET | `/api/warehouse-vouchers` | Danh sách phiếu nhập/xuất |
| GET | `/api/warehouse-vouchers/{id}` | Chi tiết phiếu |
| POST | `/api/warehouse-vouchers` | Tạo phiếu mới |
| PUT | `/api/warehouse-vouchers/{id}` | Cập nhật phiếu |
| DELETE | `/api/warehouse-vouchers/{id}` | Xóa phiếu |
| GET | `/api/warehouse-vouchers/stats` | Thống kê kho |

### Invoices (`/api/invoices`)
| Method | Path | Mô tả |
|--------|------|-------|
| GET | `/api/invoices` | Danh sách hóa đơn |
| POST | `/api/invoices` | Import hóa đơn |
| PUT | `/api/invoices/{id}` | Cập nhật hóa đơn |
| DELETE | `/api/invoices/{id}` | Xóa hóa đơn |

### HDDT Proxy (`/api/hddt-proxy`)
- Proxy tới cổng thuế điện tử

### Gmail (`/api/gmail`)
- Đồng bộ email hóa đơn

---

## Voucher Status Flow

```
DRAFT → POSTED → CANCELLED
```

- Chỉ sửa/xóa khi trạng thái `DRAFT`
- `POSTED`: đã ghi sổ, không thể sửa
- `CANCELLED`: đã hủy

---

## Auto-Numbering

| Loại | Format | Ví dụ |
|------|--------|-------|
| Phiếu Thu | PT + year + seq | PT202501001 |
| Phiếu Chi | PC + year + seq | PC202501001 |
| Phiếu Nhập Kho | PNK + year + seq | PNK202501001 |
| Phiếu Xuất Kho | PXK + year + seq | PXK202501001 |

Sequence lưu trong Firestore collection `counters`.

---

## Firestore Schema

| Collection | Mô tả |
|-----------|-------|
| `cash_vouchers` | Phiếu thu/chi |
| `warehouse_vouchers` | Phiếu nhập/xuất kho |
| `invoices` | Hóa đơn mua hàng |
| `suppliers` | Nhà cung cấp |
| `counters` | Auto-numbering sequences |
| `sync_logs` | Audit trail |

### Invoice Model

| Field | Type | Mô tả |
|-------|------|-------|
| `invoiceKey` | string | Unique key |
| `invoiceNo` | string | Số hóa đơn |
| `invoiceSymbol` | string | Ký hiệu hóa đơn |
| `supplierName` | string | Tên NCC |
| `supplierTaxCode` | string | MST NCC |
| `issueDate` | string | Ngày phát hành |
| `totalBeforeVat` | number | Tiền trước thuế |
| `vatRate` | number | Thuế suất |
| `vatAmount` | number | Tiền thuế |
| `totalAmount` | number | Tổng tiền |
| `reconcileStatus` | string | PENDING/MATCHED/UNMATCHED/MISMATCH |
| `source` | string | TAX_PORTAL / AI_PDF |

---

## Invoice XML Formats

Hỗ trợ 7 format XML hóa đơn:
- A1: TH Milk
- A2: Vinamilk
- B: MISA
- C: Vinh An
- D: Nguyen Thinh
- (+ 2 format khác)

Chi tiết: xem `app/services/invoice_parsers.py`

---

## Environment

```env
FIREBASE_SERVICE_ACCOUNT_KETOAN=...  # Firebase credentials
```

- Firebase creds priority: env `FIREBASE_SERVICE_ACCOUNT_KETOAN` > file > default
- CORS: `localhost:4200`
- Host: `0.0.0.0:8000`

---

*Cập nhật: 2026-06-06*
