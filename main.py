"""
TapHoa39KeToan Backend - FastAPI Application
Kế toán doanh nghiệp theo Thông tư 133/2016/TT-BTC
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import logging
import uvicorn

# Configure logging to show INFO level
logging.basicConfig(level=logging.INFO, format='%(name)s - %(levelname)s - %(message)s')

from app.config import settings, initialize_firebase, initialize_supplies_firebase, initialize_gmail_firebase
from app.routes import cash_voucher_router, warehouse_voucher_router, hddt_proxy_router, invoice_router, invoice_legacy_router, gmail_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan - startup and shutdown events"""
    # Startup
    print("🚀 Starting TapHoa39KeToan Backend...")
    initialize_firebase()
    try:
        initialize_supplies_firebase()
    except Exception as e:
        print(f"⚠️ Supplies Firebase unavailable (invoice routes will fail): {e}")
    try:
        initialize_gmail_firebase()
    except Exception as e:
        print(f"⚠️ Gmail Firebase unavailable (gmail routes will fail): {e}")
    print(f"✅ Server ready at http://{settings.host}:{settings.port}")
    yield
    # Shutdown
    print("👋 Shutting down...")


# Create FastAPI app
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="""
## TapHoa39KeToan API

Hệ thống Kế toán Doanh nghiệp theo Thông tư 133/2016/TT-BTC

### Modules:
- **Phiếu Thu/Chi**: Quản lý thu chi tiền mặt/ngân hàng
- **Phiếu Nhập/Xuất Kho**: Quản lý nhập xuất kho hàng hóa
- **Hóa đơn đầu vào**: Đồng bộ và đối chiếu hóa đơn từ NCC

### Features:
- CRUD operations cho tất cả chứng từ
- Ghi sổ (Post) / Hủy phiếu
- Thống kê và báo cáo
- Tích hợp Firebase Firestore
    """,
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Health check endpoint
@app.get("/", tags=["Health"])
async def root():
    """Health check endpoint"""
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version
    }


@app.get("/health", tags=["Health"])
async def health_check():
    """Detailed health check"""
    return {
        "status": "healthy",
        "firebase": "connected",
        "version": settings.app_version
    }


# Register routers
app.include_router(cash_voucher_router)
app.include_router(warehouse_voucher_router)
app.include_router(hddt_proxy_router)
app.include_router(invoice_router)
app.include_router(invoice_legacy_router)
app.include_router(gmail_router)


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug
    )
