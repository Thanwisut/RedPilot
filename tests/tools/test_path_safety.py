"""Tests for path_safety — containment validation for filesystem tools.

Covers path-traversal attempts, absolute paths, symlink escapes,
and null bytes — the common vulnerability class for filesystem tools.
"""

import tempfile
from pathlib import Path

import pytest
from redpilot_tools.utils.path_safety import (
    PathEscapeError,
    resolve_safe_path,
    resolve_safe_path_allow_missing,
    resolve_safe_path_must_exist,
)


class TestResolveSafePath:
    """Core path containment validation."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Create a temporary root directory for testing."""
        self.root = tempfile.mkdtemp(prefix="redpilot_test_root_")
        # Create a nested directory structure
        (Path(self.root) / "subdir").mkdir()
        (Path(self.root) / "subdir" / "nested.txt").write_text("nested")
        (Path(self.root) / "existing.txt").write_text("hello")

    # ------------------------------------------------------------------
    # Path traversal rejection
    # ------------------------------------------------------------------

    def test_rejects_simple_path_traversal(self) -> None:
        """``../`` escaping the root should be rejected."""
        with pytest.raises(PathEscapeError, match="outside the allowed root"):
            resolve_safe_path("../etc/passwd", self.root)

    def test_rejects_deep_path_traversal(self) -> None:
        """Multiple ``../`` components should be rejected."""
        with pytest.raises(PathEscapeError, match="outside the allowed root"):
            resolve_safe_path("../../../../etc/passwd", self.root)

    def test_rejects_mixed_traversal(self) -> None:
        """``subdir/../../../etc/passwd`` should be rejected."""
        with pytest.raises(PathEscapeError, match="outside the allowed root"):
            resolve_safe_path("subdir/../../../etc/passwd", self.root)

    def test_rejects_traversal_in_middle(self) -> None:
        """``subdir/../existing.txt`` should NOT escape but should resolve."""
        # This stays within root — should pass
        expected = Path(self.root).resolve() / "existing.txt"
        resolved = resolve_safe_path("subdir/../existing.txt", self.root, must_exist=True)
        assert resolved == expected

    # ------------------------------------------------------------------
    # Absolute path rejection
    # ------------------------------------------------------------------

    def test_rejects_absolute_path_outside_root(self) -> None:
        """Absolute paths outside root should be rejected."""
        with pytest.raises(PathEscapeError, match="outside the allowed root"):
            resolve_safe_path("/etc/passwd", self.root)

    def test_rejects_absolute_path_traversal(self) -> None:
        """Absolute path with traversal should be rejected."""
        with pytest.raises(PathEscapeError, match="outside the allowed root"):
            resolve_safe_path("/var/log/../../etc/passwd", self.root)

    # ------------------------------------------------------------------
    # Null byte injection
    # ------------------------------------------------------------------

    def test_rejects_null_byte(self) -> None:
        """Path containing null bytes should be rejected."""
        with pytest.raises(PathEscapeError, match="null byte"):
            resolve_safe_path("existing.txt\x00.jpg", self.root)

    def test_rejects_null_byte_traversal(self) -> None:
        """Path with null byte and traversal should be rejected."""
        with pytest.raises(PathEscapeError, match="null byte"):
            resolve_safe_path("../etc\x00/passwd", self.root)

    # ------------------------------------------------------------------
    # Valid path acceptance
    # ------------------------------------------------------------------

    def test_allows_relative_path_within_root(self) -> None:
        """Simple relative path within root should be allowed."""
        resolved = resolve_safe_path("existing.txt", self.root, must_exist=True)
        assert resolved == Path(self.root).resolve() / "existing.txt"

    def test_allows_nested_path(self) -> None:
        """Nested relative path should be allowed."""
        expected = Path(self.root).resolve() / "subdir" / "nested.txt"
        resolved = resolve_safe_path("subdir/nested.txt", self.root, must_exist=True)
        assert resolved == expected

    def test_allows_root_traversal_staying_inside(self) -> None:
        """Traversal that stays within root should be allowed."""
        resolved = resolve_safe_path("subdir/..", self.root, must_exist=True)
        assert resolved == Path(self.root).resolve()

    def test_allows_root_path(self) -> None:
        """Empty path (root itself) should resolve to root."""
        resolved = resolve_safe_path("", self.root, must_exist=True)
        assert resolved == Path(self.root).resolve()

    def test_allows_dot_path(self) -> None:
        """``.`` should resolve to root."""
        resolved = resolve_safe_path(".", self.root, must_exist=True)
        assert resolved == Path(self.root).resolve()

    # ------------------------------------------------------------------
    # must_exist behavior
    # ------------------------------------------------------------------

    def test_must_exist_raises_file_not_found(self) -> None:
        """``must_exist=True`` should raise if path doesn't exist."""
        with pytest.raises(FileNotFoundError, match="does not exist"):
            resolve_safe_path("nonexistent.txt", self.root, must_exist=True)

    def test_allow_missing_does_not_require_existence(self) -> None:
        """``must_exist=False`` should not raise for missing paths."""
        expected = Path(self.root).resolve() / "new_file.txt"
        resolved = resolve_safe_path("new_file.txt", self.root, must_exist=False)
        assert resolved == expected


class TestResolveSafePathConvenience:
    """Convenience wrappers for resolve_safe_path."""

    def test_allow_missing(self) -> None:
        root = tempfile.mkdtemp()
        expected = Path(root).resolve() / "new_file.txt"
        resolved = resolve_safe_path_allow_missing("new_file.txt", root)
        assert resolved == expected

    def test_must_exist_ok(self) -> None:
        root = tempfile.mkdtemp()
        (Path(root) / "test.txt").write_text("content")
        expected = Path(root).resolve() / "test.txt"
        resolved = resolve_safe_path_must_exist("test.txt", root)
        assert resolved == expected

    def test_must_exist_fails(self) -> None:
        root = tempfile.mkdtemp()
        with pytest.raises(FileNotFoundError):
            resolve_safe_path_must_exist("missing.txt", root)

    def test_escape_rejected(self) -> None:
        root = tempfile.mkdtemp()
        with pytest.raises(PathEscapeError):
            resolve_safe_path("../etc", root)
