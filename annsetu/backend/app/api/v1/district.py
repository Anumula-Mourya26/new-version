from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.schemas.schemas import RedirectSuggestionRequest, RedirectSuggestionResponse
from app.services.redirect_service import RedirectService

router = APIRouter(prefix='/district', tags=['District Congestion Command'])


@router.get('/{district_id}/congestion')
async def get_district_congestion(district_id: str, db: AsyncSession = Depends(get_db)):
    overview = await RedirectService.get_district_congestion_overview(db, district_id)
    return {'district_id': district_id, 'centres': overview}


@router.post('/{district_id}/redirect', response_model=RedirectSuggestionResponse)
async def apply_district_redirect(district_id: str, payload: RedirectSuggestionRequest, db: AsyncSession = Depends(get_db)):
    result = await RedirectService.apply_redirect(
        db=db,
        from_centre_id=payload.from_centre_id,
        to_centre_id=payload.to_centre_id,
        farmer_count=payload.farmer_count,
    )
    await db.commit()
    return RedirectSuggestionResponse(**result)
