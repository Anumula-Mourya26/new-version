from typing import Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.core.db import get_db
from app.core.security import get_current_user_token
from app.models.entities import User, Farmer, Booking, Token, Procurement, Payment, Slot
from app.schemas.schemas import FarmerRegister, FarmerResponse, FarmerStatusTimelineResponse, PaymentTimelineItem

router = APIRouter(prefix='/farmers', tags=['Farmers'])


@router.post('', response_model=FarmerResponse)
async def register_farmer(payload: FarmerRegister, db: AsyncSession = Depends(get_db)):
    # Check if aadhaar_ref exists
    existing = (await db.execute(select(Farmer).where(Farmer.aadhaar_ref == payload.aadhaar_ref))).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='Farmer already registered with this Aadhaar reference')

    # Get or create user
    user = (await db.execute(select(User).where(User.phone == payload.phone))).scalar_one_or_none()
    if not user:
        user = User(
            phone=payload.phone,
            role='farmer',
            full_name=payload.full_name,
            preferred_language=payload.preferred_language,
            district_id=payload.district_id,
        )
        db.add(user)
        await db.flush()
    else:
        user.full_name = payload.full_name
        user.district_id = payload.district_id

    farmer = Farmer(
        id=user.id,
        aadhaar_ref=payload.aadhaar_ref,
        land_record_ref=payload.land_record_ref,
        bank_account_ref=payload.bank_account_ref,
        is_sharecropper=payload.is_sharecropper,
        consent_letter_doc_ref=payload.consent_letter_doc_ref,
        village=payload.village,
        district_id=payload.district_id,
    )
    db.add(farmer)
    await db.commit()

    return FarmerResponse(
        id=farmer.id,
        phone=user.phone,
        full_name=user.full_name,
        village=farmer.village,
        district_id=farmer.district_id,
        is_sharecropper=farmer.is_sharecropper,
        bank_account_ref=farmer.bank_account_ref,
    )


@router.get('/{farmer_id}/status-timeline', response_model=FarmerStatusTimelineResponse)
async def get_farmer_status_timeline(farmer_id: str, db: AsyncSession = Depends(get_db)):
    # Fetch active or most recent booking for this farmer
    stmt = (
        select(Booking)
        .where(Booking.farmer_id == farmer_id)
        .order_by(Booking.booked_at.desc())
    )
    booking = (await db.execute(stmt)).scalars().first()
    if not booking:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='No booking records found for this farmer')

    slot = (await db.execute(select(Slot).where(Slot.id == booking.slot_id))).scalar_one_or_none()
    token = (await db.execute(select(Token).where(Token.booking_id == booking.id))).scalar_one_or_none()

    procurement = None
    payment = None
    if token:
        procurement = (await db.execute(select(Procurement).where(Procurement.token_id == token.id))).scalar_one_or_none()
        if procurement:
            payment = (await db.execute(select(Payment).where(Payment.procurement_id == procurement.id))).scalar_one_or_none()

    current_stage = payment.stage if payment else ('sold' if procurement else 'pending')

    # Construct the 4-stage AnnSetu timeline
    stages = ['sold', 'advice_generated', 'advice_reached_agent', 'credited']
    stage_idx = stages.index(current_stage) if current_stage in stages else -1

    timeline = [
        PaymentTimelineItem(
            stage='sold',
            timestamp=procurement.recorded_at if procurement else booking.booked_at,
            is_completed=stage_idx >= 0,
            description='Produce inspected and weighed at APMC weighbridge.',
        ),
        PaymentTimelineItem(
            stage='advice_generated',
            timestamp=payment.stage_updated_at if payment and stage_idx >= 1 else booking.booked_at,
            is_completed=stage_idx >= 1,
            description='Payment Advice generated on PFMS / DBT rail.',
        ),
        PaymentTimelineItem(
            stage='advice_reached_agent',
            timestamp=payment.stage_updated_at if payment and stage_idx >= 2 else booking.booked_at,
            is_completed=stage_idx >= 2,
            description='Commission Agent / Intermediary ledger reconciliation confirmed.',
        ),
        PaymentTimelineItem(
            stage='credited',
            timestamp=payment.stage_updated_at if payment and stage_idx >= 3 else booking.booked_at,
            is_completed=stage_idx >= 3,
            description='Direct Benefit Transfer (DBT) funds credited to bank account.',
        ),
    ]

    return FarmerStatusTimelineResponse(
        booking_code=booking.unique_booking_code,
        status=booking.status,
        slot_time=f'{slot.slot_date} ({slot.time_window})' if slot else '',
        arrival_time=token.issued_at if token else None,
        weighed_quantity=procurement.weighed_quantity_quintals if procurement else None,
        msp_amount=payment.amount_due if payment else None,
        payment_stage=current_stage,
        utr_ref=payment.utr_ref if payment else None,
        timeline=timeline,
    )
