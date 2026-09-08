import uuid
from datetime import datetime, timezone
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func

from app.core.db import get_db
from app.models.entities import Booking, Slot, Centre, User, QueueState, Transaction
from app.schemas.schemas import (
    BookingCreateRequest, BookingDetailResponse, ArrivalConfirmRequest, TransactionBrief
)
from app.services.queue_engine import QueueEngine
from app.ws.queue_ws import manager

router = APIRouter(prefix='/bookings', tags=['Bookings'])


def generate_booking_code() -> str:
    return f'AS-{uuid.uuid4().hex[:6].upper()}'


@router.post('', response_model=BookingDetailResponse)
async def create_booking(payload: BookingCreateRequest, db: AsyncSession = Depends(get_db)):
    # 1. Fetch and validate Slot
    slot = (await db.execute(select(Slot).where(Slot.id == payload.slot_id))).scalar_one_or_none()
    if not slot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Selected slot not found')

    # Max 30 farmers per slot requirement
    if slot.booked_units >= slot.capacity_units or slot.booked_units >= 30:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail='Slot capacity reached (Maximum 30 farmers per slot). Please select another time window.'
        )

    farmer = (await db.execute(select(User).where(User.id == payload.farmer_id))).scalar_one_or_none()
    if not farmer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Farmer profile not found')

    centre = (await db.execute(select(Centre).where(Centre.id == payload.centre_id))).scalar_one_or_none()
    if not centre:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Mandi Centre not found')

    code = generate_booking_code()
    qr_payload = f'ANNSETU:{code}:{farmer.phone}:{payload.estimated_weight_quintals}'

    booking = Booking(
        farmer_id=payload.farmer_id,
        centre_id=payload.centre_id,
        slot_id=payload.slot_id,
        estimated_weight_quintals=payload.estimated_weight_quintals,
        unique_booking_code=code,
        qr_payload=qr_payload,
        status='booked',
    )
    slot.booked_units += 1

    db.add(booking)
    await db.commit()
    await db.refresh(booking)

    return BookingDetailResponse(
        id=booking.id,
        unique_booking_code=booking.unique_booking_code,
        qr_payload=booking.qr_payload,
        centre_name=centre.name,
        state=centre.state,
        city=centre.city,
        slot_date=slot.slot_date,
        time_window=slot.time_window,
        estimated_weight_quintals=booking.estimated_weight_quintals,
        status=booking.status,
        booked_at=booking.booked_at,
    )


@router.post('/arrival-confirm')
async def confirm_arrival(payload: ArrivalConfirmRequest, db: AsyncSession = Depends(get_db)):
    """
    Confirmation when farmer reaches the location to create/activate queue entry.
    """
    stmt = (
        select(Booking, Centre, Slot)
        .join(Centre, Centre.id == Booking.centre_id)
        .join(Slot, Slot.id == Booking.slot_id)
        .where(Booking.unique_booking_code == payload.booking_code)
    )
    res = (await db.execute(stmt)).first()
    if not res:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Booking code not found')

    booking, centre, slot = res

    if booking.status in ['completed', 'cancelled']:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f'Booking is already {booking.status}')

    now = datetime.now(timezone.utc)
    booking.arrived_at = now
    booking.status = 'arrived'

    # Check if already in queue_state
    q_state = (await db.execute(select(QueueState).where(QueueState.booking_id == booking.id))).scalar_one_or_none()
    if not q_state:
        # Count farmers currently waiting
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

    await db.commit()

    # Recompute and broadcast
    updated_queue = await QueueEngine.recompute_centre_queue(db, centre.id)
    await db.commit()

    await manager.broadcast_queue_update(
        centre.id,
        {'event': 'arrival_confirmed', 'booking_code': booking.unique_booking_code, 'queue': updated_queue}
    )

    return {
        'status': 'success',
        'message': f'Arrival confirmed! You are inserted at queue position #{q_state.position}.',
        'position': q_state.position,
        'eta_minutes': q_state.eta_minutes,
        'arrived_at': booking.arrived_at,
    }


@router.get('/farmer/{farmer_id}', response_model=List[BookingDetailResponse])
async def get_farmer_bookings(farmer_id: str, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(Booking, Centre, Slot)
        .join(Centre, Centre.id == Booking.centre_id)
        .join(Slot, Slot.id == Booking.slot_id)
        .where(Booking.farmer_id == farmer_id)
        .order_by(Booking.booked_at.desc())
    )
    rows = (await db.execute(stmt)).all()
    results = []

    for booking, centre, slot in rows:
        q_state = (await db.execute(select(QueueState).where(QueueState.booking_id == booking.id))).scalar_one_or_none()
        tx = (await db.execute(select(Transaction).where(Transaction.booking_id == booking.id))).scalar_one_or_none()

        tx_brief = None
        if tx:
            tx_brief = TransactionBrief(
                id=tx.id,
                actual_weight_quintals=tx.actual_weight_quintals,
                amount_paid=tx.amount_paid,
                payment_method=tx.payment_method,
                proof_type=tx.proof_type,
                proof_data=tx.proof_data,
                status=tx.status,
                created_at=tx.created_at,
            )

        results.append(BookingDetailResponse(
            id=booking.id,
            unique_booking_code=booking.unique_booking_code,
            qr_payload=booking.qr_payload,
            centre_name=centre.name,
            state=centre.state,
            city=centre.city,
            slot_date=slot.slot_date,
            time_window=slot.time_window,
            estimated_weight_quintals=booking.estimated_weight_quintals,
            status=booking.status,
            arrived_at=booking.arrived_at,
            booked_at=booking.booked_at,
            queue_position=q_state.position if q_state and q_state.status == 'waiting' else None,
            eta_minutes=q_state.eta_minutes if q_state and q_state.status == 'waiting' else None,
            transaction=tx_brief,
        ))

    return results


@router.get('/farmer/{farmer_id}/active', response_model=BookingDetailResponse)
async def get_farmer_active_booking(farmer_id: str, db: AsyncSession = Depends(get_db)):
    bookings = await get_farmer_bookings(farmer_id, db)
    if not bookings:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='No bookings found')
    # Find active: in_queue, arrived, or booked first, else most recent completed
    for b in bookings:
        if b.status in ['arrived', 'in_queue', 'booked']:
            return b
    # Return latest
    return bookings[0]


@router.get('/farmer/{farmer_id}/history', response_model=List[BookingDetailResponse])
async def get_farmer_history(farmer_id: str, db: AsyncSession = Depends(get_db)):
    return await get_farmer_bookings(farmer_id, db)


@router.post('/{booking_id}/arrive')
async def arrive_booking_by_id(booking_id: str, db: AsyncSession = Depends(get_db)):
    booking = (await db.execute(select(Booking).where(Booking.id == booking_id))).scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Booking not found')
    return await confirm_arrival(ArrivalConfirmRequest(booking_code=booking.unique_booking_code), db)


@router.post('/{booking_id}/cancel')
async def cancel_booking_post(booking_id: str, db: AsyncSession = Depends(get_db)):
    return await cancel_booking(booking_id, db)


@router.delete('/{booking_id}')
async def cancel_booking(booking_id: str, db: AsyncSession = Depends(get_db)):
    booking = (await db.execute(select(Booking).where(Booking.id == booking_id))).scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Booking not found')

    if booking.status in ['completed', 'cancelled']:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f'Cannot cancel {booking.status} booking')

    booking.status = 'cancelled'

    # Release slot count
    slot = (await db.execute(select(Slot).where(Slot.id == booking.slot_id))).scalar_one_or_none()
    if slot and slot.booked_units > 0:
        slot.booked_units -= 1

    # Remove from queue if present
    q_state = (await db.execute(select(QueueState).where(QueueState.booking_id == booking.id))).scalar_one_or_none()
    if q_state:
        q_state.status = 'cancelled'

    await db.commit()

    # Recompute queue
    await QueueEngine.recompute_centre_queue(db, booking.centre_id)
    await db.commit()

    return {'status': 'success', 'message': 'Booking cancelled successfully. Slot capacity released.'}

