import pytest
from httpx import AsyncClient, ASGITransport
from datetime import datetime, timedelta

from app.main import app
from app.services.sms_service import SMSService, format_phone_e164


def test_phone_formatting():
    assert format_phone_e164("9876543210") == "+919876543210"
    assert format_phone_e164("+919876543210") == "+919876543210"
    assert format_phone_e164("919876543210") == "+919876543210"
    assert format_phone_e164("09876543210") == "+919876543210"
    assert format_phone_e164("") == ""


@pytest.mark.anyio
async def test_sms_service_graceful_fallback():
    # Verify mock SMS dispatch succeeds gracefully
    res = await SMSService.send_sms_direct("9876543210", "Test SMS Content")
    assert res["success"] is True
    assert res["status"] == "mock_sent"
    assert res["recipient"] in ("9876543210", "+919876543210")

    # Empty phone number returns error without throwing exception
    err_res = await SMSService.send_sms_direct("", "Test")
    assert err_res["success"] is False
    assert err_res["status"] == "failed"


@pytest.mark.anyio
async def test_multi_crop_booking_and_sms():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Farmer login
        login_res = await client.post("/api/v1/auth/login", json={"phone": "9876543210", "role": "farmer"})
        assert login_res.status_code == 200
        farmer_id = login_res.json()["user_id"]

        # Fetch centre and slot
        centres_res = await client.get("/api/v1/centres")
        assert centres_res.status_code == 200
        centre = centres_res.json()[0]
        centre_id = centre["id"]

        slots_res = await client.get(f"/api/v1/centres/{centre_id}/slots")
        assert slots_res.status_code == 200
        # Pick a slot that still has capacity
        slot = [s for s in slots_res.json() if s["remaining_units"] > 0][-1]
        slot_id = slot["id"]

        # 1. Create booking with multiple crops: Wheat + Mustard + Gram
        booking_payload = {
            "farmer_id": farmer_id,
            "centre_id": centre_id,
            "slot_id": slot_id,
            "crops": [
                {"crop_name": "Wheat", "estimated_weight_quintals": 20.0, "msp_rate": 2320.0},
                {"crop_name": "Mustard", "estimated_weight_quintals": 10.0, "msp_rate": 5650.0},
                {"crop_name": "Gram", "estimated_weight_quintals": 5.0, "msp_rate": 5440.0},
            ]
        }
        res = await client.post("/api/v1/bookings", json=booking_payload)
        assert res.status_code == 200
        b_data = res.json()
        assert b_data["estimated_weight_quintals"] == 35.0
        assert b_data["primary_crop"] == "Wheat"
        assert len(b_data["crops_data"]) == 3
        assert b_data["sms_status"] in ("sent", "mock_sent", "failed")
        booking_id = b_data["id"]

        # 2. Resend SMS endpoint
        resend_res = await client.post(f"/api/v1/bookings/{booking_id}/resend-sms")
        assert resend_res.status_code == 200
        assert resend_res.json()["status"] == "success"
        assert resend_res.json()["sms_status"] in ("sent", "mock_sent", "failed")


@pytest.mark.anyio
async def test_historical_schedule_retrieval():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Query schedule history for centre-khanna
        today_str = datetime.now().strftime("%Y-%m-%d")
        hist_res = await client.get(f"/api/v1/centres/centre-khanna/schedule/history?date={today_str}")
        assert hist_res.status_code == 200
        data = hist_res.json()

        assert data["centre_id"] == "centre-khanna"
        assert data["date"] == today_str
        assert data["total_slots"] == 5
        assert data["total_capacity_units"] == 150
        assert len(data["slots"]) == 5
        # Check first slot has booked entries
        assert data["slots"][0]["booked_count"] >= 1
        assert len(data["slots"][0]["bookings"]) >= 1
        assert data["slots"][0]["bookings"][0]["farmer_name"] != ""

        # Test past date from seed (-7 days)
        past_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        past_hist = await client.get(f"/api/v1/centres/centre-khanna/schedule/history?date={past_date}")
        assert past_hist.status_code == 200
        past_data = past_hist.json()
        assert past_data["date"] == past_date
        assert past_data["total_volume_quintals"] > 0


@pytest.mark.anyio
async def test_crop_trends_analytics():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Daily timeframe
        res_daily = await client.get("/api/v1/analytics/crop-trends?timeframe=daily")
        assert res_daily.status_code == 200
        daily_data = res_daily.json()
        assert len(daily_data["crops_analyzed"]) > 0
        assert len(daily_data["trends"]) > 0
        assert "Wheat" in daily_data["summary_by_crop"]
        assert daily_data["summary_by_crop"]["Wheat"]["total_volume_quintals"] > 0

        # Weekly timeframe
        res_weekly = await client.get("/api/v1/analytics/crop-trends?timeframe=weekly")
        assert res_weekly.status_code == 200
        assert len(res_weekly.json()["trends"]) > 0

        # Specific crop filter
        res_crop = await client.get("/api/v1/analytics/crop-trends?crop=Wheat")
        assert res_crop.status_code == 200
        assert all(t["crop_name"] == "Wheat" for t in res_crop.json()["trends"])


@pytest.mark.anyio
async def test_strategic_procurement_signals():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        today_str = datetime.now().strftime("%Y-%m-%d")
        res = await client.get(f"/api/v1/analytics/procurement-signals?centre_id=centre-khanna&date={today_str}")
        assert res.status_code == 200
        data = res.json()

        assert data["centre_id"] == "centre-khanna"
        assert len(data["signals"]) >= 6  # Major crops
        for sig in data["signals"]:
            assert sig["crop_name"] != ""
            assert sig["daily_target_quintals"] > 0
            assert sig["urgency_signal"] in ("HIGH_DEFICIT", "ON_TRACK", "BALANCED", "SURPLUS_CEILING")
            assert len(sig["procurement_recommendation"]) > 10


@pytest.mark.anyio
async def test_vendor_multi_crop_payment():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Farmer login and book
        farmer_login = await client.post("/api/v1/auth/login", json={"phone": "9876543210", "role": "farmer"})
        farmer_id = farmer_login.json()["user_id"]

        slots_res = await client.get("/api/v1/centres/centre-samrala/slots")
        slot_id = slots_res.json()[0]["id"]

        b_res = await client.post("/api/v1/bookings", json={
            "farmer_id": farmer_id,
            "centre_id": "centre-samrala",
            "slot_id": slot_id,
            "crops": [
                {"crop_name": "Cotton", "estimated_weight_quintals": 12.0, "msp_rate": 7121.0},
                {"crop_name": "Wheat", "estimated_weight_quintals": 18.0, "msp_rate": 2320.0},
            ]
        })
        assert b_res.status_code == 200
        b_id = b_res.json()["id"]
        b_code = b_res.json()["unique_booking_code"]

        # Farmer arrives
        arrive_res = await client.post("/api/v1/bookings/arrival-confirm", json={"booking_code": b_code})
        assert arrive_res.status_code == 200

        # Vendor submits payment with multi-crop itemized breakdown and proof
        pay_res = await client.post("/api/v1/vendor/payment/submit", json={
            "booking_id": b_id,
            "actual_weight_quintals": 30.5,
            "amount_paid": (12.2 * 7121.0) + (18.3 * 2320.0),
            "crops": [
                {"crop_name": "Cotton", "actual_weight_quintals": 12.2, "msp_rate": 7121.0},
                {"crop_name": "Wheat", "actual_weight_quintals": 18.3, "msp_rate": 2320.0},
            ],
            "payment_method": "dbt",
            "proof_type": "transaction_id",
            "proof_data": "SBIN009988776655",
            "proof_image": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
        })
        assert pay_res.status_code == 200
        assert pay_res.json()["status"] == "success"
        assert pay_res.json()["proof_data"] == "SBIN009988776655"