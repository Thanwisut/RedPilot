"""Tests for ShellExecAdapter — command construction, argv safety, manifest."""

import pytest
from redpilot_tools.adapters.shell_exec_adapter import (
    SHELL_EXEC_MANIFEST,
    ShellExecAdapter,
)


class TestShellExecAdapter:
    """ShellExecAdapter command building and safety."""

    def setup_method(self) -> None:
        self.adapter = ShellExecAdapter()

    # ------------------------------------------------------------------
    # Command construction
    # ------------------------------------------------------------------

    def test_build_command_simple(self) -> None:
        argv = self.adapter.build_command(
            {"command": ["ls", "-la"]},
            "/tmp/scratch",
        )
        assert argv == ["ls", "-la"]

    def test_build_command_with_description(self) -> None:
        argv = self.adapter.build_command(
            {"command": ["echo", "hello"], "description": "Say hello"},
            "/tmp/scratch",
        )
        assert argv == ["echo", "hello"]

    def test_build_command_with_timeout(self) -> None:
        argv = self.adapter.build_command(
            {"command": ["sleep", "10"], "timeout": 30},
            "/tmp/scratch",
        )
        assert argv == ["sleep", "10"]

    # ------------------------------------------------------------------
    # Argv safety — fuzz tests (following nmap's pattern)
    # ------------------------------------------------------------------

    def test_build_command_never_contains_shell_metachar(self) -> None:
        """Fuzz test: shell metacharacters in argv elements are literal strings,
        not injected shell syntax, because we use list[str] never a shell string."""
        dangerous_inputs: list[list[str]] = [
            ["ls", "; rm -rf /"],
            ["echo", "`whoami`"],
            ["cat", "$(cat /etc/passwd)"],
            ["echo", "hello | cat /etc/shadow"],
            ["nmap", "10.0.0.1 && echo pwned"],
            ["bash", "-c", "rm -rf /"],
            ["echo", "hello > /dev/null"],
            ["python3", "-c", "import os; os.system('rm -rf /')"],
            ["perl", "-e", "system('rm -rf /')"],
            ["echo", "hello", "||", "rm", "-rf", "/"],
        ]
        for cmd in dangerous_inputs:
            argv = self.adapter.build_command(
                {"command": cmd},
                "/tmp/scratch",
            )
            # Each element should be passed through as-is, not interpreted
            assert len(argv) == len(cmd)
            for i, arg in enumerate(argv):
                assert arg == cmd[i]

    # ------------------------------------------------------------------
    # Input validation
    # ------------------------------------------------------------------

    def test_missing_command_raises(self) -> None:
        with pytest.raises(ValueError, match="Missing required"):
            self.adapter.build_command({}, "/tmp/scratch")

    def test_non_list_command_raises(self) -> None:
        with pytest.raises(ValueError, match="must be a list"):
            self.adapter.build_command(
                {"command": "ls -la"},
                "/tmp/scratch",
            )

    def test_empty_command_raises(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            self.adapter.build_command(
                {"command": []},
                "/tmp/scratch",
            )

    def test_non_string_element_raises(self) -> None:
        with pytest.raises(ValueError, match="must be a string"):
            self.adapter.build_command(
                {"command": ["ls", 123]},
                "/tmp/scratch",
            )

    def test_none_element_raises(self) -> None:
        with pytest.raises(ValueError, match="must be a string"):
            self.adapter.build_command(
                {"command": ["ls", None]},
                "/tmp/scratch",
            )

    # ------------------------------------------------------------------
    # Command representation (for approval prompts)
    # ------------------------------------------------------------------

    def test_build_command_representation(self) -> None:
        result = self.adapter.build_command_representation(
            {"command": ["nmap", "-sT", "10.0.0.1"]},
        )
        assert "nmap" in result
        assert "-sT" in result
        assert "10.0.0.1" in result

    def test_build_command_representation_empty(self) -> None:
        result = self.adapter.build_command_representation({})
        assert isinstance(result, str)

    def test_build_command_representation_non_list(self) -> None:
        result = self.adapter.build_command_representation(
            {"command": "not a list"},
        )
        assert isinstance(result, str)

    # ------------------------------------------------------------------
    # Output parsing
    # ------------------------------------------------------------------

    def test_parse_output(self) -> None:
        parsed = self.adapter.parse_output(
            "hello world\nline2",
            "",
            0,
            "/tmp/scratch",
        )
        assert parsed["stdout"] == "hello world\nline2"
        assert parsed["stderr"] == ""
        assert parsed["exit_code"] == 0

    def test_parse_output_with_error(self) -> None:
        parsed = self.adapter.parse_output(
            "",
            "permission denied",
            1,
            "/tmp/scratch",
        )
        assert parsed["stdout"] == ""
        assert parsed["stderr"] == "permission denied"
        assert parsed["exit_code"] == 1

    # ------------------------------------------------------------------
    # Manifest
    # ------------------------------------------------------------------

    def test_manifest_is_correct(self) -> None:
        assert SHELL_EXEC_MANIFEST.name == "shell_exec"
        assert SHELL_EXEC_MANIFEST.dangerous is True
        assert SHELL_EXEC_MANIFEST.requires_approval is True
        assert SHELL_EXEC_MANIFEST.sandbox_profile.value == "code_analysis"
