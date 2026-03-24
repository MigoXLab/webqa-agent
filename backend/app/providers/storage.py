"""Storage provider interface and default implementation.

Provider implementations must expose:
- name: str - provider identifier
- upload_report(local_dir, key_prefix) -> str | None - upload report, return URL
"""
import logging
from typing import Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class StorageProvider(Protocol):
    """Protocol for report/artifact storage providers."""

    name: str

    def upload_report(self, local_dir: str, key_prefix: str) -> Optional[str]:
        """Upload a report directory to remote storage.

        Args:
            local_dir: Local directory path containing the report files
            key_prefix: Logical key prefix for organizing uploads
                (e.g. "20260323_143022_abc12345")

        Returns:
            Public URL of the main report HTML, or None if upload is skipped/failed.
        """
        ...


class LocalStorageProvider:
    """Default provider: reports stay on local filesystem.

    Reports are served through the backend's static file API.
    No remote upload is performed.
    """

    name = 'local'

    def upload_report(self, local_dir: str, key_prefix: str) -> Optional[str]:
        logger.debug(
            '[Storage:local] Skipping upload, report stays local: %s', local_dir
        )
        return None
