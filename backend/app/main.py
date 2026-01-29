"""FastAPI application entry point."""
import logging
from contextlib import asynccontextmanager

from app.api import api_router
from app.api.internal import router as internal_router
from app.config import get_settings
from app.database import init_db
from app.services.progress_cache import close_redis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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

    yield

    # Shutdown
    logger.info('Shutting down...')
    await close_redis()
    logger.info('Redis connection closed')


# Create FastAPI app
app = FastAPI(
    title='WebQA Test Management API',
    description='API for managing test cases and executions',
    version='1.0.0',
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

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
