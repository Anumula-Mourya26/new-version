from datetime import datetime, timezone
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func

from app.core.db import get_db
from app.models.entities import Centre, Slot, Booking, User, QueueState, Transaction
from app.schemas.schemas import (
    VendorSettingsUpdateRequest, VendorCheckinRequest, VendorPaymentSubmitRequest,
    SlotRosterResponse, FarmerInSlot, TransactionBrief
)
from app.services.queue_engine import QueueEngine
from app.ws.queue_ws import manager

router = APIRouter(prefix='/vendor', tags=['Vendor Operations'])


@router.get('/{centre_id}/settings')
async def get_vendor_settings(centre_id: str, db: AsyncSession = Depends(get_db)):
    centre = (await db.execute(select(Centre).where(Centre.id == centre_id))).scalar_one_or_none()
    if not centre:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Mandi Centre not found')

    return {
        'centre_id': centre.id,
        'mandi_name': centre.name,
        'workers_count': centre.workers_count,        # C
        'capacity_factor': centre.capacity_factor,    # F
        'status': centre.status,
    }


@router.put('/{centre_id}/settings')
async def update_vendor_settings(
    centre_id: str, payload: VendorSettingsUpdateRequest, db: AsyncSession = Depends(get_db)
):
    centre = (await db.execute(select(Centre).where(Centre.id == centre_id))).scalar_one_or_none()
    if not centre:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Mandi Centre not found')

    centre.workers_count = payload.workers_count
    centre.capacity_factor = payload.capacity_factor
    centre.status = payload.status

    await db.commit()

    # Instant live ETA recompute and WebSocket broadcast to all farmers
    updated_queue = await QueueEngine.recompute_centre_queue(db, centre_id)
    await db.commit()

    await manager.broadcast_queue_update(
        centre_id,
        {
            'event': 'settings_updated',
            'workers_count': centre.workers_count,
            'capacity_factor': centre.capacity_factor,
            'status': centre.status,
            'queue': updated_queue,
        }
    )

    return {
        'status': 'success',
        'message': 'Operational settings updated. All farmer ETAs recomputed instantly.',
        'workers_count': centre.workers_count,
        'capacity_factor': centre.capacity_factor,
        'centre_status': centre.status,
    }


@router.get('/{centre_id}/slots/roster', response_model=List[SlotRosterResponse])
async def get_slots_roster(centre_id: str, slot_date: str = None, db: AsyncSession = Depends(get_db)):
    if not slot_date:
        slot_date = datetime.now().strftime('%Y-%m-%d')

    slots = (await db.execute(
        select(Slot)
        .where(and_(Slot.centre_id == centre_id, Slot.slot_date == slot_date))
        .order_by(Slot.time_window.asc())
    )).scalars().all()

    results = []
    for slot in slots:
        bookings_stmt = (
            select(Booking, User)
            .join(User, User.id == Booking.farmer_id)
            .where(Booking.slot_id == slot.id)
            .order_by(Booking.booked_at.asc())
        )
        b_rows = (await db.execute(bookings_stmt)).all()

        farmers = [
            FarmerInSlot(
                booking_id=b.id,
                booking_code=b.unique_booking_code,
                farmer_name=u.full_name,
                farmer_phone=u.phone,
                estimated_weight=b.estimated_weight_quintals,
                status=b.status,
                arrived_at=b.arrived_at,
            )
            for b, u in b_rows
        ]

        results.append(SlotRosterResponse(
            slot_id=slot.id,
            time_window=slot.time_window,
            capacity_units=slot.capacity_units,
            booked_units=len(farmers),
            farmers=farmers,
        ))

    return results


@router.post('/scan-checkin')
async def scan_and_checkin(payload: VendorCheckinRequest, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(Booking, Centre)
        .join(Centre, Centre.id == Booking.centre_id)
        .where(Booking.unique_booking_code == payload.booking_code)
    )
    res = (await db.execute(stmt)).first()
    if not res:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Booking code not found')

    booking, centre = res

    if booking.status in ['completed', 'cancelled']:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f'Booking is {booking.status}')

    now = datetime.now(timezone.utc)
    booking.status = 'in_queue'
    booking.arrived_at = booking.arrived_at or now

    q_state = (await db.execute(select(QueueState).where(QueueState.booking_id == booking.id))).scalar_one_or_none()
    if not q_state:
        waiting_count = (await db.execute(
            select(func.count(QueueState.id)).where(
                and_(QueueState.centre_id == centre.id, QueueState.status == 'waiting')
            )
        )).scalar() or 0

        position = waiting_count + 1
        eta = QueueEngine.calculate_eta(
            n=position, c=centre.workers_count, f=centre.capacity_factor, status=centre.status
        )

        q_state = QueueState(
            centre_id=centre.id,
            booking_id=booking.id,
            position=position,
            eta_minutes=eta,
            status='waiting',
            computed_at=now,
        )
        db.add(q_state)
    else:
        q_state.status = 'waiting'

    await db.commit()

    updated_queue = await QueueEngine.recompute_centre_queue(db, centre.id)
    await db.commit()

    await manager.broadcast_queue_update(
        centre.id,
        {'event': 'admitted_to_queue', 'booking_code': booking.unique_booking_code, 'queue': updated_queue}
    )

    return {
        'status': 'success',
        'message': f'Farmer checked in! Assigned Queue Position #{q_state.position}',
        'booking_code': booking.unique_booking_code,
        'position': q_state.position,
        'eta_minutes': q_state.eta_minutes,
    }


@router.post('/payment/submit')
async def submit_payment(payload: VendorPaymentSubmitRequest, db: AsyncSession = Depends(get_db)):
    booking = (await db.execute(select(Booking).where(Booking.id == payload.booking_id))).scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Booking not found')

    existing_tx = (await db.execute(select(Transaction).where(Transaction.booking_id == payload.booking_id))).scalar_one_or_none()
    if existing_tx:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='Payment transaction already recorded for this booking')

    # Record transaction with proof
    tx = Transaction(
        booking_id=booking.id,
        centre_id=booking.centre_id,
        farmer_id=booking.farmer_id,
        actual_weight_quintals=payload.actual_weight_quintals,
        amount_paid=payload.amount_paid,
        payment_method=payload.payment_method,
        proof_type=payload.proof_type,
        proof_data=payload.proof_data,
        status='credited',
    )
    db.add(tx)

    # Complete booking and remove from active waiting queue
    booking.status = 'completed'

    q_state = (await db.execute(select(QueueState).where(QueueState.booking_id == booking.id))).scalar_one_or_none()
    if q_state:
        q_state.status = 'served'

    await db.commit()

    # Recompute remaining queue
    updated_queue = await QueueEngine.recompute_centre_queue(db, booking.centre_id)
    await db.commit()

    await manager.broadcast_queue_update(
        booking.centre_id,
        {
            'event': 'service_completed',
            'served_booking': booking.unique_booking_code,
            'queue': updated_queue,
        }
    )

    return {
        'status': 'success',
        'message': 'Payment submitted and confirmed with proof! Farmer account marked credited.',
        'transaction_id': tx.id,
        'amount_paid': tx.amount_paid,
        'proof_type': tx.proof_type,
        'proof_data': tx.proof_data,
    }


@router.get('/{centre_id}/transactions')
async def get_centre_transactions(centre_id: str, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(Transaction, Booking, User)
        .join(Booking, Booking.id == Transaction.booking_id)
        .join(User, User.id == Transaction.farmer_id)
        .where(Transaction.centre_id == centre_id)
        .order_by(Transaction.created_at.desc())
    )
    rows = (await db.execute(stmt)).all()

    return [
        {
            'id': tx.id,
            'booking_code': b.unique_booking_code,
            'farmer_name': u.full_name,
            'farmer_phone': u.phone,
            'actual_weight_quintals': tx.actual_weight_quintals,
            'amount_paid': tx.amount_paid,
            'payment_method': tx.payment_method,
            'proof_type': tx.proof_type,
            'proof_data': tx.proof_data,
            'status': tx.status,
            'created_at': tx.created_at,
        }
        for tx, b, u in rows
    ]
