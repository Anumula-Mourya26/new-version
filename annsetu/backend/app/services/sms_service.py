import re
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("annsetu.sms")


def clean_indian_phone(phone: str) -> str:
    """
    Strips country code, spaces, and formatting to yield a 10-digit Indian phone string.
    Preserves special demo admin phone '123456890'.
    """
    if not phone:
        return ""
    cleaned = re.sub(r"[^\d]", "", phone.strip())
    if cleaned in ("123456890", "1234567890"):
        return cleaned
    if cleaned.startswith("91") and len(cleaned) == 12:
        return cleaned[2:]
    if cleaned.startswith("0") and len(cleaned) == 11:
        return cleaned[1:]
    return cleaned


def format_phone_e164(phone: str) -> str:
    """Format phone number with +91 prefix for display/compatibility."""
    if not phone:
        return ""
    if phone.startswith("+91"):
        return phone
    if phone.startswith("91") and len(phone) == 12:
        return f"+{phone}"
    if phone.startswith("+"):
        return phone
    cleaned = clean_indian_phone(phone)
    return f"+91{cleaned}" if cleaned else ""


def is_valid_indian_phone(phone: str) -> bool:
    """
    Validates if a phone number is a valid 10-digit Indian mobile number (starts with 6,7,8,9),
    or 9-digit test numbers / special pre-configured admin testing numbers.
    """
    cleaned = clean_indian_phone(phone)
    if cleaned in ("123456890", "1234567890"):
        return True
    return bool(re.match(r"^[6-9]\d{8,9}$", cleaned))


class SMSService:
    @classmethod
    async def send_sms_direct(cls, to_phone: str, message: str, **kwargs) -> Dict[str, Any]:
        """
        Base SMS dispatcher stub. Ready for a fresh SMS provider integration.
        Currently records mock SMS in development logs without external third-party calls.
        """
        cleaned_phone = clean_indian_phone(to_phone)
        if not cleaned_phone or not is_valid_indian_phone(cleaned_phone):
            return {
                "success": False,
                "status": "failed",
                "error": "Invalid phone number format. Must be a 10-digit Indian mobile number.",
                "recipient": to_phone,
            }

        logger.info(f"[SMS DISPATCH] To: {cleaned_phone} | Content: {message}")
        return {
            "success": True,
            "status": "mock_sent",
            "sid": f"SMS_MOCK_{cleaned_phone[-4:] if len(cleaned_phone) >= 4 else '0000'}",
            "recipient": cleaned_phone,
            "message": message,
        }

    @classmethod
    async def send_booking_confirmation(
        cls,
        to_phone: str,
        farmer_name: str,
        booking_code: str,
        mandi_name: str,
        slot_date: str,
        slot_time: str,
        crops_summary: str,
        total_weight: float,
    ) -> Dict[str, Any]:
        """
        Send booking confirmation SMS when a farmer books a slot.
        """
        msg = (
            f"AnnSetu Booking Confirmed! Code: #{booking_code}. "
            f"Farmer: {farmer_name}. Mandi: {mandi_name}. "
            f"Date: {slot_date}, Slot: {slot_time}. "
            f"Produce: {crops_summary} ({total_weight:.1f} Q). "
            f"Please carry your digital gate pass."
        )
        return await cls.send_sms_direct(to_phone=to_phone, message=msg)

    @classmethod
    async def send_admission_sms(
        cls,
        to_phone: str,
        farmer_name: str,
        booking_code: str,
        mandi_name: str,
        queue_position: int,
        eta_minutes: Optional[int],
    ) -> Dict[str, Any]:
        """
        Send queue admission SMS when a vendor admits the farmer into the queue.
        """
        eta_str = f"{eta_minutes} mins" if eta_minutes is not None else "Immediate"
        msg = (
            f"AnnSetu Gate Pass: Farmer {farmer_name}, you are admitted to queue at {mandi_name} "
            f"for pass #{booking_code}. Queue Pos: #{queue_position}. "
            f"Est wait: {eta_str}. Please proceed to weighing counter when called."
        )
        return await cls.send_sms_direct(to_phone=to_phone, message=msg)