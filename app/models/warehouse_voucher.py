"""
Phiếu Nhập Kho / Phiếu Xuất Kho - Warehouse Voucher Models
Theo Thông tư 133/2016/TT-BTC
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


class WarehouseVoucherType(str, Enum):
    RECEIPT = "RECEIPT"  # Phiếu nhập kho
    ISSUE = "ISSUE"      # Phiếu xuất kho


class WarehouseVoucherStatus(str, Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    CANCELLED = "CANCELLED"


class ReceiptType(str, Enum):
    PURCHASE = "PURCHASE"              # Nhập mua
    RETURN_SALE = "RETURN_SALE"        # Nhập hàng bán bị trả lại
    TRANSFER_IN = "TRANSFER_IN"        # Nhập điều chuyển nội bộ
    PRODUCTION = "PRODUCTION"          # Nhập thành phẩm sản xuất
    INVENTORY_PLUS = "INVENTORY_PLUS"  # Kiểm kê thừa
    OTHER_IN = "OTHER_IN"              # Nhập khác


class IssueType(str, Enum):
    SALE = "SALE"                        # Xuất bán
    RETURN_PURCHASE = "RETURN_PURCHASE"  # Xuất trả lại NCC
    TRANSFER_OUT = "TRANSFER_OUT"        # Xuất điều chuyển nội bộ
    PRODUCTION_USE = "PRODUCTION_USE"    # Xuất sử dụng sản xuất
    INVENTORY_MINUS = "INVENTORY_MINUS"  # Kiểm kê thiếu
    OTHER_OUT = "OTHER_OUT"              # Xuất khác


class WarehouseVoucherLine(BaseModel):
    """Chi tiết dòng phiếu kho"""
    id: Optional[str] = None
    line_no: int = Field(..., ge=1)
    product_id: Optional[str] = None
    product_code: str
    product_name: str
    unit: str
    quantity: float = Field(..., gt=0)
    unit_price: float = Field(..., ge=0)
    amount: float = Field(..., ge=0)
    inventory_account: str = "156"  # TK kho
    expense_account: Optional[str] = None  # TK chi phí/giá vốn
    warehouse_code: Optional[str] = None
    batch_no: Optional[str] = None
    expiry_date: Optional[datetime] = None
    note: Optional[str] = None


class WarehouseVoucherCreate(BaseModel):
    """DTO tạo phiếu kho mới"""
    voucher_type: WarehouseVoucherType
    receipt_type: Optional[ReceiptType] = None
    issue_type: Optional[IssueType] = None
    voucher_date: datetime
    partner_id: Optional[str] = None
    partner_code: Optional[str] = None
    partner_name: Optional[str] = None
    ref_voucher_no: Optional[str] = None
    ref_voucher_date: Optional[datetime] = None
    ref_voucher_type: Optional[str] = None
    warehouse_code: str
    warehouse_name: str
    keeper: Optional[str] = None
    receiver: Optional[str] = None
    lines: List[WarehouseVoucherLine]
    debit_account: str
    credit_account: str
    description: Optional[str] = None
    note: Optional[str] = None


class WarehouseVoucherUpdate(BaseModel):
    """DTO cập nhật phiếu kho"""
    voucher_date: Optional[datetime] = None
    partner_name: Optional[str] = None
    warehouse_code: Optional[str] = None
    warehouse_name: Optional[str] = None
    keeper: Optional[str] = None
    receiver: Optional[str] = None
    lines: Optional[List[WarehouseVoucherLine]] = None
    description: Optional[str] = None
    note: Optional[str] = None


class WarehouseVoucher(BaseModel):
    """Phiếu nhập/xuất kho đầy đủ"""
    id: str
    voucher_no: str  # PNK202501001, PXK202501001
    voucher_type: WarehouseVoucherType
    receipt_type: Optional[ReceiptType] = None
    issue_type: Optional[IssueType] = None
    voucher_date: datetime
    status: WarehouseVoucherStatus = WarehouseVoucherStatus.DRAFT

    # Đối tượng liên quan
    partner_id: Optional[str] = None
    partner_code: Optional[str] = None
    partner_name: Optional[str] = None

    # Chứng từ gốc
    ref_voucher_no: Optional[str] = None
    ref_voucher_date: Optional[datetime] = None
    ref_voucher_type: Optional[str] = None

    # Kho
    warehouse_code: str
    warehouse_name: str
    keeper: Optional[str] = None
    receiver: Optional[str] = None

    # Chi tiết
    lines: List[WarehouseVoucherLine]

    # Tổng hợp
    total_quantity: float
    total_amount: float

    # Bút toán
    debit_account: str
    credit_account: str

    # Ghi chú
    description: Optional[str] = None
    note: Optional[str] = None

    # Audit
    created_at: datetime
    created_by: str
    updated_at: Optional[datetime] = None
    posted_at: Optional[datetime] = None
    posted_by: Optional[str] = None
    cancelled_at: Optional[datetime] = None
    cancelled_by: Optional[str] = None
    cancel_reason: Optional[str] = None

    class Config:
        from_attributes = True
