from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class FileResponse(BaseModel):
    """File information response."""
    id: str
    name: str
    size: int
    type: str
    uploaded_at: datetime
    url: str

class FileListResponse(BaseModel):
    """List of files response."""
    items: List[FileResponse]
    total: int
