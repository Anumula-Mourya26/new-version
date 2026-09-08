from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.db import get_db
from app.core.security import create_access_token
from app.models.entities import User
from app.schemas.schemas import FarmerSignupRequest, LoginRequest, TokenResponse
from app.services.sms_service import clean_indian_phone, is_valid_indian_phone

router = APIRouter(prefix='/auth', tags=['Authentication'])


@router.post('/farmer/signup', response_model=TokenResponse)
async def farmer_signup(payload: FarmerSignupRequest, db: AsyncSession = Depends(get_db)):
    if not is_valid_indian_phone(payload.phone):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Indian mobile number. Please enter a valid 10-digit number."
        )

    clean_phone = clean_indian_phone(payload.phone)

    # Check if phone already registered
    existing_phone = (await db.execute(select(User).where(User.phone == clean_phone))).scalar_one_or_none()
    if existing_phone:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='Phone number already registered. Please log in.')

    # Check if aadhaar already registered
    existing_aadhaar = (await db.execute(select(User).where(User.aadhaar_number == payload.aadhaar_number))).scalar_one_or_none()
    if existing_aadhaar:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='Aadhaar number already registered.')

    if payload.pin != payload.confirm_pin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="PIN and Confirm PIN must match exactly."
        )

    user = User(
        phone=clean_phone,
        role='farmer',
        full_name=payload.full_name,
        aadhaar_number=payload.aadhaar_number,
        alt_person_name=payload.alt_person_name,
        alt_person_aadhaar=payload.alt_person_aadhaar,
        pin=payload.pin,
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


@router.post('/login', response_model=TokenResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    role = (payload.role or 'farmer').lower()

    if role == 'admin':
        # ponytail: hardcoded admin credentials for prototype (Admin ID: 123457890, Password: 123456789); replace with hashed credentials in auth store before production
        clean_admin_id = (payload.admin_id or payload.phone or '').replace(' ', '').replace('-', '').strip()
        clean_password = (payload.password or '').strip()
        if clean_admin_id != '123457890' or clean_password != '123456789':
            if clean_admin_id != '123457890' and clean_password == '123456789':
                detail = "Invalid Admin ID. Required Admin ID is 123457890."
            elif clean_admin_id == '123457890' and clean_password != '123456789':
                detail = "Invalid Admin Password. Required Admin Password is 123456789."
            else:
                detail = "Invalid admin credentials. Required: Admin ID (123457890) and Password (123456789)."
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=detail
            )
        admin = (await db.execute(select(User).where(User.role == 'admin'))).scalars().first()
        if not admin:
            admin = (await db.execute(select(User).where(User.phone == '123457890'))).scalars().first()
        if not admin:
            admin = User(
                phone='123457890',
                role='admin',
                full_name='District Mandi Administrator',
            )
            db.add(admin)
            await db.commit()
            await db.refresh(admin)

        token = create_access_token({'sub': admin.id, 'role': 'admin', 'phone': admin.phone})
        return TokenResponse(
            access_token=token,
            role='admin',
            user_id=admin.id,
            phone=admin.phone,
            full_name=admin.full_name,
        )

    # Phone is required for vendor and farmer
    if not payload.phone or not is_valid_indian_phone(payload.phone):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Indian mobile number. Please enter a valid 10-digit number."
        )

    clean_phone = clean_indian_phone(payload.phone)

    if role == 'vendor':
        user = (await db.execute(select(User).where(User.phone == clean_phone))).scalar_one_or_none()
        if not user or user.role not in ['vendor', 'admin']:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail='Vendor not registered. Vendors must be registered by the District Admin.'
            )

        # 4-digit PIN authentication (completely replaces legacy phone-number-as-password login logic)
        submitted_pin = (payload.pin or payload.password or '').strip()
        expected_pin = user.pin or '1234'
        if not submitted_pin or submitted_pin != expected_pin:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail='Invalid 4-digit PIN. Please enter your valid PIN.'
            )

        token = create_access_token({'sub': user.id, 'role': user.role, 'phone': user.phone})
        return TokenResponse(
            access_token=token,
            role=user.role,
            user_id=user.id,
            phone=user.phone,
            full_name=user.full_name,
            centre_id=user.centre_id,
        )

    if role == 'farmer':
        user = (await db.execute(select(User).where(User.phone == clean_phone))).scalar_one_or_none()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail='Farmer account not found. Please click Sign Up to register.'
            )

        # 4-digit PIN gates farmer login alongside phone identification
        submitted_pin = (payload.pin or payload.password or '').strip()
        expected_pin = user.pin or '1234'
        if not submitted_pin or submitted_pin != expected_pin:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail='Invalid 4-digit PIN. Please enter your valid PIN.'
            )

        token = create_access_token({'sub': user.id, 'role': user.role, 'phone': user.phone})
        return TokenResponse(
            access_token=token,
            role=user.role,
            user_id=user.id,
            phone=user.phone,
            full_name=user.full_name,
            centre_id=user.centre_id,
        )

    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Invalid role specified.')
