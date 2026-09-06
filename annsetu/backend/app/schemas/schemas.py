from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


# ── Auth ────────────────────────────────────────────────────────
class OTPRequest(BaseModel):
    phone: str = Field(..., pattern=r'^\+?[0-9]{10,13}$')


class OTPVerify(BaseModel):
    phone: str
    otp: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = 'bearer'
    role: str
    user_id: str
    phone: str
    full_name: str


class OfficerLoginRequest(BaseModel):
    phone: str
    password: str


# ── Farmer ──────────────────────────────────────────────────────
class FarmerRegister(BaseModel):
    phone: str
    full_name: str
    aadhaar_ref: str
    bank_account_ref: str
    land_record_ref: Optional[str] = None
    is_sharecropper: bool = False
    consent_letter_doc_ref: Optional[str] = None
    village: str
    district_id: str
    preferred_language: str = 'hi'


class FarmerResponse(BaseModel):
    id: str
    phone: str
    full_name: str
    village: str
    district_id: str
    is_sharecropper: bool
    bank_account_ref: str

    model_config = ConfigDict(from_attributes=True)


# ── Centre & Slots ──────────────────────────────────────────────
class CentreResponse(BaseModel):
    id: str
    name: str
    district_id: str
    latitude: float
    longitude: float
    daily_capacity_units: int
    weighing_points: int
    operating_hours: str
    status: str
    live_waiting_count: int = 0
    load_status: str = 'green'  # green, amber, red
    current_eta_minutes: int = 0

    model_config = ConfigDict(from_attributes=True)


class SlotResponse(BaseModel):
    id: str
    centre_id: str
    slot_date: str
    time_window: str
    capacity_units: int
    booked_units: int
    remaining_units: int

    model_config = ConfigDict(from_attributes=True)


class BookingCreate(BaseModel):
    farmer_id: str
    slot_id: str
    declared_quantity_quintals: float = Field(..., gt=0)


class BookingResponse(BaseModel):
    booking_id: str
    unique_booking_code: str
    status: str
    slot_date: str
    time_window: str
    centre_name: str

    model_config = ConfigDict(from_attributes=True)


# ── Gate & Queue ────────────────────────────────────────────────
class GateCheckInRequest(BaseModel):
    booking_code: Optional[str] = None
    qr_payload: Optional[str] = None


class CheckInResponse(BaseModel):
    token_id: str
    token_number: int
    position: int
    eta_minutes: int
    centre_id: str
    issued_at: datetime


class QueueItem(BaseModel):
    token_number: int
    unique_booking_code: str
    farmer_name: str
    position: int
    eta_minutes: int
    status: str


class QueueStatusResponse(BaseModel):
    centre_id: str
    centre_name: str
    total_waiting: int
    active_counters: int
    estimated_wait_time_minutes: int
    queue: List[QueueItem]


# ── Procurement & Quality ───────────────────────────────────────
class ProcurementCreate(BaseModel):
    token_id: str
    moisture_pct: float
    quality_result: str = 'accepted'  # accepted / rejected
    weighed_quantity_quintals: Optional[float] = None
    rejection_reason: Optional[str] = None


class ProcurementResponse(BaseModel):
    procurement_id: str
    receipt_ref: Optional[str]
    quality_result: str
    weighed_quantity_quintals: Optional[float]
    amount_due: Optional[float]


# ── Payments (AnnSetu Staged Trust Timeline) ────────────────────
class PaymentStageUpdate(BaseModel):
    stage: str  # sold -> advice_generated -> advice_reached_agent -> credited
    utr_ref: Optional[str] = None


class PaymentTimelineItem(BaseModel):
    stage: str
    timestamp: datetime
    is_completed: bool
    description: str


class FarmerStatusTimelineResponse(BaseModel):
    booking_code: str
    status: str
    slot_time: str
    arrival_time: Optional[datetime]
    weighed_quantity: Optional[float]
    msp_amount: Optional[float]
    payment_stage: str
    utr_ref: Optional[str]
    timeline: List[PaymentTimelineItem]


# ── District Congestion & Redirect ──────────────────────────────
class RedirectSuggestionRequest(BaseModel):
    from_centre_id: str
    to_centre_id: str
    farmer_count: int = Field(..., gt=0)


class RedirectSuggestionResponse(BaseModel):
    status: str
    message: str
    redirected_count: int
    source_centre: str
    target_centre: str
