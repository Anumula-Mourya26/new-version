from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.db import init_db
from app.api.v1.auth import router as auth_router
from app.api.v1.farmers import router as farmers_router
from app.api.v1.centres import router as centres_router
from app.api.v1.bookings import router as bookings_router
from app.api.v1.gate import router as gate_router
from app.api.v1.queue import router as queue_router
from app.api.v1.procurement import router as procurement_router
from app.api.v1.payments import router as payments_router
from app.api.v1.district import router as district_router
from app.api.v1.analytics import router as analytics_router

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize DB schemas on startup
    await init_db()
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description='Live Gate & Queue Transparency Layer for MSP Procurement (SIH 2026 PS 26032)',
    lifespan=lifespan,
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

# Mount API v1 Routers
api_v1_prefix = '/api/v1'
app.include_router(auth_router, prefix=api_v1_prefix)
app.include_router(farmers_router, prefix=api_v1_prefix)
app.include_router(centres_router, prefix=api_v1_prefix)
app.include_router(bookings_router, prefix=api_v1_prefix)
app.include_router(gate_router, prefix=api_v1_prefix)
app.include_router(queue_router, prefix=api_v1_prefix)
app.include_router(procurement_router, prefix=api_v1_prefix)
app.include_router(payments_router, prefix=api_v1_prefix)
app.include_router(district_router, prefix=api_v1_prefix)
app.include_router(analytics_router, prefix=api_v1_prefix)


@app.get('/')
async def root():
    return {
        'app': settings.APP_NAME,
        'tagline': 'From slot booking to credited payout — live, honest MSP procurement',
        'version': settings.APP_VERSION,
        'status': 'online',
        'docs': '/docs',
    }


@app.get('/api/v1/health')
async def health_check():
    return {
        'status': 'healthy',
        'app': settings.APP_NAME,
        'version': settings.APP_VERSION,
        'environment': settings.APP_ENV,
    }
