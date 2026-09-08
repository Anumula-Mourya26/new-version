import math
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.models.entities import Booking, QueueState, Centre


class QueueEngine:
    T_BASE_MINUTES = 25  # Baseline handling time per tractor/farmer
    MIN_FACTOR = 0.05

    @classmethod
    def calculate_eta(
        cls,
        n: int,
        c: int,
        f: float,
        status: str = 'NORMAL',
        t_base: int = T_BASE_MINUTES
    ) -> Optional[int]:
        """
        AnnSetu Smart Queue Formula:
        ETA = ceil( (N * T_base) / (C * F) )
        """
        if status == 'PAUSED' or f <= 0 or c <= 0:
            return None  # Indeterminate wait time

        if n <= 0:
            return 0

        effective_f = max(f, cls.MIN_FACTOR)
        raw_minutes = (n * t_base) / (c * effective_f)
        return math.ceil(raw_minutes)

    @classmethod
    async def recompute_centre_queue(cls, db: AsyncSession, centre_id: str) -> List[Dict[str, Any]]:
        # Fetch centre operational settings (C and F)
        centre = (await db.execute(select(Centre).where(Centre.id == centre_id))).scalar_one_or_none()
        if not centre:
            return []

        c = centre.workers_count
        f = centre.capacity_factor
        status = centre.status

        # Fetch all waiting queue entries ordered by arrival
        stmt = (
            select(QueueState, Booking)
            .join(Booking, Booking.id == QueueState.booking_id)
            .where(and_(QueueState.centre_id == centre_id, QueueState.status == 'waiting'))
            .order_by(QueueState.computed_at.asc())
        )
        results = (await db.execute(stmt)).all()

        updated_items = []
        now = datetime.now(timezone.utc)

        for idx, (q_state, booking) in enumerate(results, start=1):
            eta = cls.calculate_eta(n=idx, c=c, f=f, status=status)
            q_state.position = idx
            q_state.eta_minutes = eta
            q_state.computed_at = now

            updated_items.append({
                'booking_id': booking.id,
                'booking_code': booking.unique_booking_code,
                'position': idx,
                'eta_minutes': eta,
                'status': q_state.status,
            })

        await db.flush()
        return updated_items
