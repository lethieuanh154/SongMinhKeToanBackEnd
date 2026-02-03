"""
Warehouse Voucher Service - Phiếu Nhập/Xuất Kho
"""
from datetime import datetime
from typing import List, Optional
from google.cloud.firestore import FieldFilter
import uuid

from ..config.firebase import get_db
from ..models.warehouse_voucher import (
    WarehouseVoucher,
    WarehouseVoucherCreate,
    WarehouseVoucherUpdate,
    WarehouseVoucherLine,
    WarehouseVoucherType,
    WarehouseVoucherStatus
)


class WarehouseVoucherService:
    COLLECTION = "warehouse_vouchers"
    COUNTER_COLLECTION = "counters"

    def __init__(self):
        self.db = get_db()

    def _get_collection(self):
        return self.db.collection(self.COLLECTION)

    def _generate_voucher_no(self, voucher_type: WarehouseVoucherType) -> str:
        """Generate voucher number: PNK202501001 or PXK202501001"""
        prefix = "PNK" if voucher_type == WarehouseVoucherType.RECEIPT else "PXK"
        year = datetime.now().year
        counter_key = f"{prefix}{year}"

        counter_ref = self.db.collection(self.COUNTER_COLLECTION).document(counter_key)
        counter_doc = counter_ref.get()

        if counter_doc.exists:
            current = counter_doc.to_dict().get("value", 0)
            new_value = current + 1
        else:
            new_value = 1

        counter_ref.set({"value": new_value})
        return f"{prefix}{year}{str(new_value).zfill(5)}"

    def _calculate_totals(self, lines: List[WarehouseVoucherLine]) -> dict:
        """Calculate total quantity and amount from lines"""
        total_quantity = sum(line.quantity for line in lines)
        total_amount = sum(line.amount for line in lines)
        return {
            "total_quantity": total_quantity,
            "total_amount": total_amount
        }

    async def create(self, data: WarehouseVoucherCreate, user_id: str = "admin") -> WarehouseVoucher:
        """Create new warehouse voucher"""
        voucher_id = str(uuid.uuid4())
        voucher_no = self._generate_voucher_no(data.voucher_type)
        totals = self._calculate_totals(data.lines)
        now = datetime.now()

        # Prepare lines with IDs
        lines = []
        for i, line in enumerate(data.lines):
            line_dict = line.model_dump()
            line_dict["id"] = str(uuid.uuid4())
            line_dict["line_no"] = i + 1
            lines.append(line_dict)

        voucher_data = {
            "id": voucher_id,
            "voucher_no": voucher_no,
            "voucher_type": data.voucher_type.value,
            "receipt_type": data.receipt_type.value if data.receipt_type else None,
            "issue_type": data.issue_type.value if data.issue_type else None,
            "voucher_date": data.voucher_date,
            "status": WarehouseVoucherStatus.DRAFT.value,
            "partner_id": data.partner_id,
            "partner_code": data.partner_code,
            "partner_name": data.partner_name,
            "ref_voucher_no": data.ref_voucher_no,
            "ref_voucher_date": data.ref_voucher_date,
            "ref_voucher_type": data.ref_voucher_type,
            "warehouse_code": data.warehouse_code,
            "warehouse_name": data.warehouse_name,
            "keeper": data.keeper,
            "receiver": data.receiver,
            "lines": lines,
            "total_quantity": totals["total_quantity"],
            "total_amount": totals["total_amount"],
            "debit_account": data.debit_account,
            "credit_account": data.credit_account,
            "description": data.description,
            "note": data.note,
            "created_at": now,
            "created_by": user_id,
            "updated_at": now
        }

        self._get_collection().document(voucher_id).set(voucher_data)
        return WarehouseVoucher(**voucher_data)

    async def get_by_id(self, voucher_id: str) -> Optional[WarehouseVoucher]:
        """Get voucher by ID"""
        doc = self._get_collection().document(voucher_id).get()
        if doc.exists:
            return WarehouseVoucher(**doc.to_dict())
        return None

    async def get_all(
        self,
        voucher_type: Optional[WarehouseVoucherType] = None,
        status: Optional[WarehouseVoucherStatus] = None,
        warehouse_code: Optional[str] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        limit: int = 100
    ) -> List[WarehouseVoucher]:
        """Get all vouchers with filters - simple query to avoid composite index"""
        query = self._get_collection()

        # Only apply voucher_type filter in Firestore (most common filter)
        if voucher_type:
            query = query.where(filter=FieldFilter("voucher_type", "==", voucher_type.value))

        # Get all documents (limited)
        docs = query.limit(limit * 2).stream()

        # Convert to list and filter in memory
        vouchers = []
        for doc in docs:
            data = doc.to_dict()
            voucher = WarehouseVoucher(**data)

            # Apply other filters in memory
            if status and voucher.status != status:
                continue
            if warehouse_code and voucher.warehouse_code != warehouse_code:
                continue
            if from_date and voucher.voucher_date < from_date:
                continue
            if to_date and voucher.voucher_date > to_date:
                continue

            vouchers.append(voucher)

            if len(vouchers) >= limit:
                break

        # Sort by date descending
        vouchers.sort(key=lambda v: v.voucher_date, reverse=True)
        return vouchers[:limit]

    async def update(self, voucher_id: str, data: WarehouseVoucherUpdate, user_id: str = "admin") -> Optional[WarehouseVoucher]:
        """Update voucher (only DRAFT status)"""
        voucher = await self.get_by_id(voucher_id)
        if not voucher or voucher.status != WarehouseVoucherStatus.DRAFT:
            return None

        update_data = data.model_dump(exclude_unset=True)
        update_data["updated_at"] = datetime.now()

        if "lines" in update_data and update_data["lines"]:
            lines = [WarehouseVoucherLine(**line) for line in update_data["lines"]]
            totals = self._calculate_totals(lines)
            update_data.update(totals)

        self._get_collection().document(voucher_id).update(update_data)
        return await self.get_by_id(voucher_id)

    async def post(self, voucher_id: str, user_id: str = "admin") -> Optional[WarehouseVoucher]:
        """Post voucher (change status to POSTED)"""
        voucher = await self.get_by_id(voucher_id)
        if not voucher or voucher.status != WarehouseVoucherStatus.DRAFT:
            return None

        now = datetime.now()
        self._get_collection().document(voucher_id).update({
            "status": WarehouseVoucherStatus.POSTED.value,
            "posted_at": now,
            "posted_by": user_id
        })
        return await self.get_by_id(voucher_id)

    async def cancel(self, voucher_id: str, reason: str, user_id: str = "admin") -> Optional[WarehouseVoucher]:
        """Cancel voucher"""
        voucher = await self.get_by_id(voucher_id)
        if not voucher or voucher.status == WarehouseVoucherStatus.CANCELLED:
            return None

        now = datetime.now()
        self._get_collection().document(voucher_id).update({
            "status": WarehouseVoucherStatus.CANCELLED.value,
            "cancelled_at": now,
            "cancelled_by": user_id,
            "cancel_reason": reason
        })
        return await self.get_by_id(voucher_id)

    async def delete(self, voucher_id: str) -> bool:
        """Delete voucher (only DRAFT status)"""
        voucher = await self.get_by_id(voucher_id)
        if not voucher or voucher.status != WarehouseVoucherStatus.DRAFT:
            return False

        self._get_collection().document(voucher_id).delete()
        return True

    async def get_statistics(
        self,
        voucher_type: Optional[WarehouseVoucherType] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None
    ) -> dict:
        """Get voucher statistics"""
        query = self._get_collection()

        if voucher_type:
            query = query.where(filter=FieldFilter("voucher_type", "==", voucher_type.value))
        if from_date:
            query = query.where(filter=FieldFilter("voucher_date", ">=", from_date))
        if to_date:
            query = query.where(filter=FieldFilter("voucher_date", "<=", to_date))

        docs = list(query.stream())

        stats = {
            "total_vouchers": 0,
            "draft_count": 0,
            "posted_count": 0,
            "cancelled_count": 0,
            "total_quantity": 0.0,
            "total_amount": 0.0
        }

        for doc in docs:
            data = doc.to_dict()
            stats["total_vouchers"] += 1

            status = data.get("status")
            if status == WarehouseVoucherStatus.DRAFT.value:
                stats["draft_count"] += 1
            elif status == WarehouseVoucherStatus.POSTED.value:
                stats["posted_count"] += 1
            elif status == WarehouseVoucherStatus.CANCELLED.value:
                stats["cancelled_count"] += 1

            if status != WarehouseVoucherStatus.CANCELLED.value:
                stats["total_quantity"] += data.get("total_quantity", 0)
                stats["total_amount"] += data.get("total_amount", 0)

        return stats
