"""Unit tests for TestFileLibrary.

Tests file scanning, catalog generation, and path validation for the
intelligent file upload feature. Uses tmp_path fixture for isolated filesystem
testing.
"""

import os
import platform

import pytest

from webqa_agent.config_models.base_config import LLMConfig
from webqa_agent.config_models.gen_config import GenConfig
from webqa_agent.utils.test_file_library import (MAX_CATALOG_FILES,
                                                 TestFileLibrary)


@pytest.fixture
def file_library_dir(tmp_path):
    """Create a test directory with various file types.

    Structure:
        tmp_path/
            resume.pdf          (fake PDF with magic bytes)
            data.csv            (CSV text)
            notes.txt           (plain text)
            images/
                photo.jpg       (JPEG magic bytes)
                logo.png        (PNG magic bytes)
            huge_video.mp4      (51MB, should be excluded)
            locked.pdf          (no read permission, Unix only)
    """
    # resume.pdf - fake PDF with magic bytes
    pdf_file = tmp_path / 'resume.pdf'
    pdf_file.write_bytes(b'%PDF-1.4 fake pdf content')

    # data.csv
    csv_file = tmp_path / 'data.csv'
    csv_file.write_text('name,age\nAlice,30\nBob,25\n')

    # notes.txt
    txt_file = tmp_path / 'notes.txt'
    txt_file.write_text('Some test notes for QA.')

    # images subdirectory
    images_dir = tmp_path / 'images'
    images_dir.mkdir()

    # photo.jpg - JPEG magic bytes (SOI marker)
    jpg_file = images_dir / 'photo.jpg'
    jpg_file.write_bytes(b'\xff\xd8\xff\xe0' + b'\x00' * 100)

    # logo.png - PNG magic bytes
    png_file = images_dir / 'logo.png'
    png_file.write_bytes(b'\x89PNG\r\n\x1a\n' + b'\x00' * 100)

    # huge_video.mp4 - exceeds MAX_FILE_SIZE_BYTES (51MB)
    huge_file = tmp_path / 'huge_video.mp4'
    huge_file.write_bytes(b'\x00' * (51 * 1024 * 1024))

    # locked.pdf - no read permission (skip on Windows)
    if platform.system() != 'Windows':
        locked_file = tmp_path / 'locked.pdf'
        locked_file.write_bytes(b'%PDF-1.4 locked')
        locked_file.chmod(0o000)

    return tmp_path


class TestFileLibraryScan:
    """Test file scanning and indexing."""

    def test_scan_finds_valid_files(self, file_library_dir):
        """Scan should discover all readable files under size limit."""
        lib = TestFileLibrary(str(file_library_dir))
        names = {entry.name for entry in lib.files}
        assert 'resume.pdf' in names
        assert 'data.csv' in names
        assert 'notes.txt' in names
        assert 'photo.jpg' in names
        assert 'logo.png' in names

    def test_scan_extracts_mime_types(self, file_library_dir):
        """Scan should detect correct MIME types for known extensions."""
        lib = TestFileLibrary(str(file_library_dir))
        mime_map = {entry.name: entry.mime_type for entry in lib.files}
        assert mime_map['resume.pdf'] == 'application/pdf'
        assert mime_map['photo.jpg'] == 'image/jpeg'
        assert mime_map['logo.png'] == 'image/png'
        # CSV may be text/csv or application/csv depending on platform
        assert 'csv' in mime_map['data.csv'].lower()
        assert mime_map['notes.txt'] == 'text/plain'

    def test_scan_assigns_categories(self, file_library_dir):
        """Scan should assign correct categories based on MIME type."""
        lib = TestFileLibrary(str(file_library_dir))
        cat_map = {entry.name: entry.category for entry in lib.files}
        assert cat_map['resume.pdf'] == 'document'
        assert cat_map['photo.jpg'] == 'image'
        assert cat_map['logo.png'] == 'image'
        assert cat_map['notes.txt'] == 'document'
        assert cat_map['data.csv'] == 'document'

    def test_scan_skips_large_files(self, file_library_dir):
        """Files exceeding MAX_FILE_SIZE_BYTES should be excluded."""
        lib = TestFileLibrary(str(file_library_dir))
        names = {entry.name for entry in lib.files}
        assert 'huge_video.mp4' not in names

    @pytest.mark.skipif(
        platform.system() == 'Windows',
        reason='File permission tests not reliable on Windows',
    )
    def test_scan_skips_unreadable_files(self, file_library_dir):
        """Files without read permission should be skipped gracefully."""
        lib = TestFileLibrary(str(file_library_dir))
        names = {entry.name for entry in lib.files}
        assert 'locked.pdf' not in names

    def test_scan_skips_symlinked_files(self, tmp_path):
        """Symlinked files should not be indexed (prevents external path
        leakage)."""
        test_files_dir = tmp_path / 'test_files'
        test_files_dir.mkdir()
        (test_files_dir / 'real.txt').write_text('real content')
        symlink = test_files_dir / 'link_to_external.txt'
        try:
            symlink.symlink_to('/etc/hosts')
            library = TestFileLibrary(str(test_files_dir))
            names = [f.name for f in library.files]
            assert 'link_to_external.txt' not in names
        except OSError:
            pytest.skip('Cannot create symlinks on this OS')

    def test_scan_handles_nonexistent_directory(self, tmp_path):
        """Non-existent directory should result in empty file list."""
        nonexistent = str(tmp_path / 'does_not_exist')
        lib = TestFileLibrary(nonexistent)
        assert lib.files == []

    def test_scan_handles_empty_directory(self, tmp_path):
        """Empty directory should result in empty file list."""
        empty_dir = tmp_path / 'empty'
        empty_dir.mkdir()
        lib = TestFileLibrary(str(empty_dir))
        assert lib.files == []

    def test_scan_stores_absolute_paths(self, file_library_dir):
        """All file paths should be absolute."""
        lib = TestFileLibrary(str(file_library_dir))
        for entry in lib.files:
            assert os.path.isabs(entry.path)

    def test_scan_stores_correct_extensions(self, file_library_dir):
        """Extensions should be lowercase with leading dot."""
        lib = TestFileLibrary(str(file_library_dir))
        ext_map = {entry.name: entry.extension for entry in lib.files}
        assert ext_map['resume.pdf'] == '.pdf'
        assert ext_map['photo.jpg'] == '.jpg'
        assert ext_map['data.csv'] == '.csv'

    def test_scan_stores_file_sizes(self, file_library_dir):
        """File sizes should be positive integers."""
        lib = TestFileLibrary(str(file_library_dir))
        for entry in lib.files:
            assert entry.size_bytes > 0


class TestFileLibraryCatalog:
    """Test LLM-readable catalog generation."""

    def test_catalog_contains_file_info(self, file_library_dir):
        """Catalog should contain file paths, MIME types, and sizes."""
        lib = TestFileLibrary(str(file_library_dir))
        catalog = lib.get_catalog_for_llm()

        assert catalog  # non-empty
        assert 'resume.pdf' in catalog
        assert 'application/pdf' in catalog
        # Should contain absolute path
        assert str(file_library_dir) in catalog

    def test_catalog_contains_full_paths(self, file_library_dir):
        """Catalog entries should show full absolute paths."""
        lib = TestFileLibrary(str(file_library_dir))
        catalog = lib.get_catalog_for_llm()

        # Check that at least one entry has a full absolute path
        for entry in lib.files:
            assert entry.path in catalog

    def test_catalog_contains_usage_instructions(self, file_library_dir):
        """Catalog should contain LLM usage instructions."""
        lib = TestFileLibrary(str(file_library_dir))
        catalog = lib.get_catalog_for_llm()

        assert 'IMPORTANT' in catalog
        assert 'full path' in catalog.lower() or 'FULL path' in catalog

    def test_empty_library_returns_empty_string(self, tmp_path):
        """Empty library should return empty catalog string."""
        empty_dir = tmp_path / 'empty'
        empty_dir.mkdir()
        lib = TestFileLibrary(str(empty_dir))
        catalog = lib.get_catalog_for_llm()
        assert catalog == ''

    def test_catalog_truncation_with_many_files(self, tmp_path):
        """Catalog should truncate at MAX_CATALOG_FILES entries."""
        # Create more than MAX_CATALOG_FILES files
        many_dir = tmp_path / 'many_files'
        many_dir.mkdir()
        num_files = MAX_CATALOG_FILES + 10
        for i in range(num_files):
            f = many_dir / f'file_{i:03d}.txt'
            f.write_text(f'content {i}')

        lib = TestFileLibrary(str(many_dir))
        catalog = lib.get_catalog_for_llm()

        # Count catalog entries (lines starting with "- /")
        entry_lines = [
            line for line in catalog.splitlines() if line.strip().startswith('- /')
        ]
        assert len(entry_lines) <= MAX_CATALOG_FILES

        # Should indicate truncation
        assert 'more' in catalog.lower() or 'truncated' in catalog.lower()

    def test_catalog_truncation_preserves_category_diversity(self, tmp_path):
        """When truncating, catalog should include files from diverse
        categories."""
        diverse_dir = tmp_path / 'diverse'
        diverse_dir.mkdir()

        # Create files across categories
        for i in range(20):
            (diverse_dir / f'doc_{i}.pdf').write_bytes(b'%PDF-1.4 fake')
        for i in range(20):
            (diverse_dir / f'img_{i}.jpg').write_bytes(
                b'\xff\xd8\xff\xe0' + b'\x00' * 10
            )

        lib = TestFileLibrary(str(diverse_dir))
        catalog = lib.get_catalog_for_llm()

        # Both categories should be represented
        assert '.pdf' in catalog
        assert '.jpg' in catalog


class TestFileLibraryPathValidation:
    """Test security-critical path validation."""

    def test_valid_path_inside_directory(self, file_library_dir):
        """Files inside the configured directory should be valid."""
        lib = TestFileLibrary(str(file_library_dir))
        pdf_path = str(file_library_dir / 'resume.pdf')
        assert lib.validate_file_path(pdf_path) is True

    def test_valid_path_in_subdirectory(self, file_library_dir):
        """Files in subdirectories should be valid."""
        lib = TestFileLibrary(str(file_library_dir))
        jpg_path = str(file_library_dir / 'images' / 'photo.jpg')
        assert lib.validate_file_path(jpg_path) is True

    def test_invalid_path_outside_directory(self, file_library_dir):
        """Files outside the configured directory should be rejected."""
        lib = TestFileLibrary(str(file_library_dir))
        outside_path = '/etc/passwd'
        assert lib.validate_file_path(outside_path) is False

    def test_path_traversal_attack(self, file_library_dir):
        """Path traversal attempts (../../) should be rejected."""
        lib = TestFileLibrary(str(file_library_dir))
        traversal_path = str(file_library_dir / '..' / '..' / 'etc' / 'passwd')
        assert lib.validate_file_path(traversal_path) is False

    @pytest.mark.skipif(
        platform.system() == 'Windows',
        reason='Symlink tests may require elevated privileges on Windows',
    )
    def test_symlink_escape(self, file_library_dir, tmp_path):
        """Symlinks that escape the directory should be rejected."""
        # Create a file truly outside the library directory.
        # file_library_dir IS tmp_path, so we create a sibling directory.
        outside_dir = tmp_path.parent / 'outside_dir'
        outside_dir.mkdir(exist_ok=True)
        outside_file = outside_dir / 'outside_secret.txt'
        outside_file.write_text('secret data')

        # Create a symlink inside the library pointing outside
        symlink = file_library_dir / 'sneaky_link.txt'
        symlink.symlink_to(outside_file)

        lib = TestFileLibrary(str(file_library_dir))
        # The symlink's real path is outside the directory
        assert lib.validate_file_path(str(symlink)) is False

    def test_empty_path(self, file_library_dir):
        """Empty path string should be rejected."""
        lib = TestFileLibrary(str(file_library_dir))
        assert lib.validate_file_path('') is False

    def test_directory_itself_is_not_valid_file(self, file_library_dir):
        """The directory path itself is not a valid upload file."""
        lib = TestFileLibrary(str(file_library_dir))
        assert lib.validate_file_path(str(file_library_dir)) is False


class TestFileWhitelist:
    """Test file_whitelist filtering behavior."""

    def test_whitelist_filters_to_matching_files(self, file_library_dir):
        """Only files in the whitelist should be indexed."""
        lib = TestFileLibrary(str(file_library_dir), file_whitelist=['resume.pdf', 'data.csv'])
        names = {entry.name for entry in lib.files}
        assert names == {'resume.pdf', 'data.csv'}

    def test_whitelist_none_indexes_all(self, file_library_dir):
        """None whitelist should index all valid files (default behavior)."""
        lib = TestFileLibrary(str(file_library_dir), file_whitelist=None)
        names = {entry.name for entry in lib.files}
        assert 'resume.pdf' in names
        assert 'photo.jpg' in names
        assert len(names) >= 5  # resume.pdf, data.csv, notes.txt, photo.jpg, logo.png

    def test_whitelist_empty_list_indexes_nothing(self, file_library_dir):
        """Empty whitelist should index zero files."""
        lib = TestFileLibrary(str(file_library_dir), file_whitelist=[])
        assert lib.files == []

    def test_whitelist_nonexistent_file_yields_empty(self, file_library_dir):
        """Whitelist with names that don't exist on disk should yield
        nothing."""
        lib = TestFileLibrary(str(file_library_dir), file_whitelist=['nonexistent.pdf'])
        assert lib.files == []

    def test_whitelist_partial_match(self, file_library_dir):
        """Whitelist with mix of existing and non-existing files."""
        lib = TestFileLibrary(
            str(file_library_dir),
            file_whitelist=['resume.pdf', 'nonexistent.doc'],
        )
        names = {entry.name for entry in lib.files}
        assert names == {'resume.pdf'}

    def test_whitelist_includes_subdirectory_files(self, file_library_dir):
        """Whitelist should match files in subdirectories too."""
        lib = TestFileLibrary(str(file_library_dir), file_whitelist=['photo.jpg'])
        names = {entry.name for entry in lib.files}
        assert names == {'photo.jpg'}

    def test_whitelist_catalog_only_shows_whitelisted(self, file_library_dir):
        """Catalog should only contain whitelisted files."""
        lib = TestFileLibrary(str(file_library_dir), file_whitelist=['resume.pdf'])
        catalog = lib.get_catalog_for_llm()
        assert 'resume.pdf' in catalog
        assert 'data.csv' not in catalog
        assert 'photo.jpg' not in catalog


class TestGenConfigTestFilesDir:
    """Tests for test_files_dir field in GenConfig."""

    def test_default_is_none(self):
        config = GenConfig(
            target_url='https://example.com',
            llm_config=LLMConfig(model='gpt-4o', api_key='test-key'),
        )
        assert config.test_files_dir is None

    def test_valid_directory(self, tmp_path):
        config = GenConfig(
            target_url='https://example.com',
            llm_config=LLMConfig(model='gpt-4o', api_key='test-key'),
            test_files_dir=str(tmp_path),
        )
        assert config.test_files_dir == str(tmp_path)

    def test_nonexistent_directory_becomes_none(self):
        config = GenConfig(
            target_url='https://example.com',
            llm_config=LLMConfig(model='gpt-4o', api_key='test-key'),
            test_files_dir='/nonexistent/path/xyz',
        )
        assert config.test_files_dir is None

    def test_test_files_default_is_none(self):
        config = GenConfig(
            target_url='https://example.com',
            llm_config=LLMConfig(model='gpt-4o', api_key='test-key'),
        )
        assert config.test_files is None

    def test_test_files_with_list(self):
        config = GenConfig(
            target_url='https://example.com',
            llm_config=LLMConfig(model='gpt-4o', api_key='test-key'),
            test_files=['resume.pdf', 'photo.png'],
        )
        assert config.test_files == ['resume.pdf', 'photo.png']


@pytest.fixture
def test_files_dir(tmp_path):
    """Create a minimal test directory with a resume.pdf for integration
    tests."""
    pdf_file = tmp_path / 'resume.pdf'
    pdf_file.write_bytes(b'%PDF-1.4 fake pdf content')
    return tmp_path


class TestIntegration:
    """Integration tests for config -> library -> catalog flow."""

    def test_genconfig_to_library_flow(self, test_files_dir):
        """Test that GenConfig.test_files_dir correctly feeds
        TestFileLibrary."""
        config = GenConfig(
            target_url='https://example.com',
            llm_config=LLMConfig(model='gpt-4o', api_key='test-key'),
            test_files_dir=str(test_files_dir),
        )
        assert config.test_files_dir is not None

        library = TestFileLibrary(config.test_files_dir)
        assert len(library.files) > 0

        catalog = library.get_catalog_for_llm()
        assert 'resume.pdf' in catalog
        assert config.test_files_dir in catalog

    def test_none_config_skips_library(self):
        """Test that None test_files_dir means no library created."""
        config = GenConfig(
            target_url='https://example.com',
            llm_config=LLMConfig(model='gpt-4o', api_key='test-key'),
        )
        assert config.test_files_dir is None
        # Simulating gen_executor behavior: no library when dir is None
        test_file_library = None
        if config.test_files_dir:
            test_file_library = TestFileLibrary(config.test_files_dir)
        assert test_file_library is None

    def test_path_validation_security(self, test_files_dir):
        """Test end-to-end path validation security."""
        library = TestFileLibrary(str(test_files_dir))

        # Valid file inside directory
        valid = str(test_files_dir / 'resume.pdf')
        assert library.validate_file_path(valid) is True

        # Traversal attack
        evil = str(test_files_dir / '..' / '..' / 'etc' / 'passwd')
        assert library.validate_file_path(evil) is False

        # Completely unrelated path
        assert library.validate_file_path('/tmp/random_file.pdf') is False
