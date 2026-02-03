# TapHoa39KeToan Backend

Backend API cho hệ thống Kế toán Doanh nghiệp TapHoa39KeToan.

## Tech Stack

- **Framework**: FastAPI (Python 3.10+)
- **Database**: Firebase Firestore
- **Authentication**: Firebase Admin SDK

## Cấu trúc thư mục

```
TapHoa39KeToanBackEnd/
├── app/
│   ├── config/
│   │   ├── __init__.py
│   │   ├── settings.py      # App settings
│   │   └── firebase.py      # Firebase config
│   ├── models/
│   │   ├── __init__.py
│   │   ├── cash_voucher.py      # Phiếu thu/chi
│   │   └── warehouse_voucher.py # Phiếu kho
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── cash_voucher_routes.py
│   │   └── warehouse_voucher_routes.py
│   └── services/
│       ├── __init__.py
│       ├── cash_voucher_service.py
│       └── warehouse_voucher_service.py
├── main.py                  # FastAPI entry point
├── requirements.txt
├── .env.example
└── README.md
```

## Cài đặt

### 1. Tạo virtual environment

```bash
cd TapHoa39KeToanBackEnd
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/Mac
source venv/bin/activate
```

### 2. Cài đặt dependencies

```bash
pip install -r requirements.txt
```

### 3. Cấu hình Firebase

1. Vào [Firebase Console](https://console.firebase.google.com/)
2. Chọn project `songminhketoan-15041989`
3. Vào **Project Settings** > **Service Accounts**
4. Click **Generate new private key**
5. Lưu file JSON về và đổi tên thành `firebase-service-account.json`
6. Copy file vào thư mục gốc của backend

### 4. Tạo file .env

```bash
cp .env.example .env
```

Chỉnh sửa `.env` nếu cần.

### 5. Chạy server

```bash
# Development mode với auto-reload
python main.py

# Hoặc dùng uvicorn trực tiếp
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

## API Endpoints

### Health Check

- `GET /` - Basic health check
- `GET /health` - Detailed health check

### Phiếu Thu/Chi (Cash Vouchers)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/cash-vouchers` | Tạo phiếu mới |
| GET | `/api/cash-vouchers` | Lấy danh sách phiếu |
| GET | `/api/cash-vouchers/statistics` | Thống kê |
| GET | `/api/cash-vouchers/{id}` | Lấy chi tiết phiếu |
| PUT | `/api/cash-vouchers/{id}` | Cập nhật phiếu |
| POST | `/api/cash-vouchers/{id}/post` | Ghi sổ phiếu |
| POST | `/api/cash-vouchers/{id}/cancel` | Hủy phiếu |
| DELETE | `/api/cash-vouchers/{id}` | Xóa phiếu |

### Phiếu Nhập/Xuất Kho (Warehouse Vouchers)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/warehouse-vouchers` | Tạo phiếu mới |
| GET | `/api/warehouse-vouchers` | Lấy danh sách phiếu |
| GET | `/api/warehouse-vouchers/statistics` | Thống kê |
| GET | `/api/warehouse-vouchers/{id}` | Lấy chi tiết phiếu |
| PUT | `/api/warehouse-vouchers/{id}` | Cập nhật phiếu |
| POST | `/api/warehouse-vouchers/{id}/post` | Ghi sổ phiếu |
| POST | `/api/warehouse-vouchers/{id}/cancel` | Hủy phiếu |
| DELETE | `/api/warehouse-vouchers/{id}` | Xóa phiếu |

## API Documentation

Sau khi chạy server, truy cập:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## Firestore Collections

- `cash_vouchers` - Phiếu thu/chi
- `warehouse_vouchers` - Phiếu nhập/xuất kho
- `counters` - Bộ đếm số phiếu tự động

## License

Private - TapHoa39
