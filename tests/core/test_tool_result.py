"""Tests for ToolResult domain model and convenience constructors."""

from redpilot_core.models.tool_result import ToolResult, ToolResultStatus


class TestToolResult:
    """ToolResult construction and property behavior."""

    def test_success_constructor(self) -> None:
        result = ToolResult.success(
            "nmap",
            stdout="Nmap done: 1 IP address scanned",
            parsed_output={"hosts": [{"ip": "10.0.0.1", "ports": [22, 80]}]},
            execution_time_ms=1500,
            target="10.0.0.1",
            raw_args={"target": "10.0.0.1", "ports": "22,80"},
            tool_version="7.94",
        )
        assert result.status == ToolResultStatus.SUCCESS
        assert result.tool_name == "nmap"
        assert result.exit_code == 0
        assert result.succeeded
        assert result.parsed_output is not None
        assert result.parsed_output["hosts"][0]["ip"] == "10.0.0.1"
        assert result.execution_time_ms == 1500
        assert result.target == "10.0.0.1"
        assert result.tool_version == "7.94"

    def test_failure_constructor(self) -> None:
        result = ToolResult.failure(
            "nmap",
            error="Connection refused",
            exit_code=1,
            stderr="Failed to open socket",
            target="10.0.0.1",
        )
        assert result.status == ToolResultStatus.FAILURE
        assert not result.succeeded
        assert result.error == "Connection refused"
        assert result.exit_code == 1
        assert result.stderr == "Failed to open socket"
        assert result.can_retry

    def test_blocked_constructor(self) -> None:
        result = ToolResult.blocked(
            "sqlmap",
            reason="Target not in scope",
            target="192.168.1.100",
        )
        assert result.status == ToolResultStatus.BLOCKED
        assert not result.succeeded
        assert result.error == "Target not in scope"
        assert not result.can_retry  # scope decisions shouldn't be retried

    def test_timeout_can_retry(self) -> None:
        result = ToolResult(
            status=ToolResultStatus.TIMEOUT,
            tool_name="ffuf",
            error="Timed out after 30 seconds",
            execution_time_ms=30000,
        )
        assert not result.succeeded
        assert result.can_retry

    def test_partial_result(self) -> None:
        result = ToolResult(
            status=ToolResultStatus.PARTIAL,
            tool_name="nuclei",
            stdout="Found 2 templates matched",
            parsed_output={"findings": ["CVE-2023-1234", "CVE-2023-5678"]},
        )
        assert result.status == ToolResultStatus.PARTIAL
        assert not result.succeeded
        assert result.parsed_output is not None
        assert len(result.parsed_output["findings"]) == 2

    def test_defaults(self) -> None:
        result = ToolResult(status=ToolResultStatus.SUCCESS, tool_name="test")
        assert result.stdout == ""
        assert result.stderr == ""
        assert result.exit_code == 0
        assert result.artifacts == []
        assert result.execution_time_ms == 0
        assert result.target == ""
        assert result.raw_args == {}
