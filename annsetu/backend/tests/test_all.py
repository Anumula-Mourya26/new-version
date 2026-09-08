import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.services.queue_engine import QueueEngine


@pytest.mark.anyio
async def test_health_check():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["app"] == "AnnSetu"


def test_queue_eta_formula():
    # Case 1: Normal (F=1.0), C=2, N=4
    # ceil(4 * 25 / (2 * 1.0)) = ceil(50.0) = 50
    assert QueueEngine.calculate_eta(n=4, c=2, f=1.0, status="NORMAL") == 50

    # Case 2: Busy (F=0.8), C=2, N=4
    # raw = (4 * 25) / (2 * 0.8) = 100 / 1.6 = 62.5 -> ceil = 63
    assert QueueEngine.calculate_eta(n=4, c=2, f=0.8, status="BUSY") == 63

    # Case 3: Lifting Delayed (F=0.6), C=1, N=3
    # raw = (3 * 25) / (1 * 0.6) = 75 / 0.6 = 125.0 -> ceil = 125
    assert QueueEngine.calculate_eta(n=3, c=1, f=0.6, status="LIFTING_DELAYED") == 125

    # Case 4: Paused (F=0.0) -> None
    assert QueueEngine.calculate_eta(n=5, c=2, f=0.0, status="PAUSED") is None

    # Case 5: N=0 (done/no wait) -> 0
    assert QueueEngine.calculate_eta(n=0, c=2, f=1.0) == 0


@pytest.mark.anyio
async def test_auth_and_roles():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Admin login with Admin ID '123457890' and Password '123456789'
        admin_login = await client.post("/api/v1/auth/login", json={"role": "admin", "admin_id": "123457890", "password": "123456789"})
        assert admin_login.status_code == 200
        assert admin_login.json()["role"] == "admin"

        # Invalid Admin ID fails
        bad_admin_id = await client.post("/api/v1/auth/login", json={"role": "admin", "admin_id": "999999999", "password": "123456789"})
        assert bad_admin_id.status_code == 401

        # 2. Farmer Signup with Alternate Person Details & 4-digit PIN
        signup_res = await client.post("/api/v1/auth/farmer/signup", json={
            "phone": "9812345678",
            "full_name": "Balwinder Singh",
            "aadhaar_number": "789012345678",
            "pin": "4321",
            "confirm_pin": "4321",
            "alt_person_name": "Manjit Kaur",
            "alt_person_aadhaar": "890123456789",
        })
        assert signup_res.status_code == 200
        farmer_auth = signup_res.json()
        assert farmer_auth["role"] == "farmer"

        # 3. Farmer Login with PIN
        farmer_login = await client.post("/api/v1/auth/login", json={"phone": "9812345678", "role": "farmer", "pin": "4321"})
        assert farmer_login.status_code == 200
        assert farmer_login.json()["user_id"] == farmer_auth["user_id"]

        # 4. Vendor Login without prior admin registration fails
        unregistered_vendor = await client.post("/api/v1/auth/login", json={"phone": "9999999999", "role": "vendor"})
        assert unregistered_vendor.status_code == 404
        assert "Vendors must be registered by the District Admin" in unregistered_vendor.json()["detail"]


@pytest.mark.anyio
async def test_farmer_booking_and_arrival_journey():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Fetch centres filtered by State and City
        centres_res = await client.get("/api/v1/centres?state=Punjab&city=Ludhiana")
        assert centres_res.status_code == 200
        centres = centres_res.json()
        assert len(centres) >= 1
        c = centres[0]

        # 2. Fetch 120-minute slots
        slots_res = await client.get(f"/api/v1/centres/{c['id']}/slots")
        assert slots_res.status_code == 200
        slots = slots_res.json()
        assert len(slots) >= 1
        slot = slots[0]
        assert " - " in slot["time_window"]  # e.g., '08:00 - 10:00'
        assert slot["capacity_units"] == 30   # Max 30 farmers cap

        # 3. Book slot
        book_res = await client.post("/api/v1/bookings", json={
            "farmer_id": "farmer-demo-1",
            "centre_id": c["id"],
            "slot_id": slot["id"],
            "estimated_weight_quintals": 42.5,
        })
        assert book_res.status_code == 200
        booking = book_res.json()
        assert booking["unique_booking_code"].startswith("AS-")
        booking_code = booking["unique_booking_code"]
        booking_id = booking["id"]

        # 4. Confirm arrival at location (arrives without auto-queuing)
        arrival_res = await client.post("/api/v1/bookings/arrival-confirm", json={"booking_code": booking_code})
        assert arrival_res.status_code == 200
        arr_data = arrival_res.json()
        assert arr_data["booking_status"] == "arrived"
        assert arr_data["arrived_at"] is not None

        # 4b. Vendor admits farmer to virtual queue
        admit_res = await client.post("/api/v1/vendor/scan-checkin", json={"booking_code": booking_code})
        assert admit_res.status_code == 200
        admit_data = admit_res.json()
        assert admit_data["position"] >= 1
        assert admit_data["eta_minutes"] is not None

        # 5. View farmer booking history
        history_res = await client.get("/api/v1/bookings/farmer/farmer-demo-1")
        assert history_res.status_code == 200
        history = history_res.json()
        assert len(history) >= 2

        # 6. Cancel booking
        cancel_res = await client.delete(f"/api/v1/bookings/{booking_id}")
        assert cancel_res.status_code == 200


@pytest.mark.anyio
async def test_vendor_and_admin_workflow():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Vendor updates settings (C=4 workers, F=0.8 Busy)
        v_update = await client.put("/api/v1/vendor/centre-khanna/settings", json={
            "workers_count": 4,
            "capacity_factor": 0.8,
            "status": "BUSY",
        })
        assert v_update.status_code == 200
        assert v_update.json()["workers_count"] == 4

        # 2. Vendor gets slot roster (max 30 cap)
        roster_res = await client.get("/api/v1/vendor/centre-khanna/slots/roster")
        assert roster_res.status_code == 200
        roster = roster_res.json()
        assert len(roster) >= 1
        assert roster[0]["capacity_units"] == 30

        # 3. Vendor check-in via QR / code
        checkin_res = await client.post("/api/v1/vendor/scan-checkin", json={"booking_code": "AS-1047"})
        assert checkin_res.status_code == 200
        assert checkin_res.json()["booking_code"] == "AS-1047"

        # 4. Vendor records payment with proof upload
        pay_res = await client.post("/api/v1/vendor/payment/submit", json={
            "booking_id": "book-active-1",
            "actual_weight_quintals": 51.0,
            "amount_paid": 51.0 * 2320.00,
            "payment_method": "dbt",
            "proof_type": "transaction_id",
            "proof_data": "PUNB9988776655",
        })
        assert pay_res.status_code == 200
        assert pay_res.json()["status"] == "success"

        # 5. Vendor views transactions
        tx_res = await client.get("/api/v1/vendor/centre-khanna/transactions")
        assert tx_res.status_code == 200
        txs = tx_res.json()
        assert len(txs) >= 1

        # 6. Admin onboards new vendor mandi
        admin_create_vendor = await client.post("/api/v1/admin/vendors", json={
            "mandi_name": "Amritsar Golden Mandi",
            "state": "Punjab",
            "city": "Amritsar",
            "address": "Near Bypass Mandi Road, Amritsar",
            "manager_name": "Simranjeet Singh",
            "manager_aadhaar": "998877665544",
            "manager_phone": "9876500099",
            "workers_count": 3,
            "pin": "9876",
            "confirm_pin": "9876",
        })
        assert admin_create_vendor.status_code == 200
        assert "registered successfully" in admin_create_vendor.json()["message"]

        # 7. Admin lists users and views bookings
        users_res = await client.get("/api/v1/admin/users")
        assert users_res.status_code == 200
        assert len(users_res.json()) >= 4

        bookings_res = await client.get("/api/v1/admin/bookings")
        assert bookings_res.status_code == 200
        assert len(bookings_res.json()) >= 1
