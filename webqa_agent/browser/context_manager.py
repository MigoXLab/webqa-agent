"""Persistent BrowserContext Management

This module provides utilities for persisting Playwright BrowserContext state
to local filesystem using storage_state API.

Key Features:
- Storage state persistence (cookies, localStorage, sessionStorage)
- File-based state management with atomic writes
- Thread-safe operations with file locking
- Cross-session state reuse
"""

import json
import logging
from pathlib import Path
from typing import Optional

from playwright.async_api import BrowserContext

try:
    import filelock
    HAS_FILELOCK = True
except ImportError:
    HAS_FILELOCK = False
    logging.warning(
        "filelock not installed. Concurrent context saves may have race conditions. "
        "Install with: pip install filelock"
    )


class PersistentContextManager:
    """Persistent context manager (stateless utility class).

    Manages storage_state files for Playwright BrowserContext persistence.
    All methods are static for simplicity and thread-safety.
    """

    @staticmethod
    def get_storage_path(
        snapshot_id: str,
        base_dir: str = 'webqa_agent/browser/browser_context'
    ) -> Path:
        """Calculate storage_state JSON file path.

        Args:
            snapshot_id: Unique identifier for the snapshot
            base_dir: Base directory for storage (default: webqa_agent/browser/browser_context)

        Returns:
            Path object: {base_dir}/{snapshot_id}.json

        Raises:
            ValueError: If snapshot_id contains invalid characters (path traversal attempt)
        """
        # Security: Prevent path traversal attacks
        if not snapshot_id or '/' in snapshot_id or '\\' in snapshot_id or '..' in snapshot_id:
            raise ValueError(
                f"Invalid snapshot_id: '{snapshot_id}'. "
                "Must not contain path separators or '..' for security."
            )

        # Convert to Path object (no directory creation side effect)
        base_path = Path(base_dir)
        storage_path = base_path / f'{snapshot_id}.json'
        return storage_path

    @staticmethod
    async def get_storage_state_path(
        snapshot_id: str,
        base_dir: str = 'webqa_agent/browser/browser_context'
    ) -> Optional[str]:
        """Get storage_state file path if it exists and is valid.

        Args:
            snapshot_id: Unique identifier for the snapshot
            base_dir: Base directory for storage

        Returns:
            str: File path if exists and valid, None otherwise
        """
        try:
            storage_path = PersistentContextManager.get_storage_path(snapshot_id, base_dir)

            # Check if file exists
            if not storage_path.exists():
                logging.debug(f"[PersistentContext] No saved state found for snapshot_id: {snapshot_id}")
                return None

            # Validate JSON format
            try:
                with open(storage_path, 'r', encoding='utf-8') as f:
                    json.load(f)  # Validate JSON
            except json.JSONDecodeError as e:
                logging.warning(
                    f"[PersistentContext] Corrupted storage_state file for {snapshot_id}: {e}. "
                    "Will create new context."
                )
                return None

            logging.info(f"[PersistentContext] Found saved state for snapshot_id: {snapshot_id}")
            return str(storage_path)

        except Exception as e:
            logging.error(f"[PersistentContext] Failed to get storage_state path for {snapshot_id}: {e}")
            return None

    @staticmethod
    async def save_storage_state(
        context: BrowserContext,
        snapshot_id: str,
        base_dir: str = 'webqa_agent/browser/browser_context'
    ) -> None:
        """Save context storage_state to file with atomic write and file locking.

        Args:
            context: Playwright BrowserContext to save
            snapshot_id: Unique identifier for the snapshot
            base_dir: Base directory for storage

        Raises:
            Exception: If save operation fails
        """
        storage_path = PersistentContextManager.get_storage_path(snapshot_id, base_dir)
        tmp_path = storage_path.with_suffix('.json.tmp')

        try:
            # Ensure directory exists before writing
            storage_path.parent.mkdir(parents=True, exist_ok=True)

            # Step 1: Write to temporary file
            await context.storage_state(path=str(tmp_path))

            # Step 2: Atomic rename with file lock (if available)
            if HAS_FILELOCK:
                lock_path = storage_path.with_suffix('.lock')
                lock = filelock.FileLock(str(lock_path), timeout=10)

                try:
                    with lock:
                        tmp_path.replace(storage_path)  # Atomic operation: rename tmp -> final
                    try:
                        lock_path.unlink(missing_ok=True)  # Cleanup lock file
                    except OSError:
                        pass  # Lock file cleanup is best-effort

                except filelock.Timeout:
                    logging.warning(
                        f"[PersistentContext] Lock timeout while saving {snapshot_id}. "
                        "Proceeding without lock."
                    )
                    # Fallback: rename without lock
                    tmp_path.replace(storage_path)
            else:
                # No filelock available: direct rename (not fully atomic in concurrent scenarios)
                tmp_path.replace(storage_path)

            logging.info(f"[PersistentContext] Saved storage_state for snapshot_id: {snapshot_id}")

        except Exception as e:
            logging.error(f"[PersistentContext] Failed to save storage_state for {snapshot_id}: {e}")
            try:
                if tmp_path.exists():
                    tmp_path.unlink()  # Cleanup temporary file on failure
            except OSError:
                pass
            raise

    @staticmethod
    def delete_storage_state(
        snapshot_id: str,
        base_dir: str = 'webqa_agent/browser/browser_context'
    ) -> bool:
        """Delete storage_state file for specified snapshot_id.

        Args:
            snapshot_id: Unique identifier for the snapshot
            base_dir: Base directory for storage

        Returns:
            bool: True if deleted successfully, False if file not found or error
        """
        try:
            storage_path = PersistentContextManager.get_storage_path(snapshot_id, base_dir)

            if storage_path.exists():
                storage_path.unlink()
                logging.info(f"[PersistentContext] Cleaned up snapshot_id: {snapshot_id}")
                return True
            else:
                logging.debug(f"[PersistentContext] No file to cleanup for snapshot_id: {snapshot_id}")
                return False

        except Exception as e:
            logging.error(f"[PersistentContext] Failed to cleanup snapshot_id {snapshot_id}: {e}")
            return False
