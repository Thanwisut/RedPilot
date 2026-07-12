"""Tests for InMemoryAuditLog — write, read, entry structure."""

import pytest
from redpilot_core.models.scope import Scope
from redpilot_core.models.tool_result import ToolResult
from redpilot_tools.audit import InMemoryAuditLog


class TestInMemoryAuditLog:
    """InMemoryAuditLog lifecycle tests."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.log = InMemoryAuditLog()
        self.scope = Scope(name="test-engagement", allowed_targets=["10.0.0.0/24"])

    @pytest.mark.asyncio
    async def test_write_success_entry(self) -> None:
        result = ToolResult.success(
            "nmap",
            stdout="Nmap done",
            execution_time_ms=1500,
            target="10.0.0.50",
        )
        await self.log.write(
            tool_name="nmap",
            target="10.0.0.50",
            args={"target": "10.0.0.50"},
            requesting_agent="port_scan_agent",
            task_node="NODE-001",
            rationale="Scan target for open ports",
            scope=self.scope,
            result=result,
            stdout="Nmap done: 1 host scanned",
            stderr="",
        )
        assert self.log.total_count == 1
        entry = self.log.entries[0]
        assert entry.tool_name == "nmap"
        assert entry.target == "10.0.0.50"
        assert entry.result_status == "success"
        assert entry.requesting_agent == "port_scan_agent"
        assert entry.scope_name == "test-engagement"

    @pytest.mark.asyncio
    async def test_write_blocked_entry(self) -> None:
        result = ToolResult.blocked(
            "sqlmap",
            reason="Target not in scope",
            target="192.168.1.1",
        )
        await self.log.write(
            tool_name="sqlmap",
            target="192.168.1.1",
            args={"url": "http://192.168.1.1/login.php"},
            requesting_agent="web_exploit_agent",
            task_node="NODE-002",
            rationale="SQL injection test",
            scope=self.scope,
            result=result,
        )
        assert self.log.total_count == 1
        entry = self.log.entries[0]
        assert entry.result_status == "blocked"
        assert entry.result_error == "Target not in scope"

    @pytest.mark.asyncio
    async def test_write_multiple_entries(self) -> None:
        for i in range(5):
            result = ToolResult.success(f"tool_{i}")
            await self.log.write(
                tool_name=f"tool_{i}",
                target="10.0.0.50",
                args={},
                requesting_agent="agent",
                task_node=f"NODE-{i:03d}",
                rationale=f"Test run {i}",
                scope=self.scope,
                result=result,
            )
        assert self.log.total_count == 5

    @pytest.mark.asyncio
    async def test_read_returns_newest_first(self) -> None:
        for i in range(5):
            result = ToolResult.success(f"tool_{i}")
            await self.log.write(
                tool_name=f"tool_{i}",
                target="10.0.0.50",
                args={},
                requesting_agent="agent",
                task_node=f"NODE-{i:03d}",
                rationale="",
                scope=self.scope,
                result=result,
            )
        entries = await self.log.read(limit=3)
        assert len(entries) == 3
        assert entries[0].tool_name == "tool_4"
        assert entries[1].tool_name == "tool_3"
        assert entries[2].tool_name == "tool_2"

    @pytest.mark.asyncio
    async def test_read_with_offset(self) -> None:
        for i in range(5):
            result = ToolResult.success(f"tool_{i}")
            await self.log.write(
                tool_name=f"tool_{i}",
                target="10.0.0.50",
                args={},
                requesting_agent="agent",
                task_node=f"NODE-{i:03d}",
                rationale="",
                scope=self.scope,
                result=result,
            )
        entries = await self.log.read(limit=10, offset=2)
        assert len(entries) == 3
        assert entries[0].tool_name == "tool_2"
        assert entries[1].tool_name == "tool_1"
        assert entries[2].tool_name == "tool_0"

    @pytest.mark.asyncio
    async def test_stdout_truncated(self) -> None:
        long_stdout = "a" * 10000
        result = ToolResult.success("nmap", stdout=long_stdout)
        await self.log.write(
            tool_name="nmap",
            target="10.0.0.50",
            args={},
            requesting_agent="agent",
            task_node="NODE-001",
            rationale="",
            scope=self.scope,
            result=result,
            stdout=long_stdout,
        )
        assert len(self.log.entries[0].stdout_truncated) == 5000
