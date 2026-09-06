from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func

from app.core.db import get_db
from app.models.entities import Booking, Slot, Token, QueueState, Centre
from app.schemas.schemas import GateCheckInRequest, CheckInResponse
from app.services.queue_engine import QueueEngine
from app.ws.queue_ws import manager

router = APIRouter(prefix='/gate', tags=['Gate Check-In'])


@router.post('/check-in', response_model=CheckInResponse)
async def gate_check_in(payload: GateCheckInRequest, db: AsyncSession = Depends(get_db)):
    if not payload.booking_code and not payload.qr_payload:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Either booking_code or qr_payload is required')

    # Look up booking
    stmt = select(Booking, Slot).join(Slot, Slot.id == Booking.slot_id)
    if payload.booking_code:
        stmt = stmt.where(Booking.unique_booking_code == payload.booking_code)
    else:
        # QR payload format: "ANNSETU:{booking_code}:{farmer_id}"
        code = payload.qr_payload.split(':')[1] if ':' in payload.qr_payload else payload.qr_payload
        stmt = stmt.where(Booking.unique_booking_code == code)

    res = (await db.execute(stmt)).first()
    if not res:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Valid booking not found')

    booking, slot = res

    if booking.status == 'checked_in':
        # Return existing token
        token_stmt = select(Token, QueueState).join(QueueState, QueueState.token_id == Token.id).where(Token.booking_id == booking.id)
        t_res = (await db.execute(token_stmt)).first()
        if t_res:
            token, q_state = t_res
            return CheckInResponse(
                token_id=token.id,
                token_number=token.token_number,
                position=q_state.position,
                eta_minutes=q_state.eta_minutes,
                centre_id=token.centre_id,
                issued_at=token.issued_at,
            )

    if booking.status != 'booked':
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f'Booking status is {booking.status}, cannot check-in')

    # Generate daily sequence token number
    count_stmt = select(func.count(Token.id)).where(Token.centre_id == slot.centre_id)
    daily_seq = ((await db.execute(count_stmt)).scalar() or 0) + 1

    token = Token(
        booking_id=booking.id,
        centre_id=slot.centre_id,
        token_number=daily_seq,
        qr_payload=f'TOKEN:{slot.centre_id}:{daily_seq}:{booking.unique_booking_code}',
    )
    booking.status = 'checked_in'
    db.add(token)
    await db.flush()

    # Create initial queue state
    # Count waiting farmers ahead
    waiting_stmt = (
        select(func.count(QueueState.id))
        .join(Token, Token.id == QueueState.token_id)
        .where(and_(Token.centre_id == slot.centre_id, QueueState.status == 'waiting'))
    )
    position = ((await db.execute(waiting_stmt)).scalar() or 0) + 1

    centre = (await db.execute(select(Centre).where(Centre.id == slot.centre_id))).scalar_one()
    eta = QueueEngine.calculate_eta(position=position, active_counters=centre.weighing_points)

    q_state = QueueState(
        centre_id=slot.centre_id,
        token_id=token.id,
        position=position,
        eta_minutes=eta,
        status='waiting',
    )
    db.add(q_state)
    await db.commit()

    # Trigger async recompute and WebSocket broadcast
    updated_queue = await QueueEngine.recompute_centre_queue(db, slot.centre_id)
    await db.commit()

    await manager.broadcast_queue_update(
        slot.centre_id,
        {
            'event': 'check_in',
            'token_number': token.token_number,
            'new_position': position,
            'updated_queue': updated_queue,
        }
    )

    return CheckInResponse(
        token_id=token.id,
        token_number=token.token_number,
        position=position,
        eta_minutes=eta,
        centre_id=slot.centre_id,
        issued_at=token.issued_at,
    )
