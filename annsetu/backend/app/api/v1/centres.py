from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func

from app.core.db import get_db
from app.models.entities import Centre, Slot, QueueState
from app.schemas.schemas import CentreResponse, SlotResponse
from app.services.queue_engine import QueueEngine

router = APIRouter(prefix='/centres', tags=['Centres'])


@router.get('/states-cities')
async def get_states_and_cities(db: AsyncSession = Depends(get_db)):
    centres = (await db.execute(select(Centre))).scalars().all()
    mapping = {}
    for c in centres:
        if c.state not in mapping:
            mapping[c.state] = set()
        mapping[c.state].add(c.city)

    return {state: sorted(list(cities)) for state, cities in mapping.items()}


@router.get('', response_model=List[CentreResponse])
async def list_centres(
    state: Optional[str] = None,
    city: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Centre)
    if state:
        stmt = stmt.where(Centre.state == state)
    if city:
        stmt = stmt.where(Centre.city == city)

    centres = (await db.execute(stmt)).scalars().all()
    results = []

    for centre in centres:
        # Count live waiting queue (N)
        waiting_stmt = select(func.count(QueueState.id)).where(
            and_(QueueState.centre_id == centre.id, QueueState.status == 'waiting')
        )
        waiting_count = (await db.execute(waiting_stmt)).scalar() or 0

        # AnnSetu dynamic ETA formula: ceil( (N * 25) / (C * F) )
        eta = QueueEngine.calculate_eta(
            n=waiting_count + 1,
            c=centre.workers_count,
            f=centre.capacity_factor,
            status=centre.status
        )

        results.append(CentreResponse(
            id=centre.id,
            name=centre.name,
            state=centre.state,
            city=centre.city,
            address=centre.address,
            manager_name=centre.manager_name,
            manager_phone=centre.manager_phone,
            workers_count=centre.workers_count,
            capacity_factor=centre.capacity_factor,
            status=centre.status,
            live_waiting_count=waiting_count,
            current_eta_minutes=eta,
        ))

    return results


@router.get('/{centre_id}/slots', response_model=List[SlotResponse])
async def list_centre_slots(
    centre_id: str,
    slot_date: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    centre = (await db.execute(select(Centre).where(Centre.id == centre_id))).scalar_one_or_none()
    if not centre:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='Centre not found')

    target_date = slot_date or datetime.now().strftime('%Y-%m-%d')
    stmt = (
        select(Slot)
        .where(and_(Slot.centre_id == centre_id, Slot.slot_date == target_date))
        .order_by(Slot.time_window.asc())
    )
    slots = (await db.execute(stmt)).scalars().all()

    # If no slots exist yet for target_date, auto-create standard 120-min windows
    if not slots:
        standard_windows = [
            '08:00 - 10:00',
            '10:00 - 12:00',
            '12:00 - 14:00',
            '14:00 - 16:00',
            '16:00 - 18:00',
        ]
        slots = []
        for win in standard_windows:
            s = Slot(
                centre_id=centre_id,
                slot_date=target_date,
                time_window=win,
                capacity_units=30,  # Max 30 farmers per slot
                booked_units=0,
            )
            db.add(s)
            slots.append(s)
        await db.commit()

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

