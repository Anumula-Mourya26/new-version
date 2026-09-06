import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, timedelta, timezone
from app.core.db import AsyncSessionLocal, init_db
from app.models.entities import (
    User, Farmer, Centre, Commodity, Slot, Booking, Token, QueueState, Procurement, Payment
)
from app.core.security import hash_password


async def seed():
    print('Initializing database tables...')
    await init_db()

    async with AsyncSessionLocal() as db:
        print('Seeding AnnSetu demo data...')

        # 1. District & Mandi Centres
        district_id = 'dist-punjab-ludhiana'

        c1 = Centre(
            id='centre-khanna',
            name='Khanna Grain Mandi (Central Hub)',
            district_id=district_id,
            latitude=30.7073,
            longitude=76.2195,
            daily_capacity_units=120,
            weighing_points=3,  # 3 active weighbridges
            operating_hours='08:00 - 18:00',
            status='active',
        )

        c2 = Centre(
            id='centre-samrala',
            name='Samrala APMC Mandi',
            district_id=district_id,
            latitude=30.8358,
            longitude=76.1917,
            daily_capacity_units=80,
            weighing_points=2,
            operating_hours='08:00 - 18:00',
            status='active',
        )

        c3 = Centre(
            id='centre-sahnewal',
            name='Sahnewal Procurement Centre',
            district_id=district_id,
            latitude=30.8444,
            longitude=75.9867,
            daily_capacity_units=60,
            weighing_points=1,
            operating_hours='08:00 - 18:00',
            status='active',
        )

        db.add_all([c1, c2, c3])
        await db.flush()

        # 2. Commodity: Paddy (Dhan)
        paddy = Commodity(
            id='comm-paddy-2026',
            name='Paddy (Grade A)',
            season='kharif',
            msp_per_quintal=2320.00,
            moisture_threshold_pct=17.0,
            procurement_window_start='2026-10-01',
            procurement_window_end='2026-12-15',
        )
        db.add(paddy)
        await db.flush()

        # 3. Slots for each centre
        today_str = datetime.now().strftime('%Y-%m-%d')
        slots = [
            Slot(centre_id=c1.id, slot_date=today_str, time_window='09:00 - 11:00', capacity_units=25, booked_units=4),
            Slot(centre_id=c1.id, slot_date=today_str, time_window='11:00 - 13:00', capacity_units=25, booked_units=2),
            Slot(centre_id=c2.id, slot_date=today_str, time_window='09:00 - 11:00', capacity_units=20, booked_units=1),
            Slot(centre_id=c2.id, slot_date=today_str, time_window='11:00 - 13:00', capacity_units=20, booked_units=0),
            Slot(centre_id=c3.id, slot_date=today_str, time_window='09:00 - 11:00', capacity_units=15, booked_units=0),
        ]
        db.add_all(slots)
        await db.flush()

        # 4. Officer User
        officer = User(
            id='user-officer-1',
            phone='+919876500001',
            role='operator',
            full_name='Gurpreet Singh (Mandi Inspector)',
            centre_id=c1.id,
            password_hash=hash_password('Demo@1234'),
        )
        db.add(officer)

        # 5. Sample Farmers
        f1_user = User(
            id='user-farmer-1',
            phone='+919876543210',
            role='farmer',
            full_name='Harpreet Singh',
            district_id=district_id,
        )
        db.add(f1_user)
        await db.flush()

        farmer1 = Farmer(
            id=f1_user.id,
            aadhaar_ref='AADHAAR-TOKEN-908123',
            bank_account_ref='PUNB0123456789',
            village='Rattanheri',
            district_id=district_id,
            is_sharecropper=False,
        )
        db.add(farmer1)

        # Booking & Token in Live Queue
        b1 = Booking(
            id='book-101',
            farmer_id=farmer1.id,
            slot_id=slots[0].id,
            declared_quantity_quintals=45.0,
            status='checked_in',
            unique_booking_code='AS-1047',
        )
        db.add(b1)
        await db.flush()

        tok1 = Token(
            id='tok-201',
            booking_id=b1.id,
            centre_id=c1.id,
            token_number=1,
            qr_payload='TOKEN:centre-khanna:1:AS-1047',
        )
        db.add(tok1)
        await db.flush()

        q1 = QueueState(
            centre_id=c1.id,
            token_id=tok1.id,
            position=1,
            eta_minutes=0,
            status='waiting',
        )
        db.add(q1)

        # Farmer 2 with Completed Staged Payment
        f2_user = User(
            id='user-farmer-2',
            phone='+919876543211',
            role='farmer',
            full_name='Jaswant Kaur',
            district_id=district_id,
        )
        db.add(f2_user)
        await db.flush()

        farmer2 = Farmer(
            id=f2_user.id,
            aadhaar_ref='AADHAAR-TOKEN-908124',
            bank_account_ref='SBIN0987654321',
            village='Alour',
            district_id=district_id,
            is_sharecropper=False,
        )
        db.add(farmer2)

        b2 = Booking(
            id='book-102',
            farmer_id=farmer2.id,
            slot_id=slots[0].id,
            declared_quantity_quintals=60.0,
            status='completed',
            unique_booking_code='AS-1048',
        )
        db.add(b2)
        await db.flush()

        tok2 = Token(
            id='tok-202',
            booking_id=b2.id,
            centre_id=c1.id,
            token_number=2,
            qr_payload='TOKEN:centre-khanna:2:AS-1048',
        )
        db.add(tok2)
        await db.flush()

        proc2 = Procurement(
            id='proc-302',
            token_id=tok2.id,
            moisture_pct=14.2,
            quality_result='accepted',
            weighed_quantity_quintals=58.5,
            inspector_user_id=officer.id,
            receipt_ref='REC-AS-982145',
        )
        db.add(proc2)
        await db.flush()

        pay2 = Payment(
            id='pay-402',
            procurement_id=proc2.id,
            amount_due=58.5 * 2320.00,  # 135,720 INR
            payee_type='farmer_direct',
            stage='advice_reached_agent',  # Stage 3 of 4
            utr_ref='UTIB98213401',
        )
        db.add(pay2)

        await db.commit()
        print('Seed complete! Added 3 Mandi centres, Paddy MSP, slots, farmers, and sample queue entries.')


if __name__ == '__main__':
    asyncio.run(seed())
