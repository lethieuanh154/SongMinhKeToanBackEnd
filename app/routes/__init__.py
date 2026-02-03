from .cash_voucher_routes import router as cash_voucher_router
from .warehouse_voucher_routes import router as warehouse_voucher_router

__all__ = ["cash_voucher_router", "warehouse_voucher_router"]
