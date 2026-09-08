import uuid
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from pathlib import Path


@pytest.mark.anyio
async def test_repair_farmer_signup_optional_fields():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        uid = str(uuid.uuid4().int)[:6]
        res = await client.post("/api/v1/auth/farmer/signup", json={
            "phone": f"991{uid}",
            "full_name": "Ramesh Chander",
            "aadhaar_number": f"112233{uid}",
            "pin": "1234",
            "confirm_pin": "1234",
        })
        assert res.status_code == 200
        data = res.json()
        assert data["role"] == "farmer"
        assert data["user_id"] is not None


@pytest.mark.anyio
async def test_repair_farmer_gate_pass_and_lifecycle():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Get centre and slot
        c_res = await client.get("/api/v1/centres", params={"state": "Punjab", "city": "Ludhiana"})
        assert c_res.status_code == 200
        centre = c_res.json()[0]

        s_res = await client.get(f"/api/v1/centres/{centre['id']}/slots")
        assert s_res.status_code == 200
        slot = s_res.json()[0]

        # 2. Generate gate pass (reserve slot)
        book = await client.post("/api/v1/bookings", json={
            "farmer_id": "farmer-demo-1",
            "centre_id": centre["id"],
            "slot_id": slot["id"],
            "estimated_weight_quintals": 35.0,
        })
        assert book.status_code == 200
        b_data = book.json()
        booking_id = b_data["id"]
        assert b_data["unique_booking_code"].startswith("AS-")

        # 3. Fetch active booking (gate pass view)
        active_res = await client.get("/api/v1/bookings/farmer/farmer-demo-1/active")
        assert active_res.status_code == 200
        active_data = active_res.json()
        assert active_data["id"] == booking_id
        assert active_data["unique_booking_code"] == b_data["unique_booking_code"]
        assert active_data["qr_payload"] is not None

        # 4. Confirm arrival
        arrive_res = await client.post(f"/api/v1/bookings/{booking_id}/arrive")
        assert arrive_res.status_code == 200
        assert arrive_res.json()["status"] == "success"
        assert arrive_res.json()["booking_status"] in ["arrived", "in_queue"]

        # 5. Cancel booking
        cancel_res = await client.post(f"/api/v1/bookings/{booking_id}/cancel")
        assert cancel_res.status_code == 200
        assert cancel_res.json()["status"] == "success"


@pytest.mark.anyio
async def test_repair_vendor_queue_and_admit():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        c_res = await client.get("/api/v1/centres", params={"state": "Punjab", "city": "Ludhiana"})
        centre_id = c_res.json()[0]["id"]
        s_res = await client.get(f"/api/v1/centres/{centre_id}/slots")
        slot_id = s_res.json()[0]["id"]

        book_res = await client.post("/api/v1/bookings", json={
            "farmer_id": "farmer-demo-1",
            "centre_id": centre_id,
            "slot_id": slot_id,
            "estimated_weight_quintals": 28.0,
        })
        booking_code = book_res.json()['unique_booking_code']

        # Vendor admits farmer
        admit = await client.post("/api/v1/vendor/scan-checkin", json={"booking_code": booking_code})
        assert admit.status_code == 200
        assert admit.json()["position"] >= 1

        # Vendor views active queue
        q_res = await client.get(f"/api/v1/vendor/{centre_id}/queue")
        assert q_res.status_code == 200
        queue = q_res.json()
        assert len(queue) >= 1
        matches = [q for q in queue if q["booking_code"] == booking_code]
        assert len(matches) == 1
        assert matches[0]["position"] >= 1


@pytest.mark.anyio
async def test_repair_payment_with_proof_image():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        c_res = await client.get("/api/v1/centres", params={"state": "Punjab", "city": "Ludhiana"})
        centre_id = c_res.json()[0]["id"]
        s_res = await client.get(f"/api/v1/centres/{centre_id}/slots")
        slot_id = s_res.json()[0]["id"]

        book_res = await client.post("/api/v1/bookings", json={
            "farmer_id": "farmer-demo-1",
            "centre_id": centre_id,
            "slot_id": slot_id,
            "estimated_weight_quintals": 19.5,
        })
        b_data = book_res.json()
        booking_id = b_data["id"]
        booking_code = b_data["unique_booking_code"]

        await client.post("/api/v1/vendor/scan-checkin", json={"booking_code": booking_code})

        sample_img = "data:image/svg+xml;utf8,<svg>TEST</svg>"
        pay_res = await client.post("/api/v1/vendor/payment/submit", json={
            "booking_id": booking_id,
            "actual_weight_quintals": 20.0,
            "amount_paid": 20.0 * 2320,
            "payment_method": "dbt",
            "proof_type": "transaction_id",
            "proof_data": "UTR-AUDIT-9999",
            "proof_image": sample_img,
        })
        assert pay_res.status_code == 200
        assert pay_res.json()["proof_image"] == sample_img

        # Check transaction list
        tx_res = await client.get(f"/api/v1/vendor/{centre_id}/transactions")
        assert tx_res.status_code == 200
        tx_list = tx_res.json()
        found = [t for t in tx_list if t["booking_code"] == booking_code]
        assert len(found) == 1
        assert found[0]["proof_image"] == sample_img


@pytest.mark.anyio
async def test_repair_admin_delete_entities():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        uid = str(uuid.uuid4().int)[:6]
        signup = await client.post("/api/v1/auth/farmer/signup", json={
            "phone": f"980{uid}",
            "full_name": "Test Delete Farmer",
            "aadhaar_number": f"999888{uid}",
            "pin": "1234",
            "confirm_pin": "1234",
        })
        assert signup.status_code == 200
        del_user_id = signup.json()['user_id']

        c_res = await client.get("/api/v1/centres", params={"state": "Punjab", "city": "Ludhiana"})
        centre_id = c_res.json()[0]["id"]
        s_res = await client.get(f"/api/v1/centres/{centre_id}/slots")
        slot_id = s_res.json()[0]["id"]

        book_res = await client.post("/api/v1/bookings", json={
            "farmer_id": del_user_id,
            "centre_id": centre_id,
            "slot_id": slot_id,
            "estimated_weight_quintals": 15.0,
        })
        assert book_res.status_code == 200
        del_booking_id = book_res.json()["id"]

        # Admin lists bookings
        admin_b = await client.get("/api/v1/admin/bookings")
        assert admin_b.status_code == 200
        b_list = admin_b.json()
        found_b = [b for b in b_list if b.get("id") == del_booking_id]
        assert len(found_b) == 1
        assert "id" in found_b[0]
        assert "centre_name" in found_b[0]

        # Admin deletes booking
        del_b = await client.delete(f"/api/v1/admin/bookings/{del_booking_id}")
        assert del_b.status_code == 200

        # Admin deletes user
        del_u = await client.delete(f"/api/v1/admin/users/{del_user_id}")
        assert del_u.status_code == 200


def test_repair_frontend_requirements():
    html_path = Path('app/static/index.html')
    assert html_path.exists()
    content = html_path.read_text(encoding='utf-8')

    # Requirement 2: No exposed formula text
    assert 'Formula: ETA =' not in content
    assert 'P = Position in line' not in content
    assert 'id="queue-eta-display"' in content

    # Requirement 3: Strict single-role containment
    assert "tabAdmin.classList.add('hidden')" in content
    assert "tabVendor.classList.add('hidden')" in content
    assert "tabFarmer.classList.add('hidden')" in content

    # Requirement 4: Proof image upload and display
    assert 'id="weigh-proof-image"' in content
    assert 'id="pay-card-receipt-wrap"' in content
