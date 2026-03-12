"""Tests for the version module."""
from musicround.version import VERSION_INFO, get_version_str


class TestVersionInfo:
    """Tests for VERSION_INFO dictionary."""

    def test_version_info_exists(self):
        """Test that VERSION_INFO is a non-empty dict."""
        assert isinstance(VERSION_INFO, dict)
        assert len(VERSION_INFO) > 0

    def test_version_key_present(self):
        """Test that 'version' key is present."""
        assert 'version' in VERSION_INFO

    def test_version_is_string(self):
        """Test that version value is a string."""
        assert isinstance(VERSION_INFO['version'], str)

    def test_release_name_present(self):
        """Test that 'release_name' key is present."""
        assert 'release_name' in VERSION_INFO

    def test_build_number_present(self):
        """Test that 'build_number' key is present."""
        assert 'build_number' in VERSION_INFO


class TestGetVersionStr:
    """Tests for the get_version_str function."""

    def test_returns_string(self):
        """Test that get_version_str returns a string."""
        result = get_version_str()
        assert isinstance(result, str)

    def test_contains_version_number(self):
        """Test that the version string contains the version number."""
        result = get_version_str()
        assert VERSION_INFO['version'] in result

    def test_contains_v_prefix(self):
        """Test that the version string starts with 'v'."""
        result = get_version_str()
        assert result.startswith('v')

    def test_without_build_number(self):
        """Test that build number is not included when include_build=False."""
        result = get_version_str(include_build=False)
        assert VERSION_INFO['build_number'] not in result

    def test_with_build_number(self):
        """Test that build number is included when include_build=True."""
        result = get_version_str(include_build=True)
        assert VERSION_INFO['build_number'] in result

    def test_contains_release_name(self):
        """Test that the version string contains the release name."""
        result = get_version_str()
        assert VERSION_INFO['release_name'] in result
