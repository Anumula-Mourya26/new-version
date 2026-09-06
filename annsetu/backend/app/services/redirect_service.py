from datetime import datetime
from typing import Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func
from fastapi import HTTPException, status

from app.models.entities import Centre, QueueState, Token, Slot, AuditLog


class RedirectService:
    @classmethod
    async def get_district_congestion_overview(cls, db: AsyncSession, district_id: str) -> List[Dict[str, Any]]:
        # Fetch centres in district
        centres = (await db.execute(select(Centre).where(Centre.district_id == district_id))).scalars().all()
        results = []

        for centre in centres:
            # Count live waiting farmers
            waiting_count_stmt = (
                select(func.count(QueueState.id))
                .join(Token, Token.id == QueueState.token_id)
                .where(and_(Token.centre_id == centre.id, QueueState.status == 'waiting'))
            )
            waiting_count = (await db.execute(waiting_count_stmt)).scalar() or 0

            # Determine load status: green (<50%), amber (50-80%), red (>80%)
            ratio = (waiting_count / max(1, centre.daily_capacity_units))
            if ratio >= 0.8:
                load_status = 'red'
            elif ratio >= 0.5:
                load_status = 'amber'
            else:
                load_status = 'green'

            results.append({
                'id': centre.id,
                'name': centre.name,
                'district_id': centre.district_id,
                'daily_capacity': centre.daily_capacity_units,
                'active_counters': centre.weighing_points,
                'waiting_count': waiting_count,
                'load_status': load_status,
                'load_percentage': round(ratio * 100, 1),
            })

        return results

    @classmethod
    async def apply_redirect(
        cls, db: AsyncSession, from_centre_id: str, to_centre_id: str, farmer_count: int, actor_user_id: str = None
    ) -> Dict[str, Any]:
        src = (await db.execute(select(Centre).where(Centre.id == from_centre_id))).scalar_one_or_none()
        dst = (await db.execute(select(Centre).where(Centre.id == to_centre_id))).scalar_one_or_none()

        if not src or not dst:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail='One or both centres not found')

        # Shift slot capacities from source to target for open slots
        today = datetime.now().strftime('%Y-%m-%d')
        dst_slots = (await db.execute(
            select(Slot).where(and_(Slot.centre_id == to_centre_id, Slot.slot_date >= today))
        )).scalars().all()

        if dst_slots:
            # Increase target slot capacity to accept redirected farmers
            for slot in dst_slots:
                slot.capacity_units += farmer_count
                break

        # Log audit entry
        audit = AuditLog(
            actor_user_id=actor_user_id,
            entity_type='centre_redirect',
            entity_id=from_centre_id,
            action='apply_redirect',
            before_state={'from_centre': src.name, 'to_centre': dst.name, 'count': farmer_count},
            after_state={'status': 'redirect_applied', 'diverted': farmer_count},
        )
        db.add(audit)
        await db.flush()

        return {
            'status': 'success',
            'message': f'Redirected next {farmer_count} unbooked registrations from {src.name} to {dst.name}',
            'redirected_count': farmer_count,
            'source_centre': src.name,
            'target_centre': dst.name,
        }
