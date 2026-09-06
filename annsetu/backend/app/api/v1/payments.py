from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.schemas.schemas import PaymentStageUpdate
from app.services.payment_service import PaymentService

router = APIRouter(prefix='/payments', tags=['Payments'])


@router.patch('/{payment_id}/stage')
async def update_payment_stage(payment_id: str, payload: PaymentStageUpdate, db: AsyncSession = Depends(get_db)):
    payment = await PaymentService.update_stage(
        db=db,
        payment_id=payment_id,
        new_stage=payload.stage,
        utr_ref=payload.utr_ref,
    )
    await db.commit()
    return {
        'status': 'success',
        'payment_id': payment.id,
        'new_stage': payment.stage,
        'utr_ref': payment.utr_ref,
        'updated_at': payment.stage_updated_at,
    }
