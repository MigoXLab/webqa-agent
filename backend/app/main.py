"""FastAPI application entry point."""
import logging
import os
from contextlib import asynccontextmanager

from app.api import api_router
from app.api.internal import router as internal_router
from app.config import get_settings
from app.database import init_db
from app.middleware.api_key_auth import APIKeyAuthMiddleware
from app.services.job_monitor import job_monitor
from app.services.progress_cache import close_redis
from app.services.task_scheduler import task_scheduler
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger.info('Starting up...')
    await init_db()
    logger.info('Database initialized')

    # Start Job Monitor
    job_monitor.start()

    # Start Task Scheduler
    await task_scheduler.start()

    yield

    # Shutdown
    logger.info('Shutting down...')
    await job_monitor.stop()
    await task_scheduler.stop()
    await close_redis()
    logger.info('Redis connection closed')


# Create FastAPI app
app = FastAPI(
    title='WebQA Test Management API',
    description='API for managing test cases and executions',
    version='1.0.0',
    lifespan=lifespan,
)

app.add_middleware(APIKeyAuthMiddleware)

# Mount shared reports directory for local/opensource access
os.makedirs(settings.shared_reports_path, exist_ok=True)
app.mount('/reports', StaticFiles(directory=settings.shared_reports_path), name='reports')

# CORS is not needed because:
# - Production: Same-origin (frontend and backend under same domain via Nginx proxy)
# - Local dev: Vite dev server proxies /api requests to backend (see frontend/vite.config.ts)

# Include API routes
app.include_router(api_router, prefix='/api/v1')

# Include internal API routes (for Agent callback)
app.include_router(internal_router, prefix='/api/internal', tags=['internal'])


@app.get('/health')
async def health_check():
    """Health check endpoint."""
    return {'status': 'healthy'}


@app.get('/')
async def root():
    """Root endpoint."""
    return {
        'message': 'WebQA Test Management API',
        'docs': '/docs',
        'health': '/health',
    }
