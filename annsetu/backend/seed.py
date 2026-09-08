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
    print('Ensuring persistent database schema exists...')
    async with engine.begin() as conn:
        # Non-destructive: NEVER drop existing tables or data
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        # 1. Pre-existing Admin check
        admin = (await db.execute(select(User).where(User.phone == '123456890'))).scalar_one_or_none()
        if not admin:
            print('Seeding pre-existing Admin...')
            admin = User(
                id='user-admin-1',
                phone='123456890',
                role='admin',
                full_name='District Chief Mandi Administrator',
            )
            db.add(admin)
            await db.flush()
        else:
            print('Pre-existing Admin already exists.')

        # 2. Mandi Centres check
        c1 = (await db.execute(select(Centre).where(Centre.id == 'centre-khanna'))).scalar_one_or_none()
        if not c1:
            print('Seeding Mandi Centres with geographic hierarchy...')
            c1 = Centre(
                id='centre-khanna',
                name='Khanna Grain Mandi (Central Hub)',
                state='Punjab',
                city='Ludhiana',
                address='G.T. Road, Near Grain Market Gate 1, Khanna',
                manager_name='Gurpreet Singh',
                manager_aadhaar='234567890123',
                manager_phone='9876500001',
                workers_count=3,
                capacity_factor=1.0,
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
                workers_count=2,
                capacity_factor=0.8,
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
                workers_count=4,
                capacity_factor=1.0,
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
                workers_count=3,
                capacity_factor=1.0,
                status='NORMAL',
            )
            db.add_all([c1, c2, c3, c4])
            await db.flush()

            # Mandi Vendor accounts
            v1 = User(id='vendor-1', phone='9876500001', role='vendor', full_name='Gurpreet Singh (Mandi Manager)', centre_id=c1.id, aadhaar_number='234567890123')
            v2 = User(id='vendor-2', phone='9876500002', role='vendor', full_name='Harjit Brar (Mandi Manager)', centre_id=c2.id, aadhaar_number='345678901234')
            v3 = User(id='vendor-3', phone='9876500003', role='vendor', full_name='Rajesh Kumar (Mandi Manager)', centre_id=c3.id, aadhaar_number='456789012345')
            v4 = User(id='vendor-4', phone='9876500004', role='vendor', full_name='Vikram Patel (Mandi Manager)', centre_id=c4.id, aadhaar_number='567890123456')
            db.add_all([v1, v2, v3, v4])
            await db.flush()

        # 3. Daily 120-minute slots check for today
        today_str = datetime.now().strftime('%Y-%m-%d')
        existing_slots = (await db.execute(select(Slot).where(Slot.slot_date == today_str))).scalars().all()
        if not existing_slots:
            print(f'Seeding 120-minute slots for {today_str}...')
            centres = (await db.execute(select(Centre))).scalars().all()
            windows = [
                '08:00 - 10:00',
                '10:00 - 12:00',
                '12:00 - 14:00',
                '14:00 - 16:00',
                '16:00 - 18:00',
            ]
            for centre in centres:
                for win in windows:
                    db.add(Slot(
                        centre_id=centre.id,
                        slot_date=today_str,
                        time_window=win,
                        capacity_units=30,
                        booked_units=0,
                    ))
            await db.flush()

        await db.commit()
        print('Database seed verified! All data preserved.')


if __name__ == '__main__':
    asyncio.run(seed())
