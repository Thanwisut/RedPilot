"""Tests for filesystem adapters — list_directory, read_file, write_file, edit_file.

Covers:
- Normal command construction
- Path traversal rejection (common vulnerability class)
- Output parsing
- Manifest properties
"""

import tempfile
from pathlib import Path

import pytest
from redpilot_tools.adapters.filesystem_adapter import (
    EDIT_FILE_MANIFEST,
    LIST_DIR_MANIFEST,
    READ_FILE_MANIFEST,
    WRITE_FILE_MANIFEST,
    EditFileAdapter,
    ListDirectoryAdapter,
    ReadFileAdapter,
    WriteFileAdapter,
)
from redpilot_tools.utils.path_safety import PathEscapeError


class TestListDirectoryAdapter:
    """ListDirectoryAdapter command building and path safety."""

    def setup_method(self) -> None:
        self.adapter = ListDirectoryAdapter()
        self.temp_dir = tempfile.mkdtemp(prefix="redpilot_test_ls_")

    def test_build_command_simple(self) -> None:
        argv = self.adapter.build_command(
            {"path": "subdir"},
            self.temp_dir,
        )
        assert argv[0] == "ls"
        assert "/scratch/subdir" in argv

    def test_build_command_recursive(self) -> None:
        argv = self.adapter.build_command(
            {"path": "subdir", "recursive": True},
            self.temp_dir,
        )
        assert "-R" in argv
        assert "/scratch/subdir" in argv

    def test_rejects_path_traversal(self) -> None:
        with pytest.raises(PathEscapeError):
            self.adapter.build_command(
                {"path": "../etc"},
                self.temp_dir,
            )

    def test_rejects_absolute_path_outside(self) -> None:
        with pytest.raises(PathEscapeError):
            self.adapter.build_command(
                {"path": "/etc/passwd"},
                self.temp_dir,
            )

    def test_parse_output(self) -> None:
        parsed = self.adapter.parse_output(
            "file1.txt\nfile2.txt\nsubdir/\n",
            "",
            0,
            "/tmp/scratch",
        )
        assert parsed["count"] == 3
        assert "file1.txt" in parsed["entries"]
        assert "subdir/" in parsed["entries"]

    def test_parse_output_with_total_line(self) -> None:
        """'total N' lines should be excluded."""
        parsed = self.adapter.parse_output(
            "total 64\nfile1.txt\nfile2.txt\n",
            "",
            0,
            "/tmp/scratch",
        )
        assert parsed["count"] == 2
        assert "total 64" not in parsed["entries"]

    def test_manifest_is_correct(self) -> None:
        assert LIST_DIR_MANIFEST.name == "list_directory"
        assert LIST_DIR_MANIFEST.dangerous is False
        assert LIST_DIR_MANIFEST.requires_approval is False


class TestReadFileAdapter:
    """ReadFileAdapter command building and path safety."""

    def setup_method(self) -> None:
        self.adapter = ReadFileAdapter()
        self.temp_dir = tempfile.mkdtemp(prefix="redpilot_test_read_")
        # Create a test file for must_exist tests
        (Path(self.temp_dir) / "results.txt").write_text("test content")

    def test_build_command_simple(self) -> None:
        argv = self.adapter.build_command(
            {"path": "results.txt"},
            self.temp_dir,
        )
        assert argv[0] == "cat"
        assert "/scratch/results.txt" in argv

    def test_rejects_path_traversal(self) -> None:
        with pytest.raises(PathEscapeError):
            self.adapter.build_command(
                {"path": "../etc/passwd"},
                self.temp_dir,
            )

    def test_rejects_absolute_path_outside(self) -> None:
        with pytest.raises(PathEscapeError):
            self.adapter.build_command(
                {"path": "/etc/passwd"},
                self.temp_dir,
            )

    def test_parse_output(self) -> None:
        parsed = self.adapter.parse_output(
            "Hello, world!\nLine 2\n",
            "",
            0,
            "/tmp/scratch",
        )
        assert parsed["content"] == "Hello, world!\nLine 2\n"
        assert parsed["size_bytes"] == 21
        assert parsed["truncated"] is False

    def test_parse_output_truncated(self) -> None:
        long_content = "x" * 200000
        parsed = self.adapter.parse_output(
            long_content,
            "",
            0,
            "/tmp/scratch",
        )
        assert parsed["truncated"] is True
        assert len(parsed["content"]) == 100000

    def test_manifest_is_correct(self) -> None:
        assert READ_FILE_MANIFEST.name == "read_file"
        assert READ_FILE_MANIFEST.dangerous is False
        assert READ_FILE_MANIFEST.requires_approval is False


class TestWriteFileAdapter:
    """WriteFileAdapter command building and path safety."""

    def setup_method(self) -> None:
        self.adapter = WriteFileAdapter()
        self.temp_dir = tempfile.mkdtemp(prefix="redpilot_test_write_")

    def test_build_command_simple(self) -> None:
        argv = self.adapter.build_command(
            {"path": "output.txt", "content": "hello world"},
            self.temp_dir,
        )
        assert argv[0] == "/bin/sh"
        assert argv[1] == "-c"
        assert "/scratch/output.txt" in argv[2]

    def test_rejects_path_traversal(self) -> None:
        with pytest.raises(PathEscapeError):
            self.adapter.build_command(
                {"path": "../etc/malicious", "content": "evil"},
                self.temp_dir,
            )

    def test_rejects_absolute_path_outside(self) -> None:
        with pytest.raises(PathEscapeError):
            self.adapter.build_command(
                {"path": "/etc/cron.d/evil", "content": "malicious"},
                self.temp_dir,
            )

    def test_parse_output_success(self) -> None:
        parsed = self.adapter.parse_output("", "", 0, self.temp_dir)
        assert parsed["success"] is True

    def test_parse_output_failure(self) -> None:
        parsed = self.adapter.parse_output(
            "", "permission denied", 1, self.temp_dir,
        )
        assert parsed["success"] is False
        assert "permission denied" in parsed["error"]

    def test_manifest_is_correct(self) -> None:
        assert WRITE_FILE_MANIFEST.name == "write_file"
        assert WRITE_FILE_MANIFEST.dangerous is True
        assert WRITE_FILE_MANIFEST.requires_approval is True


class TestEditFileAdapter:
    """EditFileAdapter command building and path safety."""

    def setup_method(self) -> None:
        self.adapter = EditFileAdapter()
        self.temp_dir = tempfile.mkdtemp(prefix="redpilot_test_edit_")
        # Create a test file for must_exist tests
        (Path(self.temp_dir) / "test.txt").write_text("old content here")

    def test_rejects_path_traversal(self) -> None:
        with pytest.raises(PathEscapeError):
            self.adapter.build_command(
                {"path": "../etc/hosts", "old_string": "old", "new_string": "new"},
                self.temp_dir,
            )

    def test_rejects_absolute_path_outside(self) -> None:
        with pytest.raises(PathEscapeError):
            self.adapter.build_command(
                {"path": "/etc/shadow", "old_string": "old", "new_string": "new"},
                self.temp_dir,
            )

    def test_parse_output_success(self) -> None:
        parsed = self.adapter.parse_output(
            "Replaced 1 occurrence", "", 0, "/tmp/scratch",
        )
        assert parsed["success"] is True
        assert "Replaced" in parsed["message"]

    def test_parse_output_failure(self) -> None:
        parsed = self.adapter.parse_output(
            "", "ERROR: old_string not found", 1, "/tmp/scratch",
        )
        assert parsed["success"] is False
        assert "not found" in parsed["error"]

    def test_manifest_is_correct(self) -> None:
        assert EDIT_FILE_MANIFEST.name == "edit_file"
        assert EDIT_FILE_MANIFEST.dangerous is True
        assert EDIT_FILE_MANIFEST.requires_approval is True
