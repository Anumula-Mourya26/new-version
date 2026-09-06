import asyncio
import sys
import os
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import select
from app.core.db import AsyncSessionLocal, init_db, engine, Base
from app.models.entities import User, Centre, Slot, Booking, QueueState, Transaction
from app.services.queue_engine import QueueEngine


async def seed():
    print('Resetting and creating database schema...')
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        print('Seeding pre-existing Admin...')
        # Pre-existing Admin required by user: Mobile 123456890
        admin = User(
            id='user-admin-1',
            phone='123456890',
            role='admin',
            full_name='District Chief Mandi Administrator',
        )
        db.add(admin)

        print('Seeding Mandi Centres with geographic hierarchy...')
        # Mandi Centres
        c1 = Centre(
            id='centre-khanna',
            name='Khanna Grain Mandi (Central Hub)',
            state='Punjab',
            city='Ludhiana',
            address='G.T. Road, Near Grain Market Gate 1, Khanna',
            manager_name='Gurpreet Singh',
            manager_aadhaar='234567890123',
            manager_phone='9876500001',
            workers_count=3,        # C
            capacity_factor=1.0,    # F
            status='NORMAL',
        )

        c2 = Centre(
            id='centre-samrala',
            name='Samrala APMC Mandi',
            state='Punjab',
            city='Ludhiana',
            address='Mandi Complex, Samrala Bypass',
            manager_name='Harjit Brar',
            manager_aadhaar='345678901234',
            manager_phone='9876500002',
            workers_count=2,        # C
            capacity_factor=0.8,    # F (Busy)
            status='BUSY',
        )

        c3 = Centre(
            id='centre-karnal',
            name='Karnal Central Krishi Mandi',
            state='Haryana',
            city='Karnal',
            address='National Highway 44, New Grain Market',
            manager_name='Rajesh Kumar',
            manager_aadhaar='456789012345',
            manager_phone='9876500003',
            workers_count=4,        # C
            capacity_factor=1.0,    # F
            status='NORMAL',
        )

        c4 = Centre(
            id='centre-indore',
            name='Indore Krishi Upaj Mandi',
            state='Madhya Pradesh',
            city='Indore',
            address='Laxmi Bai Nagar Mandi, Indore',
            manager_name='Vikram Patel',
            manager_aadhaar='567890123456',
            manager_phone='9876500004',
            workers_count=3,        # C
            capacity_factor=1.0,    # F
            status='NORMAL',
        )

        db.add_all([c1, c2, c3, c4])
        await db.flush()

        # Seed Vendor Users for the Mandi Managers
        v1 = User(id='vendor-1', phone='9876500001', role='vendor', full_name='Gurpreet Singh (Mandi Manager)', centre_id=c1.id, aadhaar_number='234567890123')
        v2 = User(id='vendor-2', phone='9876500002', role='vendor', full_name='Harjit Brar (Mandi Manager)', centre_id=c2.id, aadhaar_number='345678901234')
        v3 = User(id='vendor-3', phone='9876500003', role='vendor', full_name='Rajesh Kumar (Mandi Manager)', centre_id=c3.id, aadhaar_number='456789012345')
        v4 = User(id='vendor-4', phone='9876500004', role='vendor', full_name='Vikram Patel (Mandi Manager)', centre_id=c4.id, aadhaar_number='567890123456')
        db.add_all([v1, v2, v3, v4])
        await db.flush()

        # Seed 120-minute slots (8 AM to 6 PM) for each centre
        today_str = datetime.now().strftime('%Y-%m-%d')
        windows = [
            '08:00 - 10:00',
            '10:00 - 12:00',
            '12:00 - 14:00',
            '14:00 - 16:00',
            '16:00 - 18:00',
        ]

        all_slots = []
        for centre in [c1, c2, c3, c4]:
            for win in windows:
                all_slots.append(
                    Slot(
                        centre_id=centre.id,
                        slot_date=today_str,
                        time_window=win,
                        capacity_units=30,  # Strict max 30 farmers per slot
                        booked_units=0,
                    )
                )
        db.add_all(all_slots)
        await db.flush()

        print('Seeding Farmer profile and sample bookings...')
        # Farmer
        farmer = User(
            id='farmer-demo-1',
            phone='9876543210',
            role='farmer',
            full_name='Harpreet Singh',
            aadhaar_number='123456789012',
            alt_person_name='Kuldeep Singh (Brother)',
            alt_person_aadhaar='987654321098',
        )
        db.add(farmer)
        await db.flush()

        # Active Booking #1 in Khanna Mandi (08:00 - 10:00)
        target_slot = all_slots[0]
        target_slot.booked_units += 1

        b1 = Booking(
            id='book-active-1',
            farmer_id=farmer.id,
            centre_id=c1.id,
            slot_id=target_slot.id,
            estimated_weight_quintals=50.0,
            unique_booking_code='AS-1047',
            qr_payload='ANNSETU:AS-1047:9876543210:50.0',
            status='in_queue',
            arrived_at=datetime.now(timezone.utc),
        )
        db.add(b1)
        await db.flush()

        # Queue Entry with KisanQueue formula ETA
        eta_1 = QueueEngine.calculate_kisanqueue_eta(n=1, c=c1.workers_count, f=c1.capacity_factor, status=c1.status)
        q1 = QueueState(
            id='queue-1',
            centre_id=c1.id,
            booking_id=b1.id,
            position=1,
            eta_minutes=eta_1,
            status='waiting',
        )
        db.add(q1)

        # Completed Historical Booking #2 with Payment & Proof
        target_slot_2 = all_slots[1]
        target_slot_2.booked_units += 1

        b2 = Booking(
            id='book-past-2',
            farmer_id=farmer.id,
            centre_id=c1.id,
            slot_id=target_slot_2.id,
            estimated_weight_quintals=45.0,
            unique_booking_code='AS-1012',
            qr_payload='ANNSETU:AS-1012:9876543210:45.0',
            status='completed',
            arrived_at=datetime.now(timezone.utc),
        )
        db.add(b2)
        await db.flush()

        tx2 = Transaction(
            id='tx-past-2',
            booking_id=b2.id,
            centre_id=c1.id,
            vendor_user_id=v1.id,
            farmer_id=farmer.id,
            actual_weight_quintals=46.5,
            amount_paid=46.5 * 2320.00,  # ₹107,880
            payment_method='dbt',
            proof_type='transaction_id',
            proof_data='SBIN004829104829',
            status='credited',
        )
        db.add(tx2)

        await db.commit()
        print('Seed complete! Created pre-existing Admin (123456890), 4 Mandis, 120-min slots (max 30 cap), Farmer, and Bookings.')


if __name__ == '__main__':
    asyncio.run(seed())
