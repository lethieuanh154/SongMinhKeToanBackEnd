"""
Cash Voucher API Routes - Phiếu Thu/Chi
"""
from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List
from datetime import datetime

from ..models.cash_voucher import (
    CashVoucher,
    CashVoucherCreate,
    CashVoucherUpdate,
    VoucherType,
    VoucherStatus
)
from ..services.cash_voucher_service import CashVoucherService

router = APIRouter(prefix="/api/cash-vouchers", tags=["Cash Vouchers"])
service = CashVoucherService()


@router.post("", response_model=CashVoucher, status_code=201)
async def create_voucher(data: CashVoucherCreate):
    """
    Tạo phiếu thu/chi mới

    - **voucher_type**: RECEIPT (thu) hoặc PAYMENT (chi)
    - **voucher_date**: Ngày phiếu
    - **related_object_name**: Tên đối tượng (KH/NCC/NV)
    - **reason**: Lý do thu/chi
    - **lines**: Danh sách chi tiết
    """
    try:
        voucher = await service.create(data)
        return voucher
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("", response_model=List[CashVoucher])
async def get_vouchers(
    voucher_type: Optional[VoucherType] = Query(None, description="Loại phiếu: RECEIPT/PAYMENT"),
    status: Optional[VoucherStatus] = Query(None, description="Trạng thái: DRAFT/POSTED/CANCELLED"),
    from_date: Optional[datetime] = Query(None, description="Từ ngày"),
    to_date: Optional[datetime] = Query(None, description="Đến ngày"),
    limit: int = Query(100, ge=1, le=500, description="Số lượng tối đa")
):
    """
    Lấy danh sách phiếu thu/chi

    Có thể lọc theo:
    - Loại phiếu (thu/chi)
    - Trạng thái
    - Khoảng thời gian
    """
    try:
        vouchers = await service.get_all(
            voucher_type=voucher_type,
            status=status,
            from_date=from_date,
            to_date=to_date,
            limit=limit
        )
        return vouchers
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/statistics")
async def get_statistics(
    from_date: Optional[datetime] = Query(None, description="Từ ngày"),
    to_date: Optional[datetime] = Query(None, description="Đến ngày")
):
    """
    Thống kê phiếu thu/chi

    Trả về:
    - Tổng số phiếu thu/chi
    - Tổng tiền thu/chi
    - Dòng tiền ròng
    """
    try:
        stats = await service.get_statistics(from_date=from_date, to_date=to_date)
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{voucher_id}", response_model=CashVoucher)
async def get_voucher(voucher_id: str):
    """Lấy chi tiết phiếu theo ID"""
    voucher = await service.get_by_id(voucher_id)
    if not voucher:
        raise HTTPException(status_code=404, detail="Không tìm thấy phiếu")
    return voucher


@router.put("/{voucher_id}", response_model=CashVoucher)
async def update_voucher(voucher_id: str, data: CashVoucherUpdate):
    """
    Cập nhật phiếu (chỉ phiếu DRAFT)
    """
    voucher = await service.update(voucher_id, data)
    if not voucher:
        raise HTTPException(status_code=400, detail="Không thể cập nhật phiếu (phiếu không tồn tại hoặc đã ghi sổ)")
    return voucher


@router.post("/{voucher_id}/post", response_model=CashVoucher)
async def post_voucher(voucher_id: str):
    """
    Ghi sổ phiếu (chuyển từ DRAFT sang POSTED)
    """
    voucher = await service.post(voucher_id)
    if not voucher:
        raise HTTPException(status_code=400, detail="Không thể ghi sổ phiếu")
    return voucher


@router.post("/{voucher_id}/cancel", response_model=CashVoucher)
async def cancel_voucher(voucher_id: str, reason: str = Query(..., min_length=10, description="Lý do hủy (>= 10 ký tự)")):
    """
    Hủy phiếu
    """
    voucher = await service.cancel(voucher_id, reason)
    if not voucher:
        raise HTTPException(status_code=400, detail="Không thể hủy phiếu")
    return voucher


@router.delete("/{voucher_id}")
async def delete_voucher(voucher_id: str):
    """
    Xóa phiếu (chỉ phiếu DRAFT)
    """
    success = await service.delete(voucher_id)
    if not success:
        raise HTTPException(status_code=400, detail="Không thể xóa phiếu (phiếu không tồn tại hoặc đã ghi sổ)")
    return {"message": "Đã xóa phiếu thành công"}
