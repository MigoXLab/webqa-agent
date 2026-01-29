"""API routes."""
from app.api import (businesses, config, environments, executions, files,
                     test_cases)
from fastapi import APIRouter

api_router = APIRouter()

api_router.include_router(businesses.router, prefix='/businesses', tags=['businesses'])
api_router.include_router(environments.router, prefix='/environments', tags=['environments'])
api_router.include_router(test_cases.router, prefix='/cases', tags=['test_cases'])
api_router.include_router(executions.router, prefix='/executions', tags=['executions'])
api_router.include_router(config.router, prefix='/config', tags=['config'])
api_router.include_router(files.router, prefix='/files', tags=['files'])
