from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.db import get_db
from app.core.config import get_settings
from app.core.security import create_access_token
from app.models.entities import User
from app.schemas.schemas import FarmerSignupRequest, LoginRequest, TokenResponse

router = APIRouter(prefix='/auth', tags=['Authentication'])
settings = get_settings()


@router.post('/farmer/signup', response_model=TokenResponse)
async def farmer_signup(payload: FarmerSignupRequest, db: AsyncSession = Depends(get_db)):
    # Check if phone already registered
    existing_phone = (await db.execute(select(User).where(User.phone == payload.phone))).scalar_one_or_none()
    if existing_phone:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='Phone number already registered. Please log in.')

    # Check if aadhaar already registered
    existing_aadhaar = (await db.execute(select(User).where(User.aadhaar_number == payload.aadhaar_number))).scalar_one_or_none()
    if existing_aadhaar:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail='Aadhaar number already registered.')

    user = User(
        phone=payload.phone,
        role='farmer',
        full_name=payload.full_name,
        aadhaar_number=payload.aadhaar_number,
        alt_person_name=payload.alt_person_name,
        alt_person_aadhaar=payload.alt_person_aadhaar,
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
    clean_phone = payload.phone.strip()

    # Pre-existing Admin login check
    if payload.role == 'vendor' and clean_phone in ['123456890', '1234567890']:
        # Look up or create the pre-existing admin
        admin = (await db.execute(select(User).where(User.phone == clean_phone))).scalar_one_or_none()
        if not admin:
            admin = User(
                phone=clean_phone,
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

    # General user lookup
    user = (await db.execute(select(User).where(User.phone == clean_phone))).scalar_one_or_none()
    if not user:
        if payload.role == 'vendor':
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail='Vendor not registered. Vendors must be registered by the District Admin.'
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail='Farmer account not found. Please click Sign Up to register.'
            )

    # Verify role compatibility
    if payload.role == 'vendor' and user.role not in ['vendor', 'admin']:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail='Access denied. This phone number is not registered as a Mandi Vendor.'
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
