import os
import shutil
import uuid
from datetime import datetime
from typing import List

from app.config import get_settings
from app.schemas.common import APIResponse
from app.schemas.file import FileListResponse, FileResponse
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse as FastAPIFileResponse

router = APIRouter()
settings = get_settings()

def get_files_dir(business_id: str) -> str:
    """Get the directory for business files."""
    base_dir = settings.effective_shared_storage_path
    files_dir = os.path.join(base_dir, 'files', business_id)
    os.makedirs(files_dir, exist_ok=True)
    return files_dir

@router.get('/{business_id}', response_model=APIResponse[FileListResponse])
async def list_files(business_id: str):
    """List all files for a business."""
    files_dir = get_files_dir(business_id)
    items = []

    if os.path.exists(files_dir):
        for filename in os.listdir(files_dir):
            file_path = os.path.join(files_dir, filename)
            if os.path.isfile(file_path):
                stats = os.stat(file_path)
                items.append(FileResponse(
                    id=filename,
                    name=filename,
                    size=stats.st_size,
                    type='application/octet-stream',
                    uploaded_at=datetime.fromtimestamp(stats.st_mtime),
                    url=f'/api/v1/files/{business_id}/{filename}/download'
                ))

    items.sort(key=lambda x: x.uploaded_at, reverse=True)

    return APIResponse(
        data=FileListResponse(
            items=items,
            total=len(items)
        )
    )

@router.get('/{business_id}/{filename}/download')
async def download_file(business_id: str, filename: str):
    """Download a file."""
    files_dir = get_files_dir(business_id)
    file_path = os.path.join(files_dir, filename)

    if os.path.exists(file_path):
        return FastAPIFileResponse(
            path=file_path,
            filename=filename,
            media_type='application/octet-stream'
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='File not found'
        )

@router.post('/{business_id}/upload', response_model=APIResponse[FileResponse])
async def upload_file(business_id: str, file: UploadFile = File(...)):
    """Upload a file for a business."""
    files_dir = get_files_dir(business_id)

    # Generate a unique filename if needed, but here we'll use the original filename
    # or prefix it to avoid collisions. For simplicity, we'll use original.
    file_path = os.path.join(files_dir, file.filename)

    try:
        with open(file_path, 'wb') as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f'Failed to save file: {str(e)}'
        )

    stats = os.stat(file_path)
    return APIResponse(
        data=FileResponse(
            id=file.filename,
            name=file.filename,
            size=stats.st_size,
            type=file.content_type or 'application/octet-stream',
            uploaded_at=datetime.fromtimestamp(stats.st_mtime),
            url=f'/api/v1/files/{business_id}/{file.filename}/download'
        )
    )

@router.delete('/{business_id}/{filename}', response_model=APIResponse[bool])
async def delete_file(business_id: str, filename: str):
    """Delete a file."""
    files_dir = get_files_dir(business_id)
    file_path = os.path.join(files_dir, filename)

    if os.path.exists(file_path):
        os.remove(file_path)
        return APIResponse(data=True)
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail='File not found'
        )
