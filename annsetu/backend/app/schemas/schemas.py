from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict


# ── Auth ────────────────────────────────────────────────────────
class FarmerSignupRequest(BaseModel):
    phone: str
    full_name: str
    aadhaar_number: str
    alt_person_name: Optional[str] = None
    alt_person_aadhaar: Optional[str] = None


class LoginRequest(BaseModel):
    phone: Optional[str] = None
    admin_id: Optional[str] = None
    role: str = 'farmer'  # farmer, vendor, or admin
    password: Optional[str] = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = 'bearer'
    role: str
    user_id: str
    phone: str
    full_name: str
    centre_id: Optional[str] = None


# ── Centre & Slots ──────────────────────────────────────────────
class CentreResponse(BaseModel):
    id: str
    name: str
    state: str
    city: str
    address: str
    manager_name: str
    manager_phone: str
    workers_count: int
    capacity_factor: float
    status: str
    live_waiting_count: int = 0
    current_eta_minutes: Optional[int] = None

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


# ── Farmer Bookings ─────────────────────────────────────────────
class CropItem(BaseModel):
    crop_name: str
    estimated_weight_quintals: float = Field(..., gt=0)
    msp_rate: Optional[float] = 2320.0


class BookingCreateRequest(BaseModel):
    farmer_id: str
    centre_id: str
    slot_id: str
    estimated_weight_quintals: Optional[float] = Field(None, gt=0)
    crops: Optional[List[CropItem]] = None
    primary_crop: Optional[str] = 'Wheat'


class TransactionBrief(BaseModel):
    id: str
    actual_weight_quintals: float
    amount_paid: float
    payment_method: str
    proof_type: str
    proof_data: str
    proof_image: Optional[str] = None
    crops_data: Optional[List[Dict[str, Any]]] = None
    status: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BookingDetailResponse(BaseModel):
    id: str
    unique_booking_code: str
    qr_payload: str
    centre_name: str
    state: str
    city: str
    slot_date: str
    time_window: str
    estimated_weight_quintals: float
    primary_crop: Optional[str] = 'Wheat'
    crops_data: Optional[List[Dict[str, Any]]] = None
    sms_status: Optional[str] = 'pending'
    sms_error: Optional[str] = None
    status: str
    arrived_at: Optional[datetime] = None
    booked_at: datetime
    queue_position: Optional[int] = None
    eta_minutes: Optional[int] = None
    workers_count: Optional[int] = None
    capacity_factor: Optional[float] = None
    transaction: Optional[TransactionBrief] = None

    model_config = ConfigDict(from_attributes=True)


class ArrivalConfirmRequest(BaseModel):
    booking_code: str


# ── Vendor Operational Schemas ──────────────────────────────────
class VendorSettingsUpdateRequest(BaseModel):
    workers_count: int = Field(..., ge=1)
    capacity_factor: float = Field(..., ge=0.0, le=1.0)
    status: str = 'NORMAL'  # NORMAL, BUSY, LIFTING_DELAYED, PAUSED


class VendorCheckinRequest(BaseModel):
    booking_code: str


class VendorPaymentSubmitRequest(BaseModel):
    booking_id: str
    actual_weight_quintals: float = Field(..., gt=0)
    amount_paid: float = Field(..., gt=0)
    crops: Optional[List[Dict[str, Any]]] = None
    payment_method: str = 'dbt'  # dbt, cash
    proof_type: str = 'transaction_id'  # transaction_id, photo_proof
    proof_data: str  # Transaction UTR or receipt reference / image url
    proof_image: Optional[str] = None  # Base64 data URL / screenshot


class FarmerInSlot(BaseModel):
    booking_id: str
    booking_code: str
    unique_booking_code: str
    farmer_name: str
    farmer_phone: str
    estimated_weight: float
    estimated_weight_quintals: float
    primary_crop: Optional[str] = 'Wheat'
    crops_data: Optional[List[Dict[str, Any]]] = None
    status: str
    arrived_at: Optional[datetime] = None


class SlotRosterResponse(BaseModel):
    slot_id: str
    time_window: str
    capacity_units: int
    booked_units: int
    booked_count: int
    farmers: List[FarmerInSlot]
    bookings: List[FarmerInSlot]


class VendorQueueItem(BaseModel):
    booking_id: str
    unique_booking_code: str
    farmer_name: str
    farmer_phone: str
    estimated_weight_quintals: float
    primary_crop: Optional[str] = 'Wheat'
    crops_data: Optional[List[Dict[str, Any]]] = None
    position: int
    eta_minutes: Optional[int] = None
    status: str
    arrived_at: Optional[datetime] = None



# ── Admin Management ────────────────────────────────────────────
class VendorCreateRequest(BaseModel):
    mandi_name: str
    state: str
    city: str
    address: str
    manager_name: str
    manager_aadhaar: str
    manager_phone: str
    workers_count: int = 3


class BookingEditRequest(BaseModel):
    slot_id: Optional[str] = None
    estimated_weight_quintals: Optional[float] = None
    status: Optional[str] = None


class UserManagementItem(BaseModel):
    id: str
    phone: str
    role: str
    full_name: str
    aadhaar_number: Optional[str] = None
    alt_person_name: Optional[str] = None
    active_bookings: int = 0
    total_bookings: int = 0
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ── Live Queue Schemas ──────────────────────────────────────────
class QueueItem(BaseModel):
    booking_id: str
    unique_booking_code: str
    farmer_name: str
    position: int
    eta_minutes: Optional[int] = None
    status: str


class QueueStatusResponse(BaseModel):
    centre_id: str
    centre_name: str
    total_waiting: int
    workers_count: int
    capacity_factor: float
    status: str
    estimated_wait_time_minutes: Optional[int] = None
    queue: List[QueueItem]


# ── Historical Schedule & Analytics Schemas ─────────────────────
class HistoricalSlotRecord(BaseModel):
    slot_id: str
    slot_date: str
    time_window: str
    capacity_units: int
    booked_units: int
    remaining_units: int
    booked_count: int
    completed_count: int
    total_quintals: float
    total_amount_paid: float
    bookings: List[FarmerInSlot]

    model_config = ConfigDict(from_attributes=True)


class DayScheduleSummary(BaseModel):
    date: str
    centre_id: str
    centre_name: str
    total_slots: int
    total_capacity_units: int
    total_booked_units: int
    occupancy_rate_pct: float
    total_farmers_admitted: int
    total_volume_quintals: float
    total_payout_amount: float
    slots: List[HistoricalSlotRecord]


class CropTrendPoint(BaseModel):
    period: str
    crop_name: str
    volume_quintals: float
    booking_count: int
    msp_rate: float
    estimated_value: float


class CropTrendsResponse(BaseModel):
    timeframe: str
    crops_analyzed: List[str]
    trends: List[CropTrendPoint]
    summary_by_crop: Dict[str, Dict[str, Any]]


class ProcurementSignalItem(BaseModel):
    crop_name: str
    daily_target_quintals: float
    booked_supply_quintals: float
    procured_quintals: float
    deficit_or_surplus_quintals: float
    fulfillment_pct: float
    urgency_signal: str
    procurement_recommendation: str
    current_msp: float


class ProcurementSignalsResponse(BaseModel):
    centre_id: str
    centre_name: str
    date: str
    total_target_quintals: float
    total_booked_quintals: float
    signals: List[ProcurementSignalItem]


