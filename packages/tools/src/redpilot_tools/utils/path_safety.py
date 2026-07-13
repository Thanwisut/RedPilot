"""Path safety utilities — containment checks for filesystem tool operations.

Every filesystem tool (list_directory, read_file, write_file, edit_file) must
validate that the requested path is contained within the engagement's
scratch/evidence root directory. This module provides the canonical
containment check that rejects:

- Path traversal (``../`` components escaping the root)
- Absolute paths outside the root
- Symlink escapes (resolves all symlinks before checking)
- Null bytes and other suspicious patterns
"""

from __future__ import annotations

import os
from pathlib import Path


class PathEscapeError(ValueError):
    """Raised when a path attempts to escape the allowed root directory."""


_SUSPICIOUS_PATTERNS = [
    b"\x00",  # Null bytes
]


def resolve_safe_path(
    requested_path: str,
    root_dir: str,
    *,
    must_exist: bool = False,
) -> Path:
    """Resolve *requested_path* relative to *root_dir* and validate containment.

    Steps:
    1. Reject paths with suspicious content (null bytes, etc.)
    2. Resolve the requested path relative to root_dir
    3. Resolve symlinks (``Path.resolve()``)
    4. Verify the resolved path starts with the resolved root_dir
    5. If *must_exist*, verify the path actually exists on disk

    Args:
        requested_path: The user/LLM-supplied path string. May be relative
            or absolute.
        root_dir: The allowed root directory. All operations must stay
            within this directory tree.
        must_exist: If True, raises ``FileNotFoundError`` if the resolved
            path does not exist on disk.

    Returns:
        The resolved, containment-verified ``Path`` object.

    Raises:
        PathEscapeError: If the path attempts to escape the root directory
            or contains suspicious patterns.
        FileNotFoundError: If *must_exist* is True and the path doesn't exist.
    """
    # 1. Check for suspicious binary content
    _check_suspicious_patterns(requested_path)

    # 2. Resolve both root and requested paths
    root = Path(root_dir).resolve()
    resolved = (root / requested_path).resolve()

    # 3. Verify containment
    try:
        resolved.relative_to(root)
    except ValueError:
        msg = (
            f"Path '{requested_path}' resolves to '{resolved}' "
            f"which is outside the allowed root directory '{root}'"
        )
        raise PathEscapeError(msg) from None

    # 4. Check must_exist
    if must_exist and not resolved.exists():
        msg = f"Path '{requested_path}' does not exist (resolved to '{resolved}')"
        raise FileNotFoundError(msg)

    return resolved


def resolve_safe_path_allow_missing(
    requested_path: str,
    root_dir: str,
) -> Path:
    """Like ``resolve_safe_path`` but does not require the path to exist.

    Useful for write operations where the file is being created for the
    first time, or for edit operations where we check existence separately
    with a clearer error message.

    Args:
        requested_path: The user/LLM-supplied path string.
        root_dir: The allowed root directory.

    Returns:
        The resolved, containment-verified ``Path`` object.

    Raises:
        PathEscapeError: If the path attempts to escape the root.
    """
    return resolve_safe_path(requested_path, root_dir, must_exist=False)


def resolve_safe_path_must_exist(
    requested_path: str,
    root_dir: str,
) -> Path:
    """Like ``resolve_safe_path`` but requires the path to already exist.

    Useful for read and edit operations where the file must already
    exist on disk.

    Args:
        requested_path: The user/LLM-supplied path string.
        root_dir: The allowed root directory.

    Returns:
        The resolved, containment-verified ``Path`` object.

    Raises:
        PathEscapeError: If the path attempts to escape the root.
        FileNotFoundError: If the path does not exist.
    """
    return resolve_safe_path(requested_path, root_dir, must_exist=True)


def _check_suspicious_patterns(path_str: str) -> None:
    """Check for suspicious patterns in the path string.

    Raises:
        PathEscapeError: If a suspicious pattern is found.
    """
    encoded = path_str.encode("utf-8", errors="replace")
    for pattern in _SUSPICIOUS_PATTERNS:
        if pattern in encoded:
            msg = f"Path contains suspicious pattern (null byte): '{path_str}'"
            raise PathEscapeError(msg)
