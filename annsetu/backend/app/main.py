import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.core.config import get_settings
from app.core.db import init_db
from app.api.v1.auth import router as auth_router
from app.api.v1.centres import router as centres_router
from app.api.v1.bookings import router as bookings_router
from app.api.v1.vendor import router as vendor_router
from app.api.v1.admin import router as admin_router
from app.api.v1.queue import router as queue_router

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title='AnnSetu — KisanQueue Edition',
    version=settings.APP_VERSION,
    description='Mandi Queue Management, Real-Time ETA Engine & Transparent DBT Settlement',
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

# Mount Routers
api_v1 = '/api/v1'
app.include_router(auth_router, prefix=api_v1)
app.include_router(centres_router, prefix=api_v1)
app.include_router(bookings_router, prefix=api_v1)
app.include_router(vendor_router, prefix=api_v1)
app.include_router(admin_router, prefix=api_v1)
app.include_router(queue_router, prefix=api_v1)

static_dir = os.path.join(os.path.dirname(__file__), 'static')
if os.path.exists(static_dir):
    app.mount('/static', StaticFiles(directory=static_dir), name='static')


@app.get('/')
async def root():
    index_path = os.path.join(static_dir, 'index.html')
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {
        'app': 'AnnSetu',
        'status': 'online',
        'docs': '/docs',
    }


@app.get('/api/v1/health')
async def health_check():
    return {
        'status': 'healthy',
        'app': 'AnnSetu',
        'version': settings.APP_VERSION,
        'environment': settings.APP_ENV,
    }
