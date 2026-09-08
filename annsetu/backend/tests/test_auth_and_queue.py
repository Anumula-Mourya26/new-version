import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.services.sms_service import is_valid_indian_phone, clean_indian_phone, SMSService


def test_indian_phone_validation():
    # Valid numbers
    assert is_valid_indian_phone("9876543210") is True
    assert is_valid_indian_phone("+919876543210") is True
    assert is_valid_indian_phone("919876543210") is True
    assert is_valid_indian_phone("09876543210") is True
    assert is_valid_indian_phone("7123456789") is True
    assert is_valid_indian_phone("8987654321") is True
    assert is_valid_indian_phone("6123456789") is True
    assert is_valid_indian_phone("123456890") is True  # Admin demo phone

    # Invalid numbers
    assert is_valid_indian_phone("12345") is False
    assert is_valid_indian_phone("5876543210") is False  # Must start with 6-9
    assert is_valid_indian_phone("abcdefghij") is False
    assert is_valid_indian_phone("") is False


@pytest.mark.anyio
async def test_new_auth_system():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. OTP endpoint is removed and returns 404
        otp_res = await client.post("/api/v1/auth/send-otp", json={"phone": "9876543210"})
        assert otp_res.status_code == 404

        # 2. Farmer login with direct phone (no password or OTP needed)
        farmer_login = await client.post(
            "/api/v1/auth/login",
            json={"phone": "9876543210", "role": "farmer"}
        )
        assert farmer_login.status_code == 200
        assert farmer_login.json()["phone"] == "9876543210"
        assert farmer_login.json()["role"] == "farmer"

        # 3. Unregistered farmer returns 404
        unreg_farmer = await client.post(
            "/api/v1/auth/login",
            json={"phone": "9111122222", "role": "farmer"}
        )
        assert unreg_farmer.status_code == 404

        # 4. Admin login with Admin ID '123457890' and password '123456789'
        admin_login = await client.post(
            "/api/v1/auth/login",
            json={"role": "admin", "admin_id": "123457890", "password": "123456789"}
        )
        assert admin_login.status_code == 200
        assert admin_login.json()["role"] == "admin"

        # 5. Admin login with wrong password fails
        bad_admin = await client.post(
            "/api/v1/auth/login",
            json={"role": "admin", "admin_id": "123457890", "password": "wrongpassword"}
        )
        assert bad_admin.status_code == 401

        # Admin login with wrong Admin ID fails
        bad_admin_id = await client.post(
            "/api/v1/auth/login",
            json={"role": "admin", "admin_id": "123456789", "password": "123456789"}
        )
        assert bad_admin_id.status_code == 401

        # 6. Register a vendor via admin
        reg_vendor_res = await client.post(
            "/api/v1/admin/vendors",
            json={
                "mandi_name": "Test Greenfield Mandi",
                "state": "Punjab",
                "city": "Ludhiana",
                "address": "Sector 5, Mandi Complex",
                "manager_name": "Test Mandi Vendor",
                "manager_aadhaar": "123412341234",
                "manager_phone": "9876500001",
                "workers_count": 3
            }
        )
        assert reg_vendor_res.status_code == 200

        # 7. Vendor login with password = registered phone succeeds
        vendor_login = await client.post(
            "/api/v1/auth/login",
            json={"phone": "9876500001", "role": "vendor", "password": "9876500001"}
        )
        assert vendor_login.status_code == 200
        assert vendor_login.json()["role"] == "vendor"

        # 8. Vendor login with incorrect password fails with 401
        bad_vendor = await client.post(
            "/api/v1/auth/login",
            json={"phone": "9876500001", "role": "vendor", "password": "wrongpassword"}
        )
        assert bad_vendor.status_code == 401


@pytest.mark.anyio
async def test_queue_admission_flow_bugfix():
    """
    Verifies that:
    1. Confirming arrival alone DOES NOT add farmer to the vendor's active queue.
    2. Arrived status is recorded.
    3. Active queue only contains farmer AFTER vendor explicitly admits via scan-checkin.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Login farmer
        login_res = await client.post("/api/v1/auth/login", json={"phone": "9876543210", "role": "farmer"})
        assert login_res.status_code == 200
        farmer_id = login_res.json()["user_id"]

        # 2. Get Centre & Slot
        centres_res = await client.get("/api/v1/centres")
        centre_id = centres_res.json()[0]["id"]
        slots_res = await client.get(f"/api/v1/centres/{centre_id}/slots")
        slot_id = slots_res.json()[0]["id"]

        # 3. Create booking
        b_res = await client.post("/api/v1/bookings", json={
            "farmer_id": farmer_id,
            "centre_id": centre_id,
            "slot_id": slot_id,
            "crops": [{"crop_name": "Wheat", "estimated_weight_quintals": 25.0, "msp_rate": 2320.0}]
        })
        assert b_res.status_code == 200
        booking_code = b_res.json()["unique_booking_code"]

        # 4. Farmer confirms arrival
        arr_res = await client.post("/api/v1/bookings/arrival-confirm", json={"booking_code": booking_code})
        assert arr_res.status_code == 200
        assert arr_res.json()["booking_status"] == "arrived"
        assert arr_res.json()["position"] is None

        # 5. Check vendor active queue: Farmer MUST NOT be in the active waiting queue yet!
        q_res_before = await client.get(f"/api/v1/vendor/{centre_id}/queue")
        assert q_res_before.status_code == 200
        queue_codes_before = [item["booking_code"] for item in q_res_before.json()]
        assert booking_code not in queue_codes_before

        # 6. Vendor admits farmer via scan-checkin
        admit_res = await client.post("/api/v1/vendor/scan-checkin", json={"booking_code": booking_code})
        assert admit_res.status_code == 200
        assert admit_res.json()["status"] == "success"
        assert admit_res.json()["position"] is not None

        # 7. Check vendor active queue: Farmer MUST NOW be in the active waiting queue!
        q_res_after = await client.get(f"/api/v1/vendor/{centre_id}/queue")
        assert q_res_after.status_code == 200
        queue_codes_after = [item["booking_code"] for item in q_res_after.json()]
        assert booking_code in queue_codes_after
