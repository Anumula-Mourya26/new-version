from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func

from app.core.db import get_db
from app.models.entities import Centre, Slot, QueueState, Token
from app.schemas.schemas import CentreResponse, SlotResponse
from app.services.queue_engine import QueueEngine

router = APIRouter(prefix='/centres', tags=['Centres'])


@router.get('', response_model=List[CentreResponse])
async def list_centres(district_id: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    stmt = select(Centre)
    if district_id:
        stmt = stmt.where(Centre.district_id == district_id)

    centres = (await db.execute(stmt)).scalars().all()
    results = []

    for centre in centres:
        # Count live waiting queue
        waiting_count_stmt = (
            select(func.count(QueueState.id))
            .join(Token, Token.id == QueueState.token_id)
            .where(and_(Token.centre_id == centre.id, QueueState.status == 'waiting'))
        )
        waiting_count = (await db.execute(waiting_count_stmt)).scalar() or 0

        # Load indicator
        ratio = waiting_count / max(1, centre.daily_capacity_units)
        load_status = 'red' if ratio >= 0.8 else ('amber' if ratio >= 0.5 else 'green')

        # Live ETA for next arrival
        eta = QueueEngine.calculate_eta(position=waiting_count + 1, active_counters=centre.weighing_points)

        results.append(CentreResponse(
            id=centre.id,
            name=centre.name,
            district_id=centre.district_id,
            latitude=centre.latitude,
            longitude=centre.longitude,
            daily_capacity_units=centre.daily_capacity_units,
            weighing_points=centre.weighing_points,
            operating_hours=centre.operating_hours,
            status=centre.status,
            live_waiting_count=waiting_count,
            load_status=load_status,
            current_eta_minutes=eta,
        ))

    return results


@router.get('/{centre_id}/slots', response_model=List[SlotResponse])
async def list_centre_slots(centre_id: str, db: AsyncSession = Depends(get_db)):
    centre = (await db.execute(select(Centre).where(Centre.id == centre_id))).scalar_one_or_none()
    if not centre:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Centre not found')

    slots = (await db.execute(select(Slot).where(Slot.centre_id == centre_id))).scalars().all()
    return [
        SlotResponse(
            id=slot.id,
            centre_id=slot.centre_id,
            slot_date=slot.slot_date,
            time_window=slot.time_window,
            capacity_units=slot.capacity_units,
            booked_units=slot.booked_units,
            remaining_units=max(0, slot.capacity_units - slot.booked_units),
        )
        for slot in slots
    ]
