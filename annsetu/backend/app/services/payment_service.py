from datetime import datetime, timezone
import random
from typing import Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException, status

from app.models.entities import Payment, Procurement, Token, Booking, Notification


class PaymentService:
    STAGE_ORDER = ['sold', 'advice_generated', 'advice_reached_agent', 'credited']

    STAGE_DESCRIPTIONS = {
        'sold': 'Produce inspected and weighed at procurement centre. MSP procurement record issued.',
        'advice_generated': 'Procurement Agency (FCI/Markfed) generated digital Payment Advice on PFMS.',
        'advice_reached_agent': 'Payment Advice verified by Commission Agent / Intermediary ledger.',
        'credited': 'Direct Benefit Transfer (DBT) completed. Amount credited to farmer bank account.',
    }

    @classmethod
    async def update_stage(
        cls, db: AsyncSession, payment_id: str, new_stage: str, utr_ref: Optional[str] = None
    ) -> Payment:
        stmt = select(Payment).where(Payment.id == payment_id)
        payment = (await db.execute(stmt)).scalar_one_or_none()
        if not payment:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Payment record not found')

        if new_stage not in cls.STAGE_ORDER:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f'Invalid payment stage: {new_stage}')

        current_idx = cls.STAGE_ORDER.index(payment.stage)
        new_idx = cls.STAGE_ORDER.index(new_stage)

        # Enforce forward-only progression
        if new_idx <= current_idx:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f'Cannot transition backwards from {payment.stage} to {new_stage}'
            )

        payment.stage = new_stage
        payment.stage_updated_at = datetime.now(timezone.utc)

        if new_stage == 'credited':
            payment.utr_ref = utr_ref or f'UTIB{random.randint(100000000, 999999999)}'

        # Fetch farmer user id to send notification
        proc_stmt = (
            select(Booking.farmer_id)
            .join(Token, Token.booking_id == Booking.id)
            .join(Procurement, Procurement.token_id == Token.id)
            .where(Procurement.id == payment.procurement_id)
        )
        farmer_id = (await db.execute(proc_stmt)).scalar_one_or_none()

        if farmer_id:
            notif = Notification(
                user_id=farmer_id,
                channel='sms',
                event_type='payment_updated',
                payload_text=f'AnnSetu: MSP Payment status updated to {new_stage.upper()}. {cls.STAGE_DESCRIPTIONS[new_stage]}'
            )
            db.add(notif)

        await db.flush()
        return payment
