from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_

from app.core.db import get_db
from app.models.entities import User, Centre, Slot, Booking, Transaction, QueueState
from app.schemas.schemas import (
    VendorCreateRequest, BookingEditRequest, UserManagementItem
)
from app.services.queue_engine import QueueEngine

router = APIRouter(prefix='/admin', tags=['Admin Console'])


@router.post('/vendors')
async def create_vendor_mandi(payload: VendorCreateRequest, db: AsyncSession = Depends(get_db)):
    if payload.pin != payload.confirm_pin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="PIN and Confirm PIN must match exactly."
        )

    # 1. Create Centre record
    centre = Centre(
        name=payload.mandi_name,
        state=payload.state,
        city=payload.city,
        address=payload.address,
        manager_name=payload.manager_name,
        manager_aadhaar=payload.manager_aadhaar,
        manager_phone=payload.manager_phone,
        workers_count=payload.workers_count,
        capacity_factor=1.0,
        status='NORMAL',
    )
    db.add(centre)
    await db.flush()

    # 2. Create or link Vendor User
    vendor_user = (await db.execute(select(User).where(User.phone == payload.manager_phone))).scalar_one_or_none()
    if not vendor_user:
        vendor_user = User(
            phone=payload.manager_phone,
            role='vendor',
            full_name=payload.manager_name,
            aadhaar_number=payload.manager_aadhaar,
            centre_id=centre.id,
            pin=payload.pin,
        )
        db.add(vendor_user)
    else:
        vendor_user.role = 'vendor'
        vendor_user.centre_id = centre.id
        vendor_user.pin = payload.pin

    # 3. Auto-populate standard 120-minute slots for today
    today_str = datetime.now().strftime('%Y-%m-%d')
    standard_windows = [
        '08:00 - 10:00',
        '10:00 - 12:00',
        '12:00 - 14:00',
        '14:00 - 16:00',
        '16:00 - 18:00',
    ]
    for win in standard_windows:
        slot = Slot(
            centre_id=centre.id,
            slot_date=today_str,
            time_window=win,
            capacity_units=30,  # Max 30 farmers per slot
            booked_units=0,
        )
        db.add(slot)

    await db.commit()

    return {
        'status': 'success',
        'message': f'Vendor and Mandi Centre \"{centre.name}\" registered successfully by Admin.',
        'centre_id': centre.id,
        'manager_phone': vendor_user.phone,
    }


@router.get('/users', response_model=List[UserManagementItem])
async def list_users(db: AsyncSession = Depends(get_db)):
    users = (await db.execute(select(User).order_by(User.created_at.desc()))).scalars().all()
    results = []

    for u in users:
        total_b = (await db.execute(select(func.count(Booking.id)).where(Booking.farmer_id == u.id))).scalar() or 0
        active_b = (await db.execute(
            select(func.count(Booking.id)).where(
                and_(Booking.farmer_id == u.id, Booking.status.in_(['booked', 'arrived', 'in_queue']))
            )
        )).scalar() or 0

        results.append(UserManagementItem(
            id=u.id,
            phone=u.phone,
            role=u.role,
            full_name=u.full_name,
            aadhaar_number=u.aadhaar_number,
            alt_person_name=u.alt_person_name,
            active_bookings=active_b,
            total_bookings=total_b,
            created_at=u.created_at,
        ))

    return results


@router.delete('/users/{user_id}')
async def delete_user_or_vendor(user_id: str, db: AsyncSession = Depends(get_db)):
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='User not found')

    if user.role == 'admin' or user.phone in ['123456890', '1234567890', '123457890']:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Cannot delete system pre-existing admin')

    # If farmer: clean up all bookings, queue states, and transactions
    farmer_bookings = (await db.execute(select(Booking).where(Booking.farmer_id == user.id))).scalars().all()
    for b in farmer_bookings:
        slot = (await db.execute(select(Slot).where(Slot.id == b.slot_id))).scalar_one_or_none()
        if slot and slot.booked_units > 0 and b.status in ['booked', 'arrived', 'in_queue']:
            slot.booked_units -= 1

        q_states = (await db.execute(select(QueueState).where(QueueState.booking_id == b.id))).scalars().all()
        for qs in q_states:
            await db.delete(qs)

        txs = (await db.execute(select(Transaction).where(Transaction.booking_id == b.id))).scalars().all()
        for tx in txs:
            await db.delete(tx)

        await db.delete(b)

    # If vendor is linked to a centre, remove centre association and slots
    if user.centre_id:
        centre = (await db.execute(select(Centre).where(Centre.id == user.centre_id))).scalar_one_or_none()
        if centre:
            c_bookings = (await db.execute(select(Booking).where(Booking.centre_id == centre.id))).scalars().all()
            for cb in c_bookings:
                cq_states = (await db.execute(select(QueueState).where(QueueState.booking_id == cb.id))).scalars().all()
                for cqs in cq_states:
                    await db.delete(cqs)
                ctxs = (await db.execute(select(Transaction).where(Transaction.booking_id == cb.id))).scalars().all()
                for ctx in ctxs:
                    await db.delete(ctx)
                await db.delete(cb)

            c_slots = (await db.execute(select(Slot).where(Slot.centre_id == centre.id))).scalars().all()
            for cs in c_slots:
                await db.delete(cs)

            await db.delete(centre)

    # Clean up any lingering transactions referencing this user
    other_txs = (await db.execute(select(Transaction).where(or_(Transaction.farmer_id == user.id, Transaction.vendor_user_id == user.id)))).scalars().all()
    for otx in other_txs:
        await db.delete(otx)

    await db.delete(user)
    await db.commit()

    return {'status': 'success', 'message': f'{user.role.capitalize()} \"{user.full_name}\" deleted successfully.'}


@router.get('/bookings')
async def list_all_bookings(db: AsyncSession = Depends(get_db)):
    stmt = (
        select(Booking, User, Centre, Slot)
        .join(User, User.id == Booking.farmer_id)
        .join(Centre, Centre.id == Booking.centre_id)
        .join(Slot, Slot.id == Booking.slot_id)
        .order_by(Booking.booked_at.desc())
    )
    rows = (await db.execute(stmt)).all()

    return [
        {
            'id': b.id,
            'booking_id': b.id,
            'unique_booking_code': b.unique_booking_code,
            'booking_code': b.unique_booking_code,
            'farmer_name': u.full_name,
            'farmer_phone': u.phone,
            'centre_name': c.name,
            'mandi_name': c.name,
            'state': c.state,
            'city': c.city,
            'slot_date': s.slot_date,
            'time_window': s.time_window,
            'estimated_weight_quintals': b.estimated_weight_quintals,
            'estimated_weight': b.estimated_weight_quintals,
            'status': b.status,
            'booked_at': b.booked_at,
        }
        for b, u, c, s in rows
    ]


@router.patch('/bookings/{booking_id}')
async def edit_booking(booking_id: str, payload: BookingEditRequest, db: AsyncSession = Depends(get_db)):
    booking = (await db.execute(select(Booking).where(Booking.id == booking_id))).scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Booking not found')

    if payload.slot_id and payload.slot_id != booking.slot_id:
        new_slot = (await db.execute(select(Slot).where(Slot.id == payload.slot_id))).scalar_one_or_none()
        if not new_slot:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='New slot not found')
        # Adjust counters
        old_slot = (await db.execute(select(Slot).where(Slot.id == booking.slot_id))).scalar_one_or_none()
        if old_slot and old_slot.booked_units > 0:
            old_slot.booked_units -= 1
        new_slot.booked_units += 1
        booking.slot_id = payload.slot_id

    if payload.estimated_weight_quintals is not None:
        booking.estimated_weight_quintals = payload.estimated_weight_quintals

    if payload.status is not None:
        booking.status = payload.status

    await db.commit()
    return {'status': 'success', 'message': f'Booking {booking.unique_booking_code} updated successfully.'}


@router.delete('/bookings/{booking_id}')
async def delete_booking(booking_id: str, db: AsyncSession = Depends(get_db)):
    booking = (await db.execute(select(Booking).where(Booking.id == booking_id))).scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Booking not found')

    # Release slot count
    slot = (await db.execute(select(Slot).where(Slot.id == booking.slot_id))).scalar_one_or_none()
    if slot and slot.booked_units > 0 and booking.status in ['booked', 'arrived', 'in_queue']:
        slot.booked_units -= 1

    # Delete associated QueueState
    q_states = (await db.execute(select(QueueState).where(QueueState.booking_id == booking.id))).scalars().all()
    for qs in q_states:
        await db.delete(qs)

    # Delete associated Transaction
    txs = (await db.execute(select(Transaction).where(Transaction.booking_id == booking.id))).scalars().all()
    for tx in txs:
        await db.delete(tx)

    centre_id = booking.centre_id
    await db.delete(booking)
    await db.commit()

    # Recompute remaining queue if centre exists
    try:
        await QueueEngine.recompute_centre_queue(db, centre_id)
        await db.commit()
    except Exception:
        pass

    return {'status': 'success', 'message': f'Booking {booking.unique_booking_code} deleted successfully.'}
