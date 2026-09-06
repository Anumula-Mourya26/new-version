import math
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, and_

from app.models.entities import Token, QueueState, Centre, Booking


class QueueEngine:
    # Baseline service duration: 20 minutes per farmer / tractor
    DEFAULT_SERVICE_MINUTES = 20

    @staticmethod
    def calculate_eta(position: int, active_counters: int, service_minutes_per_counter: float = DEFAULT_SERVICE_MINUTES) -> int:
        """
        M/M/c Queueing model closed-form calculation:
        ETA = ceil( (position - 1) * (service_time / active_counters) )
        """
        if position <= 0:
            return 0
        c = max(1, active_counters)
        # Time for the (position-1) farmers ahead to clear across c counters
        wait_time = math.ceil(((position - 1) * service_minutes_per_counter) / c)
        return wait_time

    @classmethod
    async def recompute_centre_queue(cls, db: AsyncSession, centre_id: str) -> List[Dict[str, Any]]:
        """
        Recomputes live positions and ETAs for all waiting tokens in a procurement centre.
        """
        # 1. Fetch centre details (for weighing_points / counters c)
        centre_res = await db.execute(select(Centre).where(Centre.id == centre_id))
        centre = centre_res.scalar_one_or_none()
        c = centre.weighing_points if centre else 2

        # 2. Fetch all waiting tokens ordered by issued_at (FIFO)
        stmt = (
            select(Token, QueueState)
            .join(QueueState, Token.id == QueueState.token_id)
            .where(and_(Token.centre_id == centre_id, QueueState.status == 'waiting'))
            .order_by(Token.issued_at.asc())
        )
        results = (await db.execute(stmt)).all()

        updated_items = []
        now = datetime.now(timezone.utc)

        for idx, (token, q_state) in enumerate(results, start=1):
            eta = cls.calculate_eta(position=idx, active_counters=c)
            q_state.position = idx
            q_state.eta_minutes = eta
            q_state.computed_at = now

            updated_items.append({
                'token_id': token.id,
                'token_number': token.token_number,
                'position': idx,
                'eta_minutes': eta,
            })

        await db.flush()
        return updated_items
