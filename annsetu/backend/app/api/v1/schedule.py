from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.core.db import get_db
from app.models.entities import Centre, Slot, Booking, User, Transaction
from app.schemas.schemas import DayScheduleSummary, HistoricalSlotRecord, FarmerInSlot

router = APIRouter(prefix='/centres', tags=['Centres & Schedules'])


@router.get('/{centre_id}/schedule/history', response_model=DayScheduleSummary)
async def get_centre_schedule_history(
    centre_id: str,
    date: Optional[str] = Query(None, description="Date in YYYY-MM-DD format"),
    slot_id: Optional[str] = Query(None, description="Optional specific slot ID filter"),
    db: AsyncSession = Depends(get_db),
):
    """
    Day-wise and slot-wise historical retrieval of bookings, occupancy, and transactions.
    Backed by composite indices on (centre_id, slot_date) and (slot_id, status).
    """
    centre = (await db.execute(select(Centre).where(Centre.id == centre_id))).scalar_one_or_none()
    if not centre:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Centre not found")

    target_date = date or datetime.now().strftime("%Y-%m-%d")

    # Fetch slots for target date
    slot_stmt = (
        select(Slot)
        .where(and_(Slot.centre_id == centre_id, Slot.slot_date == target_date))
        .order_by(Slot.time_window.asc())
    )
    if slot_id:
        slot_stmt = slot_stmt.where(Slot.id == slot_id)

    slots = (await db.execute(slot_stmt)).scalars().all()

    slot_records: List[HistoricalSlotRecord] = []
    day_total_volume = 0.0
    day_total_payout = 0.0
    day_admitted_count = 0
    day_capacity = 0
    day_booked = 0

    for slot in slots:
        day_capacity += slot.capacity_units
        day_booked += slot.booked_units

        # Fetch bookings for this slot
        b_stmt = (
            select(Booking, User)
            .join(User, User.id == Booking.farmer_id)
            .where(Booking.slot_id == slot.id)
            .order_by(Booking.booked_at.asc())
        )
        booking_rows = (await db.execute(b_stmt)).all()

        slot_farmers: List[FarmerInSlot] = []
        slot_completed = 0
        slot_volume = 0.0
        slot_payout = 0.0

        for b, u in booking_rows:
            slot_farmers.append(FarmerInSlot(
                booking_id=b.id,
                booking_code=b.unique_booking_code,
                unique_booking_code=b.unique_booking_code,
                farmer_name=u.full_name,
                farmer_phone=u.phone,
                estimated_weight=b.estimated_weight_quintals,
                estimated_weight_quintals=b.estimated_weight_quintals,
                primary_crop=b.primary_crop or "Wheat",
                crops_data=b.crops_data,
                status=b.status,
                arrived_at=b.arrived_at,
            ))

            slot_volume += b.estimated_weight_quintals
            if b.status in ("arrived", "in_queue", "completed"):
                day_admitted_count += 1
            if b.status == "completed":
                slot_completed += 1

            # Fetch payment if available
            tx = (await db.execute(
                select(Transaction).where(Transaction.booking_id == b.id)
            )).scalar_one_or_none()
            if tx:
                slot_payout += tx.amount_paid

        day_total_volume += slot_volume
        day_total_payout += slot_payout

        slot_records.append(HistoricalSlotRecord(
            slot_id=slot.id,
            slot_date=slot.slot_date,
            time_window=slot.time_window,
            capacity_units=slot.capacity_units,
            booked_units=slot.booked_units,
            remaining_units=max(0, slot.capacity_units - slot.booked_units),
            booked_count=len(slot_farmers),
            completed_count=slot_completed,
            total_quintals=round(slot_volume, 2),
            total_amount_paid=round(slot_payout, 2),
            bookings=slot_farmers,
        ))

    occupancy_pct = round((day_booked / day_capacity * 100), 1) if day_capacity > 0 else 0.0

    return DayScheduleSummary(
        date=target_date,
        centre_id=centre.id,
        centre_name=centre.name,
        total_slots=len(slots),
        total_capacity_units=day_capacity,
        total_booked_units=day_booked,
        occupancy_rate_pct=occupancy_pct,
        total_farmers_admitted=day_admitted_count,
        total_volume_quintals=round(day_total_volume, 2),
        total_payout_amount=round(day_total_payout, 2),
        slots=slot_records,
    )