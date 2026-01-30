"""Unit tests for URLValidator (Phase 1 - P0).

Tests URL validation and auto-correction logic to prevent LLM hallucinations.
"""

import pytest

from webqa_agent.utils.url_validator import URLValidator


class TestURLValidatorInit:
    """Test URLValidator initialization."""

    def test_init_valid_base_url(self):
        """Test initialization with valid base URL."""
        validator = URLValidator('https://discovery.intern-ai.org.cn/home')
        assert validator.base_url == 'https://discovery.intern-ai.org.cn/home'
        assert validator.base_domain == 'discovery.intern-ai.org.cn'
        assert validator.base_scheme == 'https'

    def test_init_invalid_base_url_no_scheme(self):
        """Test initialization fails with missing scheme."""
        with pytest.raises(ValueError, match='must include scheme'):
            URLValidator('discovery.intern-ai.org.cn/home')

    def test_init_invalid_base_url_no_domain(self):
        """Test initialization fails with missing domain."""
        with pytest.raises(ValueError, match='must include domain'):
            URLValidator('https:///path')

    def test_init_empty_base_url(self):
        """Test initialization fails with empty URL."""
        with pytest.raises(ValueError, match='cannot be empty'):
            URLValidator('')


class TestURLValidatorValidate:
    """Test URL validation logic."""

    @pytest.fixture
    def validator(self):
        """Provide URLValidator instance."""
        return URLValidator('https://discovery.intern-ai.org.cn/home')

    def test_validate_valid_absolute_url(self, validator):
        """Test validation accepts correct absolute URL."""
        is_valid, error = validator.validate('https://discovery.intern-ai.org.cn/login')
        assert is_valid is True
        assert error is None

    def test_validate_relative_path(self, validator):
        """Test validation accepts relative paths."""
        is_valid, error = validator.validate('/login')
        assert is_valid is True
        assert error is None

    def test_validate_invalid_domain_reordering(self, validator):
        """Test validation catches domain reordering (P0 key test)."""
        # This is the actual P0 bug: LLM generated "intern-discovery" instead of "discovery.intern-ai"
        is_valid, error = validator.validate('https://intern-discovery.org.cn/login')
        assert is_valid is False
        assert 'Domain mismatch' in error
        assert 'discovery.intern-ai.org.cn' in error

    def test_validate_invalid_www_prefix(self, validator):
        """Test validation catches added www prefix."""
        is_valid, error = validator.validate('https://www.discovery.intern-ai.org.cn/login')
        assert is_valid is False
        assert 'Domain mismatch' in error

    def test_validate_invalid_subdomain(self, validator):
        """Test validation catches wrong subdomain."""
        is_valid, error = validator.validate('https://test.discovery.intern-ai.org.cn/login')
        assert is_valid is False
        assert 'Domain mismatch' in error

    def test_validate_empty_url(self, validator):
        """Test validation rejects empty URL."""
        is_valid, error = validator.validate('')
        assert is_valid is False
        assert 'Empty URL' in error

    def test_validate_no_scheme_absolute(self, validator):
        """Test validation rejects absolute URL without scheme."""
        is_valid, error = validator.validate('discovery.intern-ai.org.cn/login')
        assert is_valid is False
        assert 'must include scheme' in error

    def test_validate_scheme_mismatch_warning(self, validator, caplog):
        """Test validation warns on scheme mismatch but still passes."""
        is_valid, error = validator.validate('http://discovery.intern-ai.org.cn/login')
        # Scheme mismatch is a warning, not an error
        assert is_valid is True
        assert error is None
        # Should log a warning
        assert 'Scheme mismatch' in caplog.text


class TestURLValidatorAutoCorrection:
    """Test URL auto-correction logic."""

    @pytest.fixture
    def validator(self):
        """Provide URLValidator instance."""
        return URLValidator('https://discovery.intern-ai.org.cn/home')

    def test_validate_or_fix_relative_to_absolute(self, validator):
        """Test auto-correction of relative path to absolute URL (Bugfix
        2a04872)."""
        # This is the bugfix test: relative paths should be converted before validation
        fixed_url = validator.validate_or_fix('/login')
        assert fixed_url == 'https://discovery.intern-ai.org.cn/login'

    def test_validate_or_fix_relative_with_query(self, validator):
        """Test auto-correction preserves query parameters."""
        fixed_url = validator.validate_or_fix('/search?q=test')
        assert fixed_url == 'https://discovery.intern-ai.org.cn/search?q=test'

    def test_validate_or_fix_wrong_domain_correction(self, validator):
        """Test auto-correction of wrong domain with same path."""
        # LLM generated wrong domain, but path is correct
        fixed_url = validator.validate_or_fix('https://intern-discovery.org.cn/login')
        assert fixed_url == 'https://discovery.intern-ai.org.cn/login'

    def test_validate_or_fix_wrong_domain_preserves_query(self, validator):
        """Test auto-correction preserves query parameters."""
        fixed_url = validator.validate_or_fix('https://wrong.domain.com/search?q=test&lang=zh')
        assert fixed_url == 'https://discovery.intern-ai.org.cn/search?q=test&lang=zh'

    def test_validate_or_fix_already_valid(self, validator):
        """Test auto-correction returns unchanged URL if already valid."""
        url = 'https://discovery.intern-ai.org.cn/login'
        fixed_url = validator.validate_or_fix(url)
        assert fixed_url == url

    def test_validate_or_fix_unfixable_url(self, validator):
        """Test auto-correction raises ValueError for unfixable URLs."""
        with pytest.raises(ValueError, match='Invalid URL'):
            validator.validate_or_fix('https://completely-wrong-domain.com')

    def test_validate_or_fix_logs_correction(self, validator, caplog):
        """Test auto-correction logs the fix."""
        import logging
        with caplog.at_level(logging.INFO):
            validator.validate_or_fix('/login')
            assert 'auto-corrected' in caplog.text.lower()


class TestURLValidatorIsSameDomain:
    """Test same domain checking."""

    @pytest.fixture
    def validator(self):
        """Provide URLValidator instance."""
        return URLValidator('https://discovery.intern-ai.org.cn/home')

    def test_is_same_domain_true(self, validator):
        """Test same domain check returns True."""
        assert validator.is_same_domain('https://discovery.intern-ai.org.cn/login') is True

    def test_is_same_domain_false(self, validator):
        """Test same domain check returns False."""
        assert validator.is_same_domain('https://google.com') is False

    def test_is_same_domain_relative_path(self, validator):
        """Test same domain check returns True for relative paths."""
        assert validator.is_same_domain('/login') is True


class TestURLValidatorEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_url_with_port(self):
        """Test URL with explicit port."""
        validator = URLValidator('https://example.com:8080/home')
        is_valid, _ = validator.validate('https://example.com:8080/login')
        assert is_valid is True

    def test_url_with_fragment(self):
        """Test URL with fragment."""
        validator = URLValidator('https://example.com/home')
        is_valid, _ = validator.validate('https://example.com/page#section')
        assert is_valid is True

    def test_url_with_special_characters(self):
        """Test URL with special characters in path."""
        validator = URLValidator('https://example.com/home')
        is_valid, _ = validator.validate('https://example.com/search?q=test%20query&lang=zh-CN')
        assert is_valid is True

    def test_root_path(self):
        """Test validation of root path."""
        validator = URLValidator('https://example.com/home')
        is_valid, _ = validator.validate('https://example.com/')
        assert is_valid is True

    def test_base_url_with_path(self):
        """Test validator works when base URL has path."""
        validator = URLValidator('https://example.com/app/home')
        is_valid, _ = validator.validate('https://example.com/app/login')
        assert is_valid is True
        # Domain validation doesn't check path, only domain
        is_valid, _ = validator.validate('https://example.com/other/path')
        assert is_valid is True
