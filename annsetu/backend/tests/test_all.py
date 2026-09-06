import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.services.queue_engine import QueueEngine


@pytest.mark.anyio
async def test_health_check():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url='http://test') as client:
        resp = await client.get('/api/v1/health')
        assert resp.status_code == 200
        data = resp.json()
        assert data['status'] == 'healthy'
        assert data['app'] == 'AnnSetu'


def test_queue_engine_mmc_math():
    # Position 1: 0 wait
    assert QueueEngine.calculate_eta(position=1, active_counters=1, service_minutes_per_counter=20) == 0
    # Position 2: 1 person * 20 min / 1 counter = 20 min
    assert QueueEngine.calculate_eta(position=2, active_counters=1, service_minutes_per_counter=20) == 20
    # Position 5: 4 ahead * 20 min / 1 counter = 80 min
    assert QueueEngine.calculate_eta(position=5, active_counters=1, service_minutes_per_counter=20) == 80

    # Multi-counter (c=2)
    assert QueueEngine.calculate_eta(position=5, active_counters=2, service_minutes_per_counter=20) == 40
    assert QueueEngine.calculate_eta(position=6, active_counters=2, service_minutes_per_counter=20) == 50

    # High capacity (c=4)
    assert QueueEngine.calculate_eta(position=9, active_counters=4, service_minutes_per_counter=20) == 40


@pytest.mark.anyio
async def test_e2e_farmer_journey():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url='http://test') as client:
        # 1. List centres
        centres_res = await client.get('/api/v1/centres')
        assert centres_res.status_code == 200
        centres = centres_res.json()
        assert len(centres) >= 1
        c1 = centres[0]
        c1_id = c1['id']
        dist_id = c1['district_id']

        # 2. List slots
        slots_res = await client.get(f'/api/v1/centres/{c1_id}/slots')
        assert slots_res.status_code == 200
        slots = slots_res.json()
        assert len(slots) >= 1
        slot = slots[0]
        slot_id = slot['id']

        import random, uuid
        test_suffix = str(random.randint(10000000, 99999999))
        test_phone = f'+9198{test_suffix}'
        test_aadhaar = f'AADHAAR-{test_suffix}'

        # 3. Request and verify OTP
        otp_req = await client.post('/api/v1/auth/otp/request', json={'phone': test_phone})
        assert otp_req.status_code == 200

        auth_res = await client.post('/api/v1/auth/otp/verify', json={'phone': test_phone, 'otp': '1234'})
        assert auth_res.status_code == 200
        token_data = auth_res.json()
        user_id = token_data['user_id']

        # 4. Register farmer profile
        reg_res = await client.post('/api/v1/farmers', json={
            'phone': test_phone,
            'full_name': 'Test Farmer',
            'aadhaar_ref': test_aadhaar,
            'bank_account_ref': 'SBIN0001234',
            'village': 'Test Village',
            'district_id': dist_id,
        })
        assert reg_res.status_code == 200
        farmer = reg_res.json()
        farmer_id = farmer['id']

        # 5. Book a slot
        book_res = await client.post('/api/v1/bookings', json={
            'farmer_id': farmer_id,
            'slot_id': slot_id,
            'declared_quantity_quintals': 50.0,
        })
        assert book_res.status_code == 200
        booking = book_res.json()
        booking_code = booking['unique_booking_code']
        assert booking_code.startswith('AS-')

        # 6. Gate check-in
        checkin_res = await client.post('/api/v1/gate/check-in', json={
            'booking_code': booking_code
        })
        assert checkin_res.status_code == 200
        checkin_data = checkin_res.json()
        assert checkin_data['position'] >= 1
        token_id = checkin_data['token_id']

        # 7. Check live queue
        q_res = await client.get(f'/api/v1/queue/{c1_id}/live')
        assert q_res.status_code == 200
        q_data = q_res.json()
        assert q_data['total_waiting'] >= 1

        # 8. Record procurement (Quality check + Weighbridge)
        proc_res = await client.post('/api/v1/procurement', json={
            'token_id': token_id,
            'moisture_pct': 13.5,
            'quality_result': 'accepted',
            'weighed_quantity_quintals': 48.0,
        })
        assert proc_res.status_code == 200
        proc_data = proc_res.json()
        assert proc_data['receipt_ref'].startswith('REC-AS-')
        assert proc_data['amount_due'] == 48.0 * 2320.00

        # 9. Verify Farmer Status Timeline
        timeline_res = await client.get(f'/api/v1/farmers/{farmer_id}/status-timeline')
        assert timeline_res.status_code == 200
        timeline_data = timeline_res.json()
        assert timeline_data['payment_stage'] == 'sold'
        assert len(timeline_data['timeline']) == 4

        # 10. District Congestion Check
        dist_res = await client.get(f'/api/v1/district/{dist_id}/congestion')
        assert dist_res.status_code == 200
        dist_data = dist_res.json()
        assert len(dist_data['centres']) >= 1

@pytest.mark.anyio
async def test_staged_payment_trust_timeline():
    from app.core.db import AsyncSessionLocal
    from app.models.entities import Payment
    import uuid

    # Create a fresh test payment in stage 'sold'
    test_proc_id = str(uuid.uuid4())
    async with AsyncSessionLocal() as session:
        payment = Payment(
            procurement_id=test_proc_id,
            amount_due=116000.0,
            payee_type='farmer_direct',
            stage='sold',
        )
        session.add(payment)
        await session.commit()
        await session.refresh(payment)
        payment_id = payment.id

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url='http://test') as client:
        # Step 1 -> Step 2: advice_generated
        p1 = await client.patch(f'/api/v1/payments/{payment_id}/stage', json={'stage': 'advice_generated'})
        assert p1.status_code == 200
        assert p1.json()['new_stage'] == 'advice_generated'

        # Step 2 -> Step 3: advice_reached_agent
        p2 = await client.patch(f'/api/v1/payments/{payment_id}/stage', json={'stage': 'advice_reached_agent'})
        assert p2.status_code == 200
        assert p2.json()['new_stage'] == 'advice_reached_agent'

        # Step 3 -> Step 4: credited (with UTR)
        p3 = await client.patch(f'/api/v1/payments/{payment_id}/stage', json={
            'stage': 'credited',
            'utr_ref': 'SBIN8899771122',
        })
        assert p3.status_code == 200
        assert p3.json()['new_stage'] == 'credited'
        assert p3.json()['utr_ref'] == 'SBIN8899771122'

        # Verify illegal backward transition fails
        fail_res = await client.patch(f'/api/v1/payments/{payment_id}/stage', json={'stage': 'sold'})
        assert fail_res.status_code == 400
        assert 'Cannot transition backwards' in fail_res.json()['detail']


@pytest.mark.anyio
async def test_district_1click_redirect():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url='http://test') as client:
        dist_id = 'dist-punjab-ludhiana'
        red_res = await client.post(f'/api/v1/district/{dist_id}/redirect', json={
            'from_centre_id': 'centre-khanna',
            'to_centre_id': 'centre-samrala',
            'farmer_count': 15,
        })
        assert red_res.status_code == 200
        res_data = red_res.json()
        assert res_data['status'] == 'success'
        assert res_data['redirected_count'] == 15
        assert 'Khanna' in res_data['source_centre']
        assert 'Samrala' in res_data['target_centre']
