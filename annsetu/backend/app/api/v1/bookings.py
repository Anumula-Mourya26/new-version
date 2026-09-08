import uuid
from datetime import datetime, timezone
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func

from app.core.db import get_db
from app.models.entities import Booking, BookingCrop, Slot, Centre, User, QueueState, Transaction
from app.schemas.schemas import (
    BookingCreateRequest, BookingDetailResponse, ArrivalConfirmRequest, TransactionBrief
)
from app.services.queue_engine import QueueEngine
from app.services.sms_service import SMSService
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

    # 2. Multi-crop calculations
    crops_list = []
    if payload.crops and len(payload.crops) > 0:
        total_weight = sum(c.estimated_weight_quintals for c in payload.crops)
        primary_crop = payload.crops[0].crop_name
        crops_list = [c.model_dump() for c in payload.crops]
    else:
        total_weight = payload.estimated_weight_quintals if payload.estimated_weight_quintals else 10.0
        primary_crop = payload.primary_crop or 'Wheat'
        crops_list = [{"crop_name": primary_crop, "estimated_weight_quintals": total_weight, "msp_rate": 2320.0}]

    code = generate_booking_code()
    qr_payload = f'ANNSETU:{code}:{farmer.phone}:{total_weight:.1f}'

    booking = Booking(
        farmer_id=payload.farmer_id,
        centre_id=payload.centre_id,
        slot_id=payload.slot_id,
        estimated_weight_quintals=round(total_weight, 2),
        primary_crop=primary_crop,
        crops_data=crops_list,
        unique_booking_code=code,
        qr_payload=qr_payload,
        status='booked',
        sms_status='pending',
    )
    slot.booked_units += 1

    db.add(booking)
    await db.flush()  # Generate booking.id

    # Create BookingCrop records
    for crop_item in crops_list:
        b_crop = BookingCrop(
            booking_id=booking.id,
            crop_name=crop_item.get('crop_name', primary_crop),
            estimated_weight_quintals=float(crop_item.get('estimated_weight_quintals', 0.0)),
            msp_rate=float(crop_item.get('msp_rate', 2320.0)),
        )
        db.add(b_crop)

    # 3. SMS Notification (Non-blocking resilience)
    crops_summary = ", ".join(f"{c['crop_name']} ({c['estimated_weight_quintals']:.1f}Q)" for c in crops_list)
    try:
        sms_res = await SMSService.send_booking_confirmation(
            to_phone=farmer.phone,
            farmer_name=farmer.full_name,
            booking_code=code,
            mandi_name=centre.name,
            slot_date=slot.slot_date,
            slot_time=slot.time_window,
            crops_summary=crops_summary,
            total_weight=total_weight,
        )
        booking.sms_status = sms_res.get('status', 'sent')
        if not sms_res.get('success'):
            booking.sms_error = sms_res.get('error')
    except Exception as exc:
        booking.sms_status = 'failed'
        booking.sms_error = str(exc)

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
        primary_crop=booking.primary_crop,
        crops_data=booking.crops_data,
        sms_status=booking.sms_status,
        sms_error=booking.sms_error,
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

    await db.commit()

    return {
        'status': 'success',
        'booking_status': booking.status,
        'message': 'Arrival confirmed! Please proceed to the Mandi gate for physical verification and admission by the vendor.',
        'position': None,
        'eta_minutes': None,
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
                proof_image=tx.proof_image,
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
            primary_crop=booking.primary_crop,
            crops_data=booking.crops_data,
            sms_status=booking.sms_status,
            sms_error=booking.sms_error,
            status=booking.status,
            arrived_at=booking.arrived_at,
            booked_at=booking.booked_at,
            queue_position=q_state.position if q_state and q_state.status == 'waiting' else None,
            eta_minutes=q_state.eta_minutes if q_state and q_state.status == 'waiting' else None,
            workers_count=centre.workers_count,
            capacity_factor=centre.capacity_factor,
            transaction=tx_brief,
        ))

    return results


@router.post('/{booking_id}/resend-sms')
async def resend_booking_sms(booking_id: str, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(Booking, Centre, Slot, User)
        .join(Centre, Centre.id == Booking.centre_id)
        .join(Slot, Slot.id == Booking.slot_id)
        .join(User, User.id == Booking.farmer_id)
        .where(Booking.id == booking_id)
    )
    row = (await db.execute(stmt)).first()
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Booking not found')

    booking, centre, slot, farmer = row

    crops_list = booking.crops_data or [{"crop_name": booking.primary_crop or 'Wheat', "estimated_weight_quintals": booking.estimated_weight_quintals}]
    crops_summary = ", ".join(f"{c['crop_name']} ({c['estimated_weight_quintals']:.1f}Q)" for c in crops_list)

    sms_res = await SMSService.send_booking_confirmation(
        to_phone=farmer.phone,
        farmer_name=farmer.full_name,
        booking_code=booking.unique_booking_code,
        mandi_name=centre.name,
        slot_date=slot.slot_date,
        slot_time=slot.time_window,
        crops_summary=crops_summary,
        total_weight=booking.estimated_weight_quintals,
    )
    booking.sms_status = sms_res.get('status', 'sent')
    booking.sms_error = sms_res.get('error') if not sms_res.get('success') else None
    await db.commit()

    return {
        'status': 'success',
        'sms_status': booking.sms_status,
        'sms_error': booking.sms_error,
        'recipient': sms_res.get('recipient'),
        'sid': sms_res.get('sid'),
        'details': sms_res,
    }


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

