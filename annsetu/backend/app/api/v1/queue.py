from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.core.db import get_db, AsyncSessionLocal
from app.models.entities import Centre, QueueState, Token, Booking, User
from app.schemas.schemas import QueueStatusResponse, QueueItem
from app.services.queue_engine import QueueEngine
from app.ws.queue_ws import manager

router = APIRouter(prefix='/queue', tags=['Live Queue'])


@router.get('/{centre_id}/live', response_model=QueueStatusResponse)
async def get_live_queue(centre_id: str, db: AsyncSession = Depends(get_db)):
    centre = (await db.execute(select(Centre).where(Centre.id == centre_id))).scalar_one_or_none()
    if not centre:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Centre not found')

    # Fetch waiting queue
    stmt = (
        select(QueueState, Token, Booking, User)
        .join(Token, Token.id == QueueState.token_id)
        .join(Booking, Booking.id == Token.booking_id)
        .join(User, User.id == Booking.farmer_id)
        .where(and_(Token.centre_id == centre_id, QueueState.status == 'waiting'))
        .order_by(QueueState.position.asc())
    )
    rows = (await db.execute(stmt)).all()

    queue_items = [
        QueueItem(
            token_number=token.token_number,
            unique_booking_code=booking.unique_booking_code,
            farmer_name=user.full_name,
            position=q.position,
            eta_minutes=q.eta_minutes,
            status=q.status,
        )
        for q, token, booking, user in rows
    ]

    total_waiting = len(queue_items)
    est_wait = QueueEngine.calculate_eta(position=total_waiting, active_counters=centre.weighing_points)

    return QueueStatusResponse(
        centre_id=centre.id,
        centre_name=centre.name,
        total_waiting=total_waiting,
        active_counters=centre.weighing_points,
        estimated_wait_time_minutes=est_wait,
        queue=queue_items,
    )


@router.websocket('/{centre_id}/ws')
async def websocket_queue_endpoint(websocket: WebSocket, centre_id: str):
    await manager.connect(centre_id, websocket)
    try:
        while True:
            # Keep-alive heartbeat
            data = await websocket.receive_text()
            if data == 'ping':
                await websocket.send_text('pong')
    except WebSocketDisconnect:
        manager.disconnect(centre_id, websocket)
