import asyncio
import sys
import os
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import select, and_, or_
from app.core.db import AsyncSessionLocal, init_db, engine, Base
from app.models.entities import User, Centre, Slot, Booking, BookingCrop, QueueState, Transaction
from app.services.queue_engine import QueueEngine


async def seed(force_reset: bool = False):
    should_reset = force_reset or ('--reset' in sys.argv) or (os.getenv('FORCE_RESET') == '1')
    if should_reset:
        print('Resetting database schema (destructive)...')
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
    else:
        print('Ensuring persistent database schema exists (non-destructive)...')
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        # 1. Admin check (preserve existing)
        admin = (await db.execute(select(User).where(or_(User.phone == '123456890', User.phone == '123457890', User.role == 'admin')))).scalars().first()
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
            print('Admin already exists; preserved.')

        # 2. Mandi Centres check (preserve existing)
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
        else:
            c2 = (await db.execute(select(Centre).where(Centre.id == 'centre-samrala'))).scalar_one_or_none()
            c3 = (await db.execute(select(Centre).where(Centre.id == 'centre-karnal'))).scalar_one_or_none()
            c4 = (await db.execute(select(Centre).where(Centre.id == 'centre-indore'))).scalar_one_or_none()

        # Seed Vendor Users for the Mandi Managers if not present
        vendor_configs = [
            ('vendor-1', '9876500001', 'Gurpreet Singh (Mandi Manager)', c1.id if c1 else None, '234567890123'),
            ('vendor-2', '9876500002', 'Harjit Brar (Mandi Manager)', c2.id if c2 else None, '345678901234'),
            ('vendor-3', '9876500003', 'Rajesh Kumar (Mandi Manager)', c3.id if c3 else None, '456789012345'),
            ('vendor-4', '9876500004', 'Vikram Patel (Mandi Manager)', c4.id if c4 else None, '567890123456'),
        ]
        v1 = None
        for vid, vphone, vname, vcid, vaadhaar in vendor_configs:
            v_user = (await db.execute(select(User).where(User.phone == vphone))).scalar_one_or_none()
            if not v_user:
                v_user = User(id=vid, phone=vphone, role='vendor', full_name=vname, centre_id=vcid, aadhaar_number=vaadhaar)
                db.add(v_user)
            if vid == 'vendor-1':
                v1 = v_user
        await db.flush()

        # Seed 120-minute slots (8 AM to 6 PM) for multiple dates
        from datetime import timedelta
        base_dt = datetime.now()
        dates_to_seed = [
            (base_dt - timedelta(days=14)).strftime('%Y-%m-%d'),
            (base_dt - timedelta(days=7)).strftime('%Y-%m-%d'),
            (base_dt - timedelta(days=3)).strftime('%Y-%m-%d'),
            (base_dt - timedelta(days=1)).strftime('%Y-%m-%d'),
            base_dt.strftime('%Y-%m-%d'),
        ]
        windows = [
            '08:00 - 10:00',
            '10:00 - 12:00',
            '12:00 - 14:00',
            '14:00 - 16:00',
            '16:00 - 18:00',
        ]

        all_slots_map = {}
        for d_str in dates_to_seed:
            for centre in [c1, c2, c3, c4]:
                if not centre:
                    continue
                for win in windows:
                    existing_s = (await db.execute(
                        select(Slot).where(
                            and_(Slot.centre_id == centre.id, Slot.slot_date == d_str, Slot.time_window == win)
                        )
                    )).scalar_one_or_none()
                    if not existing_s:
                        existing_s = Slot(
                            centre_id=centre.id,
                            slot_date=d_str,
                            time_window=win,
                            capacity_units=30,  # Max 30 farmers per slot
                            booked_units=0,
                        )
                        db.add(existing_s)
                    all_slots_map[f"{centre.id}_{d_str}_{win}"] = existing_s
        await db.flush()

        print('Checking demo Farmers and multi-crop bookings...')
        farmer_configs = [
            ('farmer-demo-1', '9876543210', 'Harpreet Singh', '123456890123', 'Kuldeep Singh (Brother)', '987654321098'),
            ('farmer-demo-2', '9800000002', 'Sukhwinder Dhillon', '234567890129', None, None),
            ('farmer-demo-3', '9800000003', 'Baldev Singh', '345678901298', None, None),
        ]
        demo_farmers = []
        for fid, fphone, fname, faadhaar, falt_name, falt_aadhaar in farmer_configs:
            f_user = (await db.execute(select(User).where(User.phone == fphone))).scalar_one_or_none()
            if not f_user:
                f_user = User(
                    id=fid,
                    phone=fphone,
                    role='farmer',
                    full_name=fname,
                    aadhaar_number=faadhaar,
                    alt_person_name=falt_name,
                    alt_person_aadhaar=falt_aadhaar,
                )
                db.add(f_user)
            demo_farmers.append(f_user)
        await db.flush()
        farmer, farmer2, farmer3 = demo_farmers[0], demo_farmers[1], demo_farmers[2]

        today_str = base_dt.strftime('%Y-%m-%d')

        # Active Booking #1 in Khanna Mandi (08:00 - 10:00 today) - Multi-crop: Wheat + Mustard
        existing_b1 = (await db.execute(select(Booking).where(Booking.unique_booking_code == 'AS-1047'))).scalar_one_or_none()
        if not existing_b1:
            slot_today_1 = all_slots_map.get(f"centre-khanna_{today_str}_08:00 - 10:00")
            if slot_today_1:
                slot_today_1.booked_units += 1
                b1_crops = [
                    {"crop_name": "Wheat", "estimated_weight_quintals": 35.0, "msp_rate": 2320.0},
                    {"crop_name": "Mustard", "estimated_weight_quintals": 15.0, "msp_rate": 5650.0},
                ]
                b1 = Booking(
                    id='book-active-1',
                    farmer_id=farmer.id,
                    centre_id=c1.id,
                    slot_id=slot_today_1.id,
                    estimated_weight_quintals=50.0,
                    primary_crop='Wheat',
                    crops_data=b1_crops,
                    unique_booking_code='AS-1047',
                    qr_payload='ANNSETU:AS-1047:9876543210:50.0',
                    status='in_queue',
                    sms_status='mock_sent',
                    arrived_at=datetime.now(timezone.utc),
                )
                db.add(b1)
                await db.flush()

                for c_item in b1_crops:
                    db.add(BookingCrop(
                        booking_id=b1.id,
                        crop_name=c_item['crop_name'],
                        estimated_weight_quintals=c_item['estimated_weight_quintals'],
                        msp_rate=c_item['msp_rate'],
                    ))

                eta_1 = QueueEngine.calculate_eta(n=1, c=c1.workers_count, f=c1.capacity_factor, status=c1.status)
                q1 = QueueState(
                    id='queue-1',
                    centre_id=c1.id,
                    booking_id=b1.id,
                    position=1,
                    eta_minutes=eta_1,
                    status='waiting',
                )
                db.add(q1)

        # Active Booking #2 today (10:00 - 12:00) - Paddy
        existing_b2 = (await db.execute(select(Booking).where(Booking.unique_booking_code == 'AS-1012'))).scalar_one_or_none()
        if not existing_b2:
            slot_today_2 = all_slots_map.get(f"centre-khanna_{today_str}_10:00 - 12:00")
            if slot_today_2:
                slot_today_2.booked_units += 1
                b2_crops = [{"crop_name": "Paddy", "estimated_weight_quintals": 45.0, "msp_rate": 2300.0}]
                b2 = Booking(
                    id='book-past-2',
                    farmer_id=farmer.id,
                    centre_id=c1.id,
                    slot_id=slot_today_2.id,
                    estimated_weight_quintals=45.0,
                    primary_crop='Paddy',
                    crops_data=b2_crops,
                    unique_booking_code='AS-1012',
                    qr_payload='ANNSETU:AS-1012:9876543210:45.0',
                    status='completed',
                    sms_status='mock_sent',
                    arrived_at=datetime.now(timezone.utc),
                )
                db.add(b2)
                await db.flush()
                db.add(BookingCrop(booking_id=b2.id, crop_name='Paddy', estimated_weight_quintals=45.0, msp_rate=2300.0))

                tx2 = Transaction(
                    id='tx-past-2',
                    booking_id=b2.id,
                    centre_id=c1.id,
                    vendor_user_id=v1.id if v1 else 'vendor-1',
                    farmer_id=farmer.id,
                    actual_weight_quintals=45.0,
                    amount_paid=45.0 * 2300.00,  # ₹103,500
                    crops_data=b2_crops,
                    payment_method='dbt',
                    proof_type='transaction_id',
                    proof_data='SBIN004829104829',
                    proof_image='data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="120" height="80"><rect width="120" height="80" fill="%2310B981"/><text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle" fill="white" font-size="12" font-family="sans-serif">DBT CREDITED</text></svg>',
                    status='credited',
                )
                db.add(tx2)

        # Seed Historical Multi-Crop bookings across past days (-1d, -3d, -7d, -14d)
        hist_data = [
            (dates_to_seed[3], "08:00 - 10:00", farmer2, [("Wheat", 40.0, 2320.0), ("Gram", 20.0, 5440.0)], "AS-HIST-01"),
            (dates_to_seed[3], "10:00 - 12:00", farmer3, [("Mustard", 30.0, 5650.0)], "AS-HIST-02"),
            (dates_to_seed[2], "08:00 - 10:00", farmer, [("Wheat", 60.0, 2320.0)], "AS-HIST-03"),
            (dates_to_seed[2], "12:00 - 14:00", farmer2, [("Cotton", 25.0, 7121.0), ("Maize", 15.0, 2225.0)], "AS-HIST-04"),
            (dates_to_seed[1], "10:00 - 12:00", farmer3, [("Paddy", 80.0, 2300.0)], "AS-HIST-05"),
            (dates_to_seed[1], "14:00 - 16:00", farmer, [("Mustard", 25.0, 5650.0), ("Wheat", 30.0, 2320.0)], "AS-HIST-06"),
            (dates_to_seed[0], "08:00 - 10:00", farmer2, [("Wheat", 50.0, 2320.0)], "AS-HIST-07"),
            (dates_to_seed[0], "12:00 - 14:00", farmer3, [("Gram", 35.0, 5440.0)], "AS-HIST-08"),
        ]

        for date_str, win, f_user, c_tuples, b_code in hist_data:
            existing_hb = (await db.execute(select(Booking).where(Booking.unique_booking_code == b_code))).scalar_one_or_none()
            if not existing_hb:
                s_key = f"centre-khanna_{date_str}_{win}"
                slot_obj = all_slots_map.get(s_key)
                if slot_obj:
                    slot_obj.booked_units += 1
                    t_weight = sum(t[1] for t in c_tuples)
                    c_json = [{"crop_name": t[0], "estimated_weight_quintals": t[1], "msp_rate": t[2]} for t in c_tuples]
                    b_hist = Booking(
                        farmer_id=f_user.id,
                        centre_id=c1.id,
                        slot_id=slot_obj.id,
                        estimated_weight_quintals=t_weight,
                        primary_crop=c_tuples[0][0],
                        crops_data=c_json,
                        unique_booking_code=b_code,
                        qr_payload=f'ANNSETU:{b_code}:{f_user.phone}:{t_weight}',
                        status='completed',
                        sms_status='mock_sent',
                        arrived_at=datetime.now(timezone.utc),
                    )
                    db.add(b_hist)
                    await db.flush()

                    for t in c_tuples:
                        db.add(BookingCrop(
                            booking_id=b_hist.id,
                            crop_name=t[0],
                            estimated_weight_quintals=t[1],
                            msp_rate=t[2],
                        ))

                    tx_amt = sum(t[1] * t[2] for t in c_tuples)
                    tx_hist = Transaction(
                        booking_id=b_hist.id,
                        centre_id=c1.id,
                        vendor_user_id=v1.id if v1 else 'vendor-1',
                        farmer_id=f_user.id,
                        actual_weight_quintals=t_weight,
                        amount_paid=tx_amt,
                        crops_data=c_json,
                        payment_method='dbt',
                        proof_type='transaction_id',
                        proof_data=f'TXN-{b_code}-UTR',
                        status='credited',
                    )
                    db.add(tx_hist)

        await db.commit()
        print('Database seed complete! Existing custom user data preserved.')


if __name__ == '__main__':
    asyncio.run(seed())

