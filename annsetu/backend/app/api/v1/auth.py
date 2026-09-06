from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.db import get_db
from app.core.config import get_settings
from app.core.security import create_access_token, verify_password
from app.models.entities import User
from app.schemas.schemas import OTPRequest, OTPVerify, TokenResponse, OfficerLoginRequest

router = APIRouter(prefix='/auth', tags=['Authentication'])
settings = get_settings()


@router.post('/otp/request')
async def request_otp(payload: OTPRequest):
    # In demo/dev mode, mock OTP 1234 is accepted
    return {
        'status': 'success',
        'message': f'OTP sent successfully to {payload.phone}',
        'mock_otp': settings.OTP_MOCK_CODE if settings.OTP_MOCK_ENABLED else None,
    }


@router.post('/otp/verify', response_model=TokenResponse)
async def verify_otp(payload: OTPVerify, db: AsyncSession = Depends(get_db)):
    if settings.OTP_MOCK_ENABLED and payload.otp != settings.OTP_MOCK_CODE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Invalid OTP')

    # Look up or auto-provision farmer user
    user = (await db.execute(select(User).where(User.phone == payload.phone))).scalar_one_or_none()
    if not user:
        user = User(
            phone=payload.phone,
            role='farmer',
            full_name=f'Farmer {payload.phone[-4:]}',
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

    token = create_access_token({'sub': user.id, 'role': user.role, 'phone': user.phone})
    return TokenResponse(
        access_token=token,
        role=user.role,
        user_id=user.id,
        phone=user.phone,
        full_name=user.full_name,
    )


@router.post('/officer/login', response_model=TokenResponse)
async def officer_login(payload: OfficerLoginRequest, db: AsyncSession = Depends(get_db)):
    user = (await db.execute(select(User).where(User.phone == payload.phone))).scalar_one_or_none()
    if not user or user.role not in ['operator', 'district_admin', 'system_admin']:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid credentials or unauthorized role')

    if user.password_hash and not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid credentials')

    token = create_access_token({'sub': user.id, 'role': user.role, 'phone': user.phone})
    return TokenResponse(
        access_token=token,
        role=user.role,
        user_id=user.id,
        phone=user.phone,
        full_name=user.full_name,
    )
