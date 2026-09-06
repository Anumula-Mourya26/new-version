import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime, ForeignKey, Text, JSON
)
from sqlalchemy.orm import relationship

from app.core.db import Base


def gen_uuid() -> str:
    return str(uuid.uuid4())


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = 'users'

    id = Column(String(36), primary_key=True, default=gen_uuid)
    phone = Column(String(15), unique=True, nullable=False, index=True)
    role = Column(String(30), nullable=False, default='farmer')  # farmer, operator, district_admin, system_admin
    full_name = Column(String(120), nullable=False)
    preferred_language = Column(String(10), default='hi')
    centre_id = Column(String(36), nullable=True)
    district_id = Column(String(36), nullable=True)
    password_hash = Column(String(128), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=now_utc)

    farmer_profile = relationship('Farmer', back_populates='user', uselist=False)


class Farmer(Base):
    __tablename__ = 'farmers'

    id = Column(String(36), ForeignKey('users.id'), primary_key=True)
    aadhaar_ref = Column(String(64), unique=True, nullable=False, index=True)
    land_record_ref = Column(String(64), nullable=True)
    bank_account_ref = Column(String(64), nullable=False)
    is_sharecropper = Column(Boolean, default=False)
    consent_letter_doc_ref = Column(String(128), nullable=True)
    arhatiya_id = Column(String(36), nullable=True)
    village = Column(String(120), nullable=False)
    district_id = Column(String(36), nullable=False, index=True)

    user = relationship('User', back_populates='farmer_profile')
    bookings = relationship('Booking', back_populates='farmer')


class Centre(Base):
    __tablename__ = 'centres'

    id = Column(String(36), primary_key=True, default=gen_uuid)
    name = Column(String(150), nullable=False)
    district_id = Column(String(36), nullable=False, index=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    daily_capacity_units = Column(Integer, nullable=False, default=100)
    weighing_points = Column(Integer, nullable=False, default=2)  # Active counters (c)
    operating_hours = Column(String(100), default='08:00 - 18:00')
    status = Column(String(20), default='active')  # active, paused, closed

    slots = relationship('Slot', back_populates='centre')


class Commodity(Base):
    __tablename__ = 'commodities'

    id = Column(String(36), primary_key=True, default=gen_uuid)
    name = Column(String(60), unique=True, nullable=False)  # Paddy, Wheat, etc.
    season = Column(String(20), nullable=False, default='kharif')
    msp_per_quintal = Column(Float, nullable=False, default=2320.00)
    moisture_threshold_pct = Column(Float, nullable=False, default=17.0)
    procurement_window_start = Column(String(20), nullable=True)
    procurement_window_end = Column(String(20), nullable=True)


class Slot(Base):
    __tablename__ = 'slots'

    id = Column(String(36), primary_key=True, default=gen_uuid)
    centre_id = Column(String(36), ForeignKey('centres.id'), nullable=False)
    slot_date = Column(String(10), nullable=False, index=True)  # YYYY-MM-DD
    time_window = Column(String(30), nullable=False)  # e.g., "09:00 - 11:00"
    capacity_units = Column(Integer, nullable=False, default=20)
    booked_units = Column(Integer, default=0)
    commodity_id = Column(String(36), nullable=True)

    centre = relationship('Centre', back_populates='slots')
    bookings = relationship('Booking', back_populates='slot')


class Booking(Base):
    __tablename__ = 'bookings'

    id = Column(String(36), primary_key=True, default=gen_uuid)
    farmer_id = Column(String(36), ForeignKey('farmers.id'), nullable=False)
    slot_id = Column(String(36), ForeignKey('slots.id'), nullable=False)
    declared_quantity_quintals = Column(Float, nullable=False)
    status = Column(String(20), default='booked')  # booked, checked_in, completed, no_show, cancelled
    booked_at = Column(DateTime, default=now_utc)
    unique_booking_code = Column(String(16), unique=True, nullable=False, index=True)

    farmer = relationship('Farmer', back_populates='bookings')
    slot = relationship('Slot', back_populates='bookings')
    token = relationship('Token', back_populates='booking', uselist=False)


class Token(Base):
    __tablename__ = 'tokens'

    id = Column(String(36), primary_key=True, default=gen_uuid)
    booking_id = Column(String(36), ForeignKey('bookings.id'), unique=True, nullable=False)
    centre_id = Column(String(36), nullable=False, index=True)
    token_number = Column(Integer, nullable=False)
    qr_payload = Column(String(256), unique=True, nullable=False)
    issued_at = Column(DateTime, default=now_utc)

    booking = relationship('Booking', back_populates='token')
    queue_state = relationship('QueueState', back_populates='token', uselist=False)
    procurement = relationship('Procurement', back_populates='token', uselist=False)


class QueueState(Base):
    __tablename__ = 'queue_state'

    id = Column(String(36), primary_key=True, default=gen_uuid)
    centre_id = Column(String(36), nullable=False, index=True)
    token_id = Column(String(36), ForeignKey('tokens.id'), nullable=False)
    position = Column(Integer, nullable=False)
    eta_minutes = Column(Integer, nullable=False)
    status = Column(String(20), default='waiting')  # waiting, in_service, served, no_show
    computed_at = Column(DateTime, default=now_utc)

    token = relationship('Token', back_populates='queue_state')


class Procurement(Base):
    __tablename__ = 'procurement'

    id = Column(String(36), primary_key=True, default=gen_uuid)
    token_id = Column(String(36), ForeignKey('tokens.id'), unique=True, nullable=False)
    moisture_pct = Column(Float, nullable=False)
    quality_result = Column(String(20), nullable=False)  # accepted, rejected
    weighed_quantity_quintals = Column(Float, nullable=True)
    inspector_user_id = Column(String(36), nullable=True)
    receipt_ref = Column(String(64), unique=True, nullable=True)
    recorded_at = Column(DateTime, default=now_utc)

    token = relationship('Token', back_populates='procurement')
    payment = relationship('Payment', back_populates='procurement', uselist=False)


class Payment(Base):
    __tablename__ = 'payments'

    id = Column(String(36), primary_key=True, default=gen_uuid)
    procurement_id = Column(String(36), ForeignKey('procurement.id'), unique=True, nullable=False)
    amount_due = Column(Float, nullable=False)
    payee_type = Column(String(20), nullable=False, default='farmer_direct')  # farmer_direct, arhatiya
    stage = Column(String(30), default='sold')  # sold, advice_generated, advice_reached_agent, credited
    utr_ref = Column(String(64), nullable=True)
    stage_updated_at = Column(DateTime, default=now_utc)

    procurement = relationship('Procurement', back_populates='payment')


class Notification(Base):
    __tablename__ = 'notifications'

    id = Column(String(36), primary_key=True, default=gen_uuid)
    user_id = Column(String(36), nullable=False, index=True)
    channel = Column(String(20), nullable=False)  # sms, push, whatsapp
    event_type = Column(String(40), nullable=False)  # slot_confirmed, turn_approaching, payment_updated
    payload_text = Column(Text, nullable=False)
    status = Column(String(20), default='queued')  # queued, sent, delivered, failed
    created_at = Column(DateTime, default=now_utc)


class AuditLog(Base):
    __tablename__ = 'audit_logs'

    id = Column(Integer, primary_key=True, autoincrement=True)
    actor_user_id = Column(String(36), nullable=True)
    entity_type = Column(String(40), nullable=False)
    entity_id = Column(String(36), nullable=False)
    action = Column(String(60), nullable=False)
    before_state = Column(JSON, nullable=True)
    after_state = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=now_utc)
