import random
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.db import get_db
from app.models.entities import Procurement, Payment, Token, QueueState, Commodity
from app.schemas.schemas import ProcurementCreate, ProcurementResponse
from app.services.queue_engine import QueueEngine
from app.ws.queue_ws import manager

router = APIRouter(prefix='/procurement', tags=['Procurement'])


@router.post('', response_model=ProcurementResponse)
async def record_procurement(payload: ProcurementCreate, db: AsyncSession = Depends(get_db)):
    token = (await db.execute(select(Token).where(Token.id == payload.token_id))).scalar_one_or_none()
    if not token:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Token not found')

    existing = (await db.execute(select(Procurement).where(Procurement.token_id == payload.token_id))).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='Procurement already recorded for this token')

    # Fetch default MSP rate for Paddy (2320 INR/quintal)
    msp_rate = 2320.00
    amount_due = (payload.weighed_quantity_quintals * msp_rate) if payload.quality_result == 'accepted' and payload.weighed_quantity_quintals else None

    receipt_ref = f'REC-AS-{random.randint(100000, 999999)}' if payload.quality_result == 'accepted' else None

    proc = Procurement(
        token_id=payload.token_id,
        moisture_pct=payload.moisture_pct,
        quality_result=payload.quality_result,
        weighed_quantity_quintals=payload.weighed_quantity_quintals,
        receipt_ref=receipt_ref,
    )
    db.add(proc)
    await db.flush()

    # Create Initial Payment entry in 'sold' stage
    if payload.quality_result == 'accepted' and amount_due:
        payment = Payment(
            procurement_id=proc.id,
            amount_due=amount_due,
            payee_type='farmer_direct',
            stage='sold',
        )
        db.add(payment)

    # Mark token queue state as 'served'
    q_state = (await db.execute(select(QueueState).where(QueueState.token_id == payload.token_id))).scalar_one_or_none()
    if q_state:
        q_state.status = 'served'

    await db.commit()

    # Dynamic queue recomputation and WebSocket broadcast
    updated_queue = await QueueEngine.recompute_centre_queue(db, token.centre_id)
    await db.commit()

    await manager.broadcast_queue_update(
        token.centre_id,
        {
            'event': 'service_completed',
            'served_token': token.token_number,
            'updated_queue': updated_queue,
        }
    )

    return ProcurementResponse(
        procurement_id=proc.id,
        receipt_ref=proc.receipt_ref,
        quality_result=proc.quality_result,
        weighed_quantity_quintals=proc.weighed_quantity_quintals,
        amount_due=amount_due,
    )
