import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Integer, Float, Boolean, DateTime, ForeignKey, Text, JSON, Index
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
    role = Column(String(20), nullable=False, default='farmer')  # farmer, vendor, admin
    full_name = Column(String(120), nullable=False)
    aadhaar_number = Column(String(20), nullable=True)
    alt_person_name = Column(String(120), nullable=True)
    alt_person_aadhaar = Column(String(20), nullable=True)
    password_hash = Column(String(128), nullable=True)
    centre_id = Column(String(36), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=now_utc)

    bookings = relationship('Booking', back_populates='farmer', cascade='all, delete-orphan')


class Centre(Base):
    __tablename__ = 'centres'

    id = Column(String(36), primary_key=True, default=gen_uuid)
    name = Column(String(150), nullable=False)
    state = Column(String(60), nullable=False, default='Punjab')
    city = Column(String(60), nullable=False, default='Ludhiana')
    address = Column(String(255), nullable=False)
    manager_name = Column(String(120), nullable=False)
    manager_aadhaar = Column(String(20), nullable=False)
    manager_phone = Column(String(20), nullable=False)
    workers_count = Column(Integer, nullable=False, default=3)      # C in ETA formula
    capacity_factor = Column(Float, nullable=False, default=1.0)    # F in ETA formula (1.0, 0.8, 0.6, 0.0)
    status = Column(String(30), default='NORMAL')                   # NORMAL, BUSY, LIFTING_DELAYED, PAUSED
    daily_capacity_units = Column(Integer, default=150)
    operating_hours = Column(String(60), default='08:00 - 18:00')

    slots = relationship('Slot', back_populates='centre', cascade='all, delete-orphan')
    bookings = relationship('Booking', back_populates='centre')


class Slot(Base):
    __tablename__ = 'slots'
    __table_args__ = (
        Index('idx_slot_centre_date', 'centre_id', 'slot_date'),
        Index('idx_slot_date_window', 'slot_date', 'time_window'),
    )

    id = Column(String(36), primary_key=True, default=gen_uuid)
    centre_id = Column(String(36), ForeignKey('centres.id', ondelete='CASCADE'), nullable=False)
    slot_date = Column(String(10), nullable=False, index=True)      # YYYY-MM-DD
    time_window = Column(String(30), nullable=False)                # 08:00 - 10:00, 10:00 - 12:00, etc.
    capacity_units = Column(Integer, nullable=False, default=30)    # Max 30 farmers per slot
    booked_units = Column(Integer, default=0)

    centre = relationship('Centre', back_populates='slots')
    bookings = relationship('Booking', back_populates='slot')


class BookingCrop(Base):
    __tablename__ = 'booking_crops'
    __table_args__ = (
        Index('idx_booking_crop_name', 'crop_name'),
    )

    id = Column(String(36), primary_key=True, default=gen_uuid)
    booking_id = Column(String(36), ForeignKey('bookings.id', ondelete='CASCADE'), nullable=False)
    crop_name = Column(String(60), nullable=False)
    estimated_weight_quintals = Column(Float, nullable=False)
    msp_rate = Column(Float, nullable=False, default=2320.0)

    booking = relationship('Booking', back_populates='crop_items')


class Booking(Base):
    __tablename__ = 'bookings'
    __table_args__ = (
        Index('idx_booking_slot_status', 'slot_id', 'status'),
        Index('idx_booking_farmer_booked', 'farmer_id', 'booked_at'),
    )

    id = Column(String(36), primary_key=True, default=gen_uuid)
    farmer_id = Column(String(36), ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    centre_id = Column(String(36), ForeignKey('centres.id', ondelete='CASCADE'), nullable=False)
    slot_id = Column(String(36), ForeignKey('slots.id', ondelete='CASCADE'), nullable=False)
    estimated_weight_quintals = Column(Float, nullable=False)
    primary_crop = Column(String(60), default='Wheat')
    crops_data = Column(JSON, nullable=True)                        # Multi-crop list details
    unique_booking_code = Column(String(16), unique=True, nullable=False, index=True)
    qr_payload = Column(String(256), nullable=False)
    status = Column(String(20), default='booked')                   # booked, arrived, in_queue, completed, cancelled
    sms_status = Column(String(20), default='pending')              # pending, sent, mock_sent, failed
    sms_error = Column(Text, nullable=True)
    arrived_at = Column(DateTime, nullable=True)
    booked_at = Column(DateTime, default=now_utc)

    farmer = relationship('User', back_populates='bookings')
    centre = relationship('Centre', back_populates='bookings')
    slot = relationship('Slot', back_populates='bookings')
    crop_items = relationship('BookingCrop', back_populates='booking', cascade='all, delete-orphan')
    queue_state = relationship('QueueState', back_populates='booking', uselist=False, cascade='all, delete-orphan')
    transaction = relationship('Transaction', back_populates='booking', uselist=False, cascade='all, delete-orphan')


class QueueState(Base):
    __tablename__ = 'queue_state'

    id = Column(String(36), primary_key=True, default=gen_uuid)
    centre_id = Column(String(36), nullable=False, index=True)
    booking_id = Column(String(36), ForeignKey('bookings.id', ondelete='CASCADE'), unique=True, nullable=False)
    position = Column(Integer, nullable=False)
    eta_minutes = Column(Integer, nullable=True)                    # Nullable if PAUSED
    status = Column(String(20), default='waiting')                  # waiting, in_service, served, cancelled
    computed_at = Column(DateTime, default=now_utc)

    booking = relationship('Booking', back_populates='queue_state')


class Transaction(Base):
    __tablename__ = 'transactions'

    id = Column(String(36), primary_key=True, default=gen_uuid)
    booking_id = Column(String(36), ForeignKey('bookings.id', ondelete='CASCADE'), unique=True, nullable=False)
    centre_id = Column(String(36), ForeignKey('centres.id', ondelete='CASCADE'), nullable=False)
    vendor_user_id = Column(String(36), ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    farmer_id = Column(String(36), ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    actual_weight_quintals = Column(Float, nullable=False)
    amount_paid = Column(Float, nullable=False)
    crops_data = Column(JSON, nullable=True)                        # Itemized actual crop breakdown
    payment_method = Column(String(20), default='dbt')              # dbt, cash
    proof_type = Column(String(30), default='transaction_id')       # transaction_id, photo_proof
    proof_data = Column(Text, nullable=False)                       # UTR / Ref No.
    proof_image = Column(Text, nullable=True)                       # Base64 data URL or image path
    status = Column(String(20), default='credited')                 # paid, credited
    created_at = Column(DateTime, default=now_utc)

    booking = relationship('Booking', back_populates='transaction')
    farmer = relationship('User', foreign_keys=[farmer_id])
    vendor = relationship('User', foreign_keys=[vendor_user_id])
    centre = relationship('Centre', foreign_keys=[centre_id])

