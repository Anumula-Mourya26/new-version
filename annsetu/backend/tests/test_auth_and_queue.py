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

        # 2. Pre-existing farmer logs in with default PIN 1234
        farmer_login = await client.post(
            "/api/v1/auth/login",
            json={"phone": "9876543210", "role": "farmer", "pin": "1234"}
        )
        assert farmer_login.status_code == 200
        assert farmer_login.json()["phone"] == "9876543210"
        assert farmer_login.json()["role"] == "farmer"

        # Farmer login with wrong PIN fails with 401
        bad_farmer_pin = await client.post(
            "/api/v1/auth/login",
            json={"phone": "9876543210", "role": "farmer", "pin": "0000"}
        )
        assert bad_farmer_pin.status_code == 401

        # 3. Unregistered farmer returns 404
        unreg_farmer = await client.post(
            "/api/v1/auth/login",
            json={"phone": "9111122222", "role": "farmer", "pin": "1234"}
        )
        assert unreg_farmer.status_code == 404

        # 4. Admin login with Admin ID '123457890' and password '123456789' (completely untouched)
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

        # 6. Farmer registration requires matching 4-digit PIN
        mismatch_signup = await client.post("/api/v1/auth/farmer/signup", json={
            "phone": "9811122233",
            "full_name": "Test PIN Farmer",
            "aadhaar_number": "112211221122",
            "pin": "7788",
            "confirm_pin": "9999",
        })
        assert mismatch_signup.status_code == 400
        assert "must match exactly" in mismatch_signup.json()["detail"]

        valid_signup = await client.post("/api/v1/auth/farmer/signup", json={
            "phone": "9811122233",
            "full_name": "Test PIN Farmer",
            "aadhaar_number": "112211221122",
            "pin": "7788",
            "confirm_pin": "7788",
        })
        assert valid_signup.status_code == 200

        # Newly registered farmer cannot log in with default 1234; must use their set PIN 7788
        new_farmer_default = await client.post(
            "/api/v1/auth/login",
            json={"phone": "9811122233", "role": "farmer", "pin": "1234"}
        )
        assert new_farmer_default.status_code == 401

        new_farmer_ok = await client.post(
            "/api/v1/auth/login",
            json={"phone": "9811122233", "role": "farmer", "pin": "7788"}
        )
        assert new_farmer_ok.status_code == 200

        # 7. Admin creates vendor: mismatched PIN fails with 400
        mismatch_vendor = await client.post(
            "/api/v1/admin/vendors",
            json={
                "mandi_name": "Test Greenfield Mandi",
                "state": "Punjab",
                "city": "Ludhiana",
                "address": "Sector 5, Mandi Complex",
                "manager_name": "Test Mandi Vendor",
                "manager_aadhaar": "123412341234",
                "manager_phone": "9876500055",
                "workers_count": 3,
                "pin": "5566",
                "confirm_pin": "5567"
            }
        )
        assert mismatch_vendor.status_code == 400
        assert "must match exactly" in mismatch_vendor.json()["detail"]

        # Admin creates vendor with matching PIN succeeds
        reg_vendor_res = await client.post(
            "/api/v1/admin/vendors",
            json={
                "mandi_name": "Test Greenfield Mandi",
                "state": "Punjab",
                "city": "Ludhiana",
                "address": "Sector 5, Mandi Complex",
                "manager_name": "Test Mandi Vendor",
                "manager_aadhaar": "123412341234",
                "manager_phone": "9876500055",
                "workers_count": 3,
                "pin": "5566",
                "confirm_pin": "5566"
            }
        )
        assert reg_vendor_res.status_code == 200

        # 8. Vendor login with new PIN succeeds
        vendor_login = await client.post(
            "/api/v1/auth/login",
            json={"phone": "9876500055", "role": "vendor", "pin": "5566"}
        )
        assert vendor_login.status_code == 200
        assert vendor_login.json()["role"] == "vendor"

        # Vendor login using phone-number-as-password fails (no dual-credential path)
        phone_pw_vendor = await client.post(
            "/api/v1/auth/login",
            json={"phone": "9876500055", "role": "vendor", "password": "9876500055"}
        )
        assert phone_pw_vendor.status_code == 401

        # Pre-existing vendor can log in with default PIN 1234
        pre_vendor = await client.post(
            "/api/v1/auth/login",
            json={"phone": "9876500001", "role": "vendor", "pin": "1234"}
        )
        assert pre_vendor.status_code == 200

        # Pre-existing vendor cannot log in with phone number as password
        pre_vendor_phone = await client.post(
            "/api/v1/auth/login",
            json={"phone": "9876500001", "role": "vendor", "password": "9876500001"}
        )
        assert pre_vendor_phone.status_code == 401


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
        # 1. Login farmer with default PIN 1234
        login_res = await client.post("/api/v1/auth/login", json={"phone": "9876543210", "role": "farmer", "pin": "1234"})
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


@pytest.mark.anyio
async def test_pin_security_and_validation():
    """
    Dedicated test for 4-digit PIN security feature:
    - Farmer registration PIN + confirm PIN validation
    - Admin vendor creation PIN + confirm PIN validation
    - Default PIN 1234 for pre-existing accounts
    - Strict rejection of phone-as-password for vendors
    - Untouched admin login
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # A. Non-4-digit PIN in farmer signup returns 422
        bad_len_signup = await client.post("/api/v1/auth/farmer/signup", json={
            "phone": "9812999901",
            "full_name": "Length Test Farmer",
            "aadhaar_number": "998811223344",
            "pin": "123",
            "confirm_pin": "123",
        })
        assert bad_len_signup.status_code == 422

        alpha_signup = await client.post("/api/v1/auth/farmer/signup", json={
            "phone": "9812999901",
            "full_name": "Alpha Test Farmer",
            "aadhaar_number": "998811223344",
            "pin": "abcd",
            "confirm_pin": "abcd",
        })
        assert alpha_signup.status_code == 422

        # B. Non-matching PIN in farmer signup returns 400
        mismatch_signup = await client.post("/api/v1/auth/farmer/signup", json={
            "phone": "9812999901",
            "full_name": "Mismatch Test Farmer",
            "aadhaar_number": "998811223344",
            "pin": "2468",
            "confirm_pin": "1357",
        })
        assert mismatch_signup.status_code == 400
        assert "must match exactly" in mismatch_signup.json()["detail"]

        # C. Successful farmer signup with matching 4-digit PIN
        valid_signup = await client.post("/api/v1/auth/farmer/signup", json={
            "phone": "9812999901",
            "full_name": "Matching Test Farmer",
            "aadhaar_number": "998811223344",
            "pin": "2468",
            "confirm_pin": "2468",
        })
        assert valid_signup.status_code == 200

        # D. New farmer cannot use default PIN 1234
        default_fail = await client.post("/api/v1/auth/login", json={
            "phone": "9812999901",
            "role": "farmer",
            "pin": "1234"
        })
        assert default_fail.status_code == 401

        # E. New farmer succeeds with chosen PIN
        pin_ok = await client.post("/api/v1/auth/login", json={
            "phone": "9812999901",
            "role": "farmer",
            "pin": "2468"
        })
        assert pin_ok.status_code == 200

        # F. Admin vendor creation: non-matching PIN returns 400
        vendor_mismatch = await client.post("/api/v1/admin/vendors", json={
            "mandi_name": "Pin Test Mandi",
            "state": "Punjab",
            "city": "Ludhiana",
            "address": "GT Road, Yard 4",
            "manager_name": "Vendor PIN Manager",
            "manager_aadhaar": "991122334455",
            "manager_phone": "9876599901",
            "workers_count": 3,
            "pin": "8899",
            "confirm_pin": "8800"
        })
        assert vendor_mismatch.status_code == 400
        assert "must match exactly" in vendor_mismatch.json()["detail"]

        # G. Admin vendor creation: matching PIN succeeds
        vendor_valid = await client.post("/api/v1/admin/vendors", json={
            "mandi_name": "Pin Test Mandi",
            "state": "Punjab",
            "city": "Ludhiana",
            "address": "GT Road, Yard 4",
            "manager_name": "Vendor PIN Manager",
            "manager_aadhaar": "991122334455",
            "manager_phone": "9876599901",
            "workers_count": 3,
            "pin": "8899",
            "confirm_pin": "8899"
        })
        assert vendor_valid.status_code == 200

        # H. Vendor login with phone-as-password returns 401
        vendor_phone_pw = await client.post("/api/v1/auth/login", json={
            "phone": "9876599901",
            "role": "vendor",
            "password": "9876599901"
        })
        assert vendor_phone_pw.status_code == 401

        # I. Vendor login with correct PIN succeeds
        vendor_pin_ok = await client.post("/api/v1/auth/login", json={
            "phone": "9876599901",
            "role": "vendor",
            "pin": "8899"
        })
        assert vendor_pin_ok.status_code == 200

        # J. Admin login remains completely untouched
        admin_login = await client.post("/api/v1/auth/login", json={
            "role": "admin",
            "admin_id": "123457890",
            "password": "123456789"
        })
        assert admin_login.status_code == 200
        assert admin_login.json()["role"] == "admin"
