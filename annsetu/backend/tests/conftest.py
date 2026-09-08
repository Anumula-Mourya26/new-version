import os
import asyncio
import pytest

# Point tests to isolated test database BEFORE importing app modules
_TEST_DB_PATH = os.path.join(os.path.dirname(__file__), "test_annsetu.db").replace("\\", "/")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TEST_DB_PATH}"

from app.core.config import get_settings
get_settings.cache_clear()

from seed import seed


@pytest.fixture(scope='module', autouse=True)
def setup_database_per_module():
    asyncio.run(seed(force_reset=True))


@pytest.fixture(scope='session', autouse=True)
def cleanup_test_db():
    yield
    for ext in ["", "-wal", "-shm"]:
        p = _TEST_DB_PATH + ext
        if os.path.exists(p):
            try:
                os.remove(p)
            except Exception:
                pass


