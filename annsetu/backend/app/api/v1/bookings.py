import random
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.db import get_db
from app.models.entities import Booking, Slot, Centre, Farmer
from app.schemas.schemas import BookingCreate, BookingResponse

router = APIRouter(prefix='/bookings', tags=['Bookings'])


def generate_booking_code() -> str:
    return f'AS-{random.randint(1000, 9999)}'


@router.post('', response_model=BookingResponse)
async def create_booking(payload: BookingCreate, db: AsyncSession = Depends(get_db)):
    slot = (await db.execute(select(Slot).where(Slot.id == payload.slot_id))).scalar_one_or_none()
    if not slot:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Slot not found')

    if slot.booked_units >= slot.capacity_units:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='Slot is fully booked. Please select an alternate slot or centre.')

    farmer = (await db.execute(select(Farmer).where(Farmer.id == payload.farmer_id))).scalar_one_or_none()
    if not farmer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Farmer profile not found')

    centre = (await db.execute(select(Centre).where(Centre.id == slot.centre_id))).scalar_one_or_none()

    # Create booking and increment slot booked units
    code = generate_booking_code()
    booking = Booking(
        farmer_id=payload.farmer_id,
        slot_id=payload.slot_id,
        declared_quantity_quintals=payload.declared_quantity_quintals,
        status='booked',
        unique_booking_code=code,
    )
    slot.booked_units += 1

    db.add(booking)
    await db.commit()
    await db.refresh(booking)

    return BookingResponse(
        booking_id=booking.id,
        unique_booking_code=booking.unique_booking_code,
        status=booking.status,
        slot_date=slot.slot_date,
        time_window=slot.time_window,
        centre_name=centre.name if centre else 'Procurement Centre',
    )


@router.delete('/{booking_id}')
async def cancel_booking(booking_id: str, db: AsyncSession = Depends(get_db)):
    booking = (await db.execute(select(Booking).where(Booking.id == booking_id))).scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Booking not found')

    if booking.status != 'booked':
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Cannot cancel checked-in or completed booking')

    booking.status = 'cancelled'

    # Release slot capacity
    slot = (await db.execute(select(Slot).where(Slot.id == booking.slot_id))).scalar_one_or_none()
    if slot and slot.booked_units > 0:
        slot.booked_units -= 1

    await db.commit()
    return {'status': 'success', 'message': 'Booking cancelled successfully and slot capacity released'}
