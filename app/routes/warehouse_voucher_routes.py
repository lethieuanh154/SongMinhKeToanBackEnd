"""
Warehouse Voucher API Routes - Phiếu Nhập/Xuất Kho
"""
from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List
from datetime import datetime

from ..models.warehouse_voucher import (
    WarehouseVoucher,
    WarehouseVoucherCreate,
    WarehouseVoucherUpdate,
    WarehouseVoucherType,
    WarehouseVoucherStatus
)
from ..services.warehouse_voucher_service import WarehouseVoucherService

router = APIRouter(prefix="/api/warehouse-vouchers", tags=["Warehouse Vouchers"])
service = WarehouseVoucherService()


@router.post("", response_model=WarehouseVoucher, status_code=201)
async def create_voucher(data: WarehouseVoucherCreate):
    """
    Tạo phiếu nhập/xuất kho mới

    - **voucher_type**: RECEIPT (nhập) hoặc ISSUE (xuất)
    - **receipt_type**: Loại nhập (PURCHASE, RETURN_SALE, ...)
    - **issue_type**: Loại xuất (SALE, RETURN_PURCHASE, ...)
    - **warehouse_code**: Mã kho
    - **lines**: Danh sách chi tiết hàng hóa
    """
    try:
        voucher = await service.create(data)
        return voucher
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("", response_model=List[WarehouseVoucher])
async def get_vouchers(
    voucher_type: Optional[WarehouseVoucherType] = Query(None, description="Loại phiếu: RECEIPT/ISSUE"),
    status: Optional[WarehouseVoucherStatus] = Query(None, description="Trạng thái: DRAFT/POSTED/CANCELLED"),
    warehouse_code: Optional[str] = Query(None, description="Mã kho"),
    from_date: Optional[datetime] = Query(None, description="Từ ngày"),
    to_date: Optional[datetime] = Query(None, description="Đến ngày"),
    limit: int = Query(100, ge=1, le=500, description="Số lượng tối đa")
):
    """
    Lấy danh sách phiếu nhập/xuất kho

    Có thể lọc theo:
    - Loại phiếu (nhập/xuất)
    - Trạng thái
    - Mã kho
    - Khoảng thời gian
    """
    try:
        vouchers = await service.get_all(
            voucher_type=voucher_type,
            status=status,
            warehouse_code=warehouse_code,
            from_date=from_date,
            to_date=to_date,
            limit=limit
        )
        return vouchers
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/statistics")
async def get_statistics(
    voucher_type: Optional[WarehouseVoucherType] = Query(None, description="Loại phiếu"),
    from_date: Optional[datetime] = Query(None, description="Từ ngày"),
    to_date: Optional[datetime] = Query(None, description="Đến ngày")
):
    """
    Thống kê phiếu kho

    Trả về:
    - Tổng số phiếu
    - Số lượng theo trạng thái
    - Tổng số lượng và giá trị
    """
    try:
        stats = await service.get_statistics(
            voucher_type=voucher_type,
            from_date=from_date,
            to_date=to_date
        )
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{voucher_id}", response_model=WarehouseVoucher)
async def get_voucher(voucher_id: str):
    """Lấy chi tiết phiếu theo ID"""
    voucher = await service.get_by_id(voucher_id)
    if not voucher:
        raise HTTPException(status_code=404, detail="Không tìm thấy phiếu")
    return voucher


@router.put("/{voucher_id}", response_model=WarehouseVoucher)
async def update_voucher(voucher_id: str, data: WarehouseVoucherUpdate):
    """
    Cập nhật phiếu (chỉ phiếu DRAFT)
    """
    voucher = await service.update(voucher_id, data)
    if not voucher:
        raise HTTPException(status_code=400, detail="Không thể cập nhật phiếu (phiếu không tồn tại hoặc đã ghi sổ)")
    return voucher


@router.post("/{voucher_id}/post", response_model=WarehouseVoucher)
async def post_voucher(voucher_id: str):
    """
    Ghi sổ phiếu (chuyển từ DRAFT sang POSTED)
    """
    voucher = await service.post(voucher_id)
    if not voucher:
        raise HTTPException(status_code=400, detail="Không thể ghi sổ phiếu")
    return voucher


@router.post("/{voucher_id}/cancel", response_model=WarehouseVoucher)
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
