"""
Phiếu Thu / Phiếu Chi - Cash Voucher Models
Theo Thông tư 133/2016/TT-BTC
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


class VoucherType(str, Enum):
    RECEIPT = "RECEIPT"  # Phiếu thu
    PAYMENT = "PAYMENT"  # Phiếu chi


class VoucherStatus(str, Enum):
    DRAFT = "DRAFT"          # Nháp
    POSTED = "POSTED"        # Đã ghi sổ
    CANCELLED = "CANCELLED"  # Đã hủy


class PaymentMethod(str, Enum):
    CASH = "CASH"                    # Tiền mặt
    BANK_TRANSFER = "BANK_TRANSFER"  # Chuyển khoản


class RelatedObjectType(str, Enum):
    CUSTOMER = "CUSTOMER"    # Khách hàng
    SUPPLIER = "SUPPLIER"    # Nhà cung cấp
    EMPLOYEE = "EMPLOYEE"    # Nhân viên
    OTHER = "OTHER"          # Khác


class CashVoucherLine(BaseModel):
    """Chi tiết dòng phiếu thu/chi"""
    id: Optional[str] = None
    line_no: int = Field(..., ge=1)
    description: str
    account_code: str  # Tài khoản đối ứng
    account_name: Optional[str] = None
    amount: float = Field(..., ge=0)
    tax_code: Optional[str] = None
    tax_rate: Optional[float] = None
    tax_amount: Optional[float] = 0


class CashVoucherCreate(BaseModel):
    """DTO tạo phiếu thu/chi mới"""
    voucher_type: VoucherType
    voucher_date: datetime
    related_object_type: RelatedObjectType
    related_object_id: Optional[str] = None
    related_object_code: Optional[str] = None
    related_object_name: str
    address: Optional[str] = None
    reason: str
    description: Optional[str] = None
    payment_method: PaymentMethod = PaymentMethod.CASH
    cash_account_code: str = "1111"
    lines: List[CashVoucherLine]
    receiver_name: Optional[str] = None
    receiver_id: Optional[str] = None
    original_voucher_no: Optional[str] = None
    original_voucher_date: Optional[datetime] = None


class CashVoucherUpdate(BaseModel):
    """DTO cập nhật phiếu thu/chi"""
    voucher_date: Optional[datetime] = None
    related_object_name: Optional[str] = None
    address: Optional[str] = None
    reason: Optional[str] = None
    description: Optional[str] = None
    payment_method: Optional[PaymentMethod] = None
    cash_account_code: Optional[str] = None
    lines: Optional[List[CashVoucherLine]] = None
    receiver_name: Optional[str] = None
    receiver_id: Optional[str] = None


class CashVoucher(BaseModel):
    """Phiếu thu / Phiếu chi đầy đủ"""
    id: str
    voucher_type: VoucherType
    voucher_no: str  # Số phiếu: PT202501001, PC202501001
    voucher_date: datetime
    posting_date: Optional[datetime] = None

    # Đối tượng
    related_object_type: RelatedObjectType
    related_object_id: Optional[str] = None
    related_object_code: Optional[str] = None
    related_object_name: str
    address: Optional[str] = None

    # Nội dung
    reason: str
    description: Optional[str] = None

    # Phương thức
    payment_method: PaymentMethod
    cash_account_code: str

    # Chi tiết
    lines: List[CashVoucherLine]

    # Tổng tiền
    total_amount: float
    total_tax_amount: float
    grand_total: float

    # Chữ viết
    amount_in_words: Optional[str] = None

    # Trạng thái
    status: VoucherStatus = VoucherStatus.DRAFT

    # Người thực hiện
    receiver_name: Optional[str] = None
    receiver_id: Optional[str] = None

    # Chứng từ gốc
    original_voucher_no: Optional[str] = None
    original_voucher_date: Optional[datetime] = None

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
