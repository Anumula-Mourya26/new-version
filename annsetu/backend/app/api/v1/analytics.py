from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func

from app.core.db import get_db
from app.models.entities import Centre, Slot, Booking, BookingCrop, Transaction
from app.schemas.schemas import (
    CropTrendsResponse, CropTrendPoint,
    ProcurementSignalsResponse, ProcurementSignalItem
)

router = APIRouter(prefix='/analytics', tags=['Analytics & Market Intelligence'])

DEFAULT_MSP_RATES = {
    'Wheat': 2320.0,
    'Paddy': 2300.0,
    'Mustard': 5650.0,
    'Gram': 5440.0,
    'Cotton': 7121.0,
    'Maize': 2225.0,
}

MANDI_DAILY_TARGETS = {
    'Wheat': 300.0,
    'Paddy': 250.0,
    'Mustard': 150.0,
    'Gram': 100.0,
    'Cotton': 120.0,
    'Maize': 80.0,
}


@router.get('/crop-trends', response_model=CropTrendsResponse)
async def get_crop_trends(
    centre_id: Optional[str] = Query(None, description="Filter by centre ID"),
    timeframe: str = Query("daily", description="Timeframe: daily, weekly, monthly, seasonal"),
    crop: Optional[str] = Query(None, description="Optional single crop filter"),
    db: AsyncSession = Depends(get_db),
):
    """
    Tenure-wise graphical trend analysis using recorded database bookings & crops.
    Aggregates volume, frequency, and MSP pricing trends.
    """
    stmt = (
        select(BookingCrop, Booking, Slot)
        .join(Booking, Booking.id == BookingCrop.booking_id)
        .join(Slot, Slot.id == Booking.slot_id)
        .where(Booking.status != 'cancelled')
    )

    if centre_id:
        stmt = stmt.where(Booking.centre_id == centre_id)
    if crop:
        stmt = stmt.where(BookingCrop.crop_name == crop)

    rows = (await db.execute(stmt)).all()

    # Aggregate by (period, crop_name)
    period_crop_map: Dict[str, Dict[str, Any]] = {}
    crops_seen = set()
    summary_map: Dict[str, Dict[str, Any]] = {}

    for b_crop, booking, slot in rows:
        c_name = b_crop.crop_name
        crops_seen.add(c_name)

        slot_dt_str = slot.slot_date  # YYYY-MM-DD
        try:
            dt = datetime.strptime(slot_dt_str, "%Y-%m-%d")
        except Exception:
            dt = datetime.now()

        if timeframe == "weekly":
            period = f"{dt.year}-W{dt.isocalendar()[1]:02d}"
        elif timeframe == "monthly":
            period = dt.strftime("%b %Y")
        elif timeframe == "seasonal":
            month = dt.month
            season = "Rabi" if month in (10, 11, 12, 1, 2, 3) else "Kharif"
            period = f"{season} {dt.year}"
        else:  # daily
            period = slot_dt_str

        key = f"{period}::{c_name}"
        if key not in period_crop_map:
            period_crop_map[key] = {
                "period": period,
                "crop_name": c_name,
                "volume_quintals": 0.0,
                "booking_count": 0,
                "msp_rate": b_crop.msp_rate or DEFAULT_MSP_RATES.get(c_name, 2320.0),
                "estimated_value": 0.0,
            }

        period_crop_map[key]["volume_quintals"] += b_crop.estimated_weight_quintals
        period_crop_map[key]["booking_count"] += 1
        period_crop_map[key]["estimated_value"] += b_crop.estimated_weight_quintals * period_crop_map[key]["msp_rate"]

        # Crop Summary Aggregate
        if c_name not in summary_map:
            summary_map[c_name] = {
                "total_volume_quintals": 0.0,
                "total_bookings": 0,
                "total_estimated_value": 0.0,
                "current_msp_rate": DEFAULT_MSP_RATES.get(c_name, 2320.0),
            }
        summary_map[c_name]["total_volume_quintals"] += b_crop.estimated_weight_quintals
        summary_map[c_name]["total_bookings"] += 1
        summary_map[c_name]["total_estimated_value"] += b_crop.estimated_weight_quintals * (b_crop.msp_rate or 2320.0)

    # Sort trend points by period
    trend_points: List[CropTrendPoint] = []
    for key, data in sorted(period_crop_map.items(), key=lambda x: (x[1]["period"], x[1]["crop_name"])):
        trend_points.append(CropTrendPoint(
            period=data["period"],
            crop_name=data["crop_name"],
            volume_quintals=round(data["volume_quintals"], 2),
            booking_count=data["booking_count"],
            msp_rate=round(data["msp_rate"], 2),
            estimated_value=round(data["estimated_value"], 2),
        ))

    # Round summaries
    for c_name, s_data in summary_map.items():
        s_data["total_volume_quintals"] = round(s_data["total_volume_quintals"], 2)
        s_data["total_estimated_value"] = round(s_data["total_estimated_value"], 2)

    return CropTrendsResponse(
        timeframe=timeframe,
        crops_analyzed=sorted(list(crops_seen)),
        trends=trend_points,
        summary_by_crop=summary_map,
    )


@router.get('/procurement-signals', response_model=ProcurementSignalsResponse)
async def get_procurement_signals(
    centre_id: str = Query(..., description="Mandi centre ID"),
    date: Optional[str] = Query(None, description="Target date in YYYY-MM-DD format"),
    db: AsyncSession = Depends(get_db),
):
    """
    Strategic procurement signals comparing live booked supply against mandi targets.
    Guides procurement decisions with real-time supply/demand signals.
    """
    centre = (await db.execute(select(Centre).where(Centre.id == centre_id))).scalar_one_or_none()
    if not centre:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Centre not found")

    target_date = date or datetime.now().strftime("%Y-%m-%d")

    # Fetch all crops booked on this target date at this centre
    stmt = (
        select(BookingCrop, Booking, Slot)
        .join(Booking, Booking.id == BookingCrop.booking_id)
        .join(Slot, Slot.id == Booking.slot_id)
        .where(
            and_(
                Booking.centre_id == centre_id,
                Slot.slot_date == target_date,
                Booking.status != 'cancelled'
            )
        )
    )
    rows = (await db.execute(stmt)).all()

    booked_volumes: Dict[str, float] = {k: 0.0 for k in MANDI_DAILY_TARGETS}
    procured_volumes: Dict[str, float] = {k: 0.0 for k in MANDI_DAILY_TARGETS}

    for b_crop, booking, slot in rows:
        c_name = b_crop.crop_name
        if c_name not in booked_volumes:
            booked_volumes[c_name] = 0.0
            procured_volumes[c_name] = 0.0
        booked_volumes[c_name] += b_crop.estimated_weight_quintals
        if booking.status == 'completed':
            procured_volumes[c_name] += b_crop.estimated_weight_quintals

    signals: List[ProcurementSignalItem] = []
    total_target = 0.0
    total_booked = 0.0

    all_crops = sorted(list(set(list(MANDI_DAILY_TARGETS.keys()) + list(booked_volumes.keys()))))

    for c_name in all_crops:
        daily_target = MANDI_DAILY_TARGETS.get(c_name, 100.0)
        booked = booked_volumes.get(c_name, 0.0)
        procured = procured_volumes.get(c_name, 0.0)
        deficit_surplus = round(daily_target - booked, 2)
        fulfillment_pct = round((booked / daily_target * 100), 1) if daily_target > 0 else 0.0
        msp = DEFAULT_MSP_RATES.get(c_name, 2320.0)

        total_target += daily_target
        total_booked += booked

        if fulfillment_pct < 50.0:
            urgency = "HIGH_DEFICIT"
            recommendation = (
                f"Urgent supply deficit ({fulfillment_pct}% fulfilled). Prioritize incoming {c_name} farmer check-ins "
                f"and broadcast procurement alerts."
            )
        elif fulfillment_pct < 90.0:
            urgency = "ON_TRACK"
            recommendation = (
                f"Healthy arrival pace ({fulfillment_pct}%). Quota on track for daily MSP target of {daily_target:.0f} Q."
            )
        elif fulfillment_pct <= 110.0:
            urgency = "BALANCED"
            recommendation = (
                f"Optimal procurement equilibrium ({fulfillment_pct}%). Storage silos and weigh bridges at ideal throughput."
            )
        else:
            urgency = "SURPLUS_CEILING"
            recommendation = (
                f"Surplus ceiling exceeded ({fulfillment_pct}%). Pre-reserve secondary buffer sheds and coordinate bulk rail lifting."
            )

        signals.append(ProcurementSignalItem(
            crop_name=c_name,
            daily_target_quintals=daily_target,
            booked_supply_quintals=round(booked, 2),
            procured_quintals=round(procured, 2),
            deficit_or_surplus_quintals=deficit_surplus,
            fulfillment_pct=fulfillment_pct,
            urgency_signal=urgency,
            procurement_recommendation=recommendation,
            current_msp=msp,
        ))

    return ProcurementSignalsResponse(
        centre_id=centre.id,
        centre_name=centre.name,
        date=target_date,
        total_target_quintals=round(total_target, 2),
        total_booked_quintals=round(total_booked, 2),
        signals=signals,
    )