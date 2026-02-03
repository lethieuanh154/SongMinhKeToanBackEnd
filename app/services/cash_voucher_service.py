"""
Cash Voucher Service - Phiếu Thu/Chi
"""
from datetime import datetime
from typing import List, Optional
from google.cloud.firestore import FieldFilter
import uuid

from ..config.firebase import get_db
from ..models.cash_voucher import (
    CashVoucher,
    CashVoucherCreate,
    CashVoucherUpdate,
    CashVoucherLine,
    VoucherType,
    VoucherStatus
)


class CashVoucherService:
    COLLECTION = "cash_vouchers"
    COUNTER_COLLECTION = "counters"

    def __init__(self):
        self.db = get_db()

    def _get_collection(self):
        return self.db.collection(self.COLLECTION)

    def _generate_voucher_no(self, voucher_type: VoucherType) -> str:
        """Generate voucher number: PT202501001 or PC202501001"""
        prefix = "PT" if voucher_type == VoucherType.RECEIPT else "PC"
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

    def _calculate_totals(self, lines: List[CashVoucherLine]) -> dict:
        """Calculate total amounts from lines"""
        total_amount = sum(line.amount for line in lines)
        total_tax = sum(line.tax_amount or 0 for line in lines)
        return {
            "total_amount": total_amount,
            "total_tax_amount": total_tax,
            "grand_total": total_amount + total_tax
        }

    def _number_to_words(self, num: float) -> str:
        """Convert number to Vietnamese words (simplified)"""
        if num == 0:
            return "Không đồng"
        # Simplified implementation
        return f"{int(num):,} đồng".replace(",", ".")

    async def create(self, data: CashVoucherCreate, user_id: str = "admin") -> CashVoucher:
        """Create new cash voucher"""
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
            "voucher_type": data.voucher_type.value,
            "voucher_no": voucher_no,
            "voucher_date": data.voucher_date,
            "related_object_type": data.related_object_type.value,
            "related_object_id": data.related_object_id,
            "related_object_code": data.related_object_code,
            "related_object_name": data.related_object_name,
            "address": data.address,
            "reason": data.reason,
            "description": data.description,
            "payment_method": data.payment_method.value,
            "cash_account_code": data.cash_account_code,
            "lines": lines,
            "total_amount": totals["total_amount"],
            "total_tax_amount": totals["total_tax_amount"],
            "grand_total": totals["grand_total"],
            "amount_in_words": self._number_to_words(totals["grand_total"]),
            "status": VoucherStatus.DRAFT.value,
            "receiver_name": data.receiver_name,
            "receiver_id": data.receiver_id,
            "original_voucher_no": data.original_voucher_no,
            "original_voucher_date": data.original_voucher_date,
            "created_at": now,
            "created_by": user_id,
            "updated_at": now
        }

        self._get_collection().document(voucher_id).set(voucher_data)
        return CashVoucher(**voucher_data)

    async def get_by_id(self, voucher_id: str) -> Optional[CashVoucher]:
        """Get voucher by ID"""
        doc = self._get_collection().document(voucher_id).get()
        if doc.exists:
            return CashVoucher(**doc.to_dict())
        return None

    async def get_all(
        self,
        voucher_type: Optional[VoucherType] = None,
        status: Optional[VoucherStatus] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        limit: int = 100
    ) -> List[CashVoucher]:
        """Get all vouchers with filters - simple query to avoid composite index"""
        # Use simple query with only one filter to avoid composite index requirement
        query = self._get_collection()

        # Only apply voucher_type filter in Firestore (most common filter)
        if voucher_type:
            query = query.where(filter=FieldFilter("voucher_type", "==", voucher_type.value))

        # Get all documents (limited)
        docs = query.limit(limit * 2).stream()  # Get more to filter client-side

        # Convert to list and filter in memory
        vouchers = []
        for doc in docs:
            data = doc.to_dict()
            voucher = CashVoucher(**data)

            # Apply other filters in memory
            if status and voucher.status != status:
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

    async def update(self, voucher_id: str, data: CashVoucherUpdate, user_id: str = "admin") -> Optional[CashVoucher]:
        """Update voucher (only DRAFT status)"""
        voucher = await self.get_by_id(voucher_id)
        if not voucher or voucher.status != VoucherStatus.DRAFT:
            return None

        update_data = data.model_dump(exclude_unset=True)
        update_data["updated_at"] = datetime.now()

        if "lines" in update_data and update_data["lines"]:
            lines = [CashVoucherLine(**line) for line in update_data["lines"]]
            totals = self._calculate_totals(lines)
            update_data.update(totals)
            update_data["amount_in_words"] = self._number_to_words(totals["grand_total"])

        self._get_collection().document(voucher_id).update(update_data)
        return await self.get_by_id(voucher_id)

    async def post(self, voucher_id: str, user_id: str = "admin") -> Optional[CashVoucher]:
        """Post voucher (change status to POSTED)"""
        voucher = await self.get_by_id(voucher_id)
        if not voucher or voucher.status != VoucherStatus.DRAFT:
            return None

        now = datetime.now()
        self._get_collection().document(voucher_id).update({
            "status": VoucherStatus.POSTED.value,
            "posting_date": now,
            "posted_at": now,
            "posted_by": user_id
        })
        return await self.get_by_id(voucher_id)

    async def cancel(self, voucher_id: str, reason: str, user_id: str = "admin") -> Optional[CashVoucher]:
        """Cancel voucher"""
        voucher = await self.get_by_id(voucher_id)
        if not voucher or voucher.status == VoucherStatus.CANCELLED:
            return None

        now = datetime.now()
        self._get_collection().document(voucher_id).update({
            "status": VoucherStatus.CANCELLED.value,
            "cancelled_at": now,
            "cancelled_by": user_id,
            "cancel_reason": reason
        })
        return await self.get_by_id(voucher_id)

    async def delete(self, voucher_id: str) -> bool:
        """Delete voucher (only DRAFT status)"""
        voucher = await self.get_by_id(voucher_id)
        if not voucher or voucher.status != VoucherStatus.DRAFT:
            return False

        self._get_collection().document(voucher_id).delete()
        return True

    async def get_statistics(self, from_date: Optional[datetime] = None, to_date: Optional[datetime] = None) -> dict:
        """Get voucher statistics"""
        query = self._get_collection()

        if from_date:
            query = query.where(filter=FieldFilter("voucher_date", ">=", from_date))
        if to_date:
            query = query.where(filter=FieldFilter("voucher_date", "<=", to_date))

        docs = list(query.stream())

        stats = {
            "total_vouchers": 0,
            "receipt_count": 0,
            "payment_count": 0,
            "total_receipt_amount": 0.0,
            "total_payment_amount": 0.0,
            "net_cash_flow": 0.0,
            "by_status": {
                "draft": 0,
                "posted": 0,
                "cancelled": 0
            }
        }

        for doc in docs:
            data = doc.to_dict()
            stats["total_vouchers"] += 1

            # Count by status
            status = data.get("status")
            if status == VoucherStatus.DRAFT.value:
                stats["by_status"]["draft"] += 1
            elif status == VoucherStatus.POSTED.value:
                stats["by_status"]["posted"] += 1
            elif status == VoucherStatus.CANCELLED.value:
                stats["by_status"]["cancelled"] += 1

            # Only count amounts for non-cancelled vouchers
            if status != VoucherStatus.CANCELLED.value:
                if data.get("voucher_type") == VoucherType.RECEIPT.value:
                    stats["receipt_count"] += 1
                    stats["total_receipt_amount"] += data.get("grand_total", 0)
                else:
                    stats["payment_count"] += 1
                    stats["total_payment_amount"] += data.get("grand_total", 0)

        stats["net_cash_flow"] = stats["total_receipt_amount"] - stats["total_payment_amount"]
        return stats
