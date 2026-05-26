"""Test file library for intelligent file upload in Gen mode.

Scans a user-configured directory for test files (PDF, images, documents, etc.),
builds a categorized index, and generates an LLM-readable catalog so the AI agent
can select appropriate files for upload testing.

Architecture:
- Used by GenExecutor to provide file context to the LLM agent
- TestFileLibrary is initialized with a directory path from GenConfig
- The catalog string is injected into LangGraph state for prompt enrichment
- File path validation ensures uploads stay within the configured directory

Security:
- All paths are resolved with os.path.realpath() to prevent symlink escapes
- Path traversal attacks (../../) are blocked by containment checks
- Only files within the configured directory tree are accessible

Example:
    library = TestFileLibrary("/path/to/test_files")
    catalog = library.get_catalog_for_llm()
    # => "Available test files for upload ...\\n- /path/to/test_files/resume.pdf ..."

    library.validate_file_path("/path/to/test_files/resume.pdf")  # True
    library.validate_file_path("/etc/passwd")  # False
"""

import logging
import mimetypes
import os
from dataclasses import dataclass
from itertools import cycle
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# --- Constants ---

MAX_CATALOG_FILES: int = 30
"""Maximum number of files to include in the LLM catalog."""

MAX_FILE_SIZE_BYTES: int = 50 * 1024 * 1024
"""Skip files larger than 50 MB during scanning."""

# --- Custom MIME type supplements ---
# The stdlib mimetypes module may miss newer or Office XML formats.

_EXTRA_MIME_TYPES: Dict[str, str] = {
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    '.webp': 'image/webp',
    '.avif': 'image/avif',
    '.md': 'text/markdown',
    '.yaml': 'text/yaml',
    '.yml': 'text/yaml',
}

# --- Category mapping (prefix-based) ---

_CATEGORY_PREFIXES: Dict[str, List[str]] = {
    'image': ['image/'],
    'video': ['video/'],
    'audio': ['audio/'],
    'document': [
        'application/pdf',
        'application/msword',
        'application/vnd.openxmlformats',
        'text/',
    ],
}


def _classify_category(mime_type: str) -> str:
    """Classify a MIME type into a high-level category.

    Args:
        mime_type: The MIME type string (e.g. "image/jpeg").

    Returns:
        One of "image", "video", "audio", "document", or "other".
    """
    for category, prefixes in _CATEGORY_PREFIXES.items():
        for prefix in prefixes:
            if mime_type.startswith(prefix):
                return category
    return 'other'


def _format_size(size_bytes: int) -> str:
    """Format byte count as a human-readable string (KB/MB).

    Args:
        size_bytes: File size in bytes.

    Returns:
        Formatted string like "125KB" or "3.2MB".
    """
    if size_bytes >= 1024 * 1024:
        return f'{size_bytes / (1024 * 1024):.1f}MB'
    return f'{size_bytes // 1024}KB'


# --- Data classes ---


@dataclass
class FileEntry:
    """Metadata for a single test file.

    Attributes:
        name: Filename without directory (e.g. "resume.pdf").
        path: Absolute filesystem path.
        extension: Lowercase extension with dot (e.g. ".pdf").
        mime_type: Detected MIME type (e.g. "application/pdf").
        size_bytes: File size in bytes.
        category: High-level category: document / image / video / audio / other.
    """

    name: str
    path: str
    extension: str
    mime_type: str
    size_bytes: int
    category: str


# --- Main library ---


class TestFileLibrary:
    """Scans a directory for test files and produces an LLM-readable catalog.

    The library resolves the directory to its real path (no symlinks) on init,
    recursively walks the tree, and indexes every readable file under the size
    limit.  The resulting catalog string can be injected into LLM prompts so
    the agent knows which files are available for upload testing.

    Attributes:
        files: List of FileEntry objects for all discovered files.
    """

    # Prevent pytest from collecting this as a test class
    __test__ = False

    def __init__(self, directory: str, file_whitelist: Optional[List[str]] = None) -> None:
        """Initialize the library and scan the directory.

        Args:
            directory: Path to the test-files directory.  Resolved to its
                real path (symlinks dereferenced) for security.
            file_whitelist: Optional list of filenames to include.
                When provided, only files whose name matches an entry
                in this list are indexed.  When None, all files are indexed.
        """
        self._directory: str = os.path.realpath(directory)
        self._file_whitelist: Optional[frozenset] = (
            frozenset(file_whitelist) if file_whitelist is not None else None
        )
        self.files: List[FileEntry] = []
        self._scan()

    # --- Scanning ---

    def _scan(self) -> None:
        """Recursively walk the directory and build the file index.

        Behaviour:
        - Follows no symlinks (followlinks=False).
        - Skips entries that are not regular files.
        - Catches PermissionError so unreadable files are silently skipped.
        - Skips files exceeding MAX_FILE_SIZE_BYTES.
        - Uses the stdlib mimetypes module + _EXTRA_MIME_TYPES for detection.
        """
        if not os.path.isdir(self._directory):
            logger.warning('Test file directory does not exist: %s', self._directory)
            return

        for dirpath, _dirnames, filenames in os.walk(
            self._directory, followlinks=False
        ):
            for filename in filenames:
                # Apply file whitelist filter
                if self._file_whitelist is not None and filename not in self._file_whitelist:
                    continue

                filepath = os.path.join(dirpath, filename)

                # Skip non-regular files (devices, sockets, etc.)
                try:
                    stat_result = os.stat(filepath, follow_symlinks=False)
                except (OSError, PermissionError):
                    logger.debug('Cannot stat file, skipping: %s', filepath)
                    continue

                # Skip symlinks (followlinks=False only prevents directory symlinks)
                if os.path.islink(filepath):
                    logger.debug('TestFileLibrary: skipping symlink: %s', filepath)
                    continue

                if not os.path.isfile(filepath):
                    continue

                # Skip files exceeding size limit
                size = stat_result.st_size
                if size > MAX_FILE_SIZE_BYTES:
                    logger.debug(
                        'Skipping oversized file (%s): %s',
                        _format_size(size),
                        filepath,
                    )
                    continue

                # Check readability
                try:
                    with open(filepath, 'rb'):
                        pass
                except PermissionError:
                    logger.debug('Permission denied, skipping: %s', filepath)
                    continue
                except OSError as exc:
                    logger.debug('Cannot read file (%s), skipping: %s', exc, filepath)
                    continue

                # Detect MIME type
                extension = os.path.splitext(filename)[1].lower()
                mime_type = _EXTRA_MIME_TYPES.get(extension)
                if mime_type is None:
                    mime_type = mimetypes.guess_type(filename)[0] or 'application/octet-stream'

                category = _classify_category(mime_type)

                self.files.append(
                    FileEntry(
                        name=filename,
                        path=os.path.realpath(filepath),
                        extension=extension,
                        mime_type=mime_type,
                        size_bytes=size,
                        category=category,
                    )
                )

        logger.info(
            'TestFileLibrary scanned %d files in %s',
            len(self.files),
            self._directory,
        )

    # --- Catalog generation ---

    def get_catalog_for_llm(self) -> str:
        """Generate a compact, LLM-readable catalog of available test files.

        Returns:
            Multi-line string listing files with full paths, MIME types, and
            sizes.  Returns an empty string when no files are available.

        The catalog is truncated at MAX_CATALOG_FILES entries.  When
        truncation is needed, a category-diverse round-robin selection is
        used so every represented category gets fair coverage.
        """
        if not self.files:
            return ''

        selected = self._select_catalog_entries()
        truncated = len(self.files) > MAX_CATALOG_FILES

        lines: List[str] = [
            'Available test files for upload (use each FULL path as the file path '
            'for your upload API, e.g. `filePath` in MCP `upload_file` or the '
            'Upload action `value` in UI automation):',
        ]
        for entry in selected:
            size_str = _format_size(entry.size_bytes)
            lines.append(f'- {entry.path} ({entry.mime_type}, {size_str})')

        if truncated:
            remaining = len(self.files) - len(selected)
            lines.append(f'\n... and {remaining} more files (truncated).')

        lines.append(
            '\nIMPORTANT: Use the exact full path string above; pass it as '
            'the file path argument (e.g. `filePath` for `upload_file` in '
            'browser MCP, or `value` for the Upload action in UI automation).'
        )

        return '\n'.join(lines)

    def _select_catalog_entries(self) -> List[FileEntry]:
        """Select up to MAX_CATALOG_FILES entries with category diversity.

        Uses round-robin across categories so that no single category
        dominates the catalog when truncation is needed.

        Returns:
            List of FileEntry, at most MAX_CATALOG_FILES items.
        """
        if len(self.files) <= MAX_CATALOG_FILES:
            return list(self.files)

        # Group files by category
        by_category: Dict[str, List[FileEntry]] = {}
        for entry in self.files:
            by_category.setdefault(entry.category, []).append(entry)

        # Round-robin across categories
        selected: List[FileEntry] = []
        category_iters = {
            cat: iter(entries) for cat, entries in by_category.items()
        }
        categories = cycle(sorted(category_iters.keys()))
        exhausted: set[str] = set()

        while len(selected) < MAX_CATALOG_FILES and len(exhausted) < len(
            category_iters
        ):
            cat = next(categories)
            if cat in exhausted:
                continue
            try:
                entry = next(category_iters[cat])
                selected.append(entry)
            except StopIteration:
                exhausted.add(cat)

        return selected

    # --- Path validation ---

    def validate_file_path(self, file_path: str) -> bool:
        """Check that a file path is safely inside the configured directory.

        Resolves the candidate path with os.path.realpath() to defeat
        symlink escapes and ``../`` traversal before checking containment.

        Args:
            file_path: The path to validate (may be relative or absolute).

        Returns:
            True if the resolved path starts with the configured directory
            followed by os.sep. The directory itself is rejected (not a file).
            False otherwise.

        Note:
            This validates directory containment only, not catalog membership.
            Files excluded during scan (e.g., oversized) but within the directory
            will still pass validation.
        """
        if not file_path:
            return False

        real_path = os.path.realpath(file_path)
        # Must be strictly inside the directory (directory itself is not a valid file)
        return real_path.startswith(self._directory + os.sep)
