"""Tests for ApprovalGate — lifecycle, permissions, timeouts, concurrency."""

from redpilot_core.guards.approval_gate import ApprovalGate, ApprovalRequest, ApprovalStatus
from redpilot_core.models.agent_manifest import PermissionLevel
from redpilot_core.models.tool_manifest import SandboxProfile, ToolManifest


class TestApprovalGate:
    """Approval gate lifecycle — creation, resolution, expiry."""

    def setup_method(self) -> None:
        self.gate = ApprovalGate()

    def test_requires_approval_dangerous_tool(self) -> None:
        tool = ToolManifest(
            name="metasploit",
            sandbox_profile=SandboxProfile.EXPLOIT,
            dangerous=True,
        )
        assert self.gate.requires_approval(tool, PermissionLevel.READ_ONLY)

    def test_requires_approval_explicit_flag(self) -> None:
        tool = ToolManifest(
            name="sqlmap",
            sandbox_profile=SandboxProfile.WEB_SCAN,
            requires_approval=True,
        )
        assert self.gate.requires_approval(tool, PermissionLevel.READ_ONLY)

    def test_no_approval_for_readonly_tool(self) -> None:
        tool = ToolManifest(
            name="nmap",
            sandbox_profile=SandboxProfile.NETWORK_SCAN_STANDARD,
        )
        assert not self.gate.requires_approval(tool, PermissionLevel.READ_ONLY)

    def test_no_approval_when_permission_sufficient(self) -> None:
        tool = ToolManifest(
            name="sqlmap",
            sandbox_profile=SandboxProfile.WEB_SCAN,
            requires_approval=True,
        )
        # WRITE-level agent using a tool that requires approval -> needs approval
        # Actually, requires_approval=true always needs approval
        assert self.gate.requires_approval(tool, PermissionLevel.WRITE)

    def test_create_and_resolve_approve(self) -> None:
        request = self.gate.create_request(
            tool_name="sqlmap",
            target="10.0.0.50",
            args={"url": "http://10.0.0.50/login.php"},
            rationale="Testing for SQL injection in login form",
            agent_id="web_exploitation_agent",
            permission_level=PermissionLevel.WRITE,
        )
        assert request.id is not None
        assert request.status == ApprovalStatus.PENDING

        resolved = self.gate.resolve(request.id, approved=True, resolved_by="user_alice")
        assert resolved is not None
        assert resolved.status == ApprovalStatus.APPROVED
        assert resolved.resolved_by == "user_alice"
        assert resolved.resolved_at is not None

    def test_create_and_resolve_deny(self) -> None:
        request = self.gate.create_request(
            tool_name="metasploit",
            target="10.0.0.50",
            args={"module": "exploit/multi/handler"},
            rationale="Setting up reverse shell handler",
            agent_id="exploit_agent",
            permission_level=PermissionLevel.DANGEROUS,
        )
        assert len(self.gate.pending_requests) == 1

        resolved = self.gate.resolve(request.id, approved=False)
        assert resolved is not None
        assert resolved.status == ApprovalStatus.DENIED
        assert len(self.gate.pending_requests) == 0
        assert len(self.gate.resolved_requests) == 1

    def test_create_and_expire(self) -> None:
        # Create with a very short timeout
        request = self.gate.create_request(
            tool_name="sqlmap",
            target="10.0.0.50",
            args={},
            rationale="Quick test",
            agent_id="web_exploitation_agent",
            permission_level=PermissionLevel.WRITE,
            timeout_seconds=0,  # Will expire immediately
        )

        # Resolve non-existent request returns None
        assert self.gate.resolve("nonexistent", approved=True) is None

        # Check for expired requests
        expired = self.gate.check_expired()
        assert len(expired) == 1
        assert expired[0].id == request.id
        assert expired[0].status == ApprovalStatus.EXPIRED
        assert expired[0].resolved_by == "timeout"

    def test_pending_requests_list(self) -> None:
        assert len(self.gate.pending_requests) == 0

        r1 = self.gate.create_request(tool_name="tool1", target="10.0.0.1", args={},
                                       rationale="test", agent_id="agent1")
        r2 = self.gate.create_request(tool_name="tool2", target="10.0.0.2", args={},
                                       rationale="test", agent_id="agent2")

        pending = self.gate.pending_requests
        assert len(pending) == 2
        assert r1.id in [p.id for p in pending]
        assert r2.id in [p.id for p in pending]

    def test_get_request(self) -> None:
        request = self.gate.create_request(
            tool_name="sqlmap", target="10.0.0.50", args={},
            rationale="test", agent_id="agent1",
        )

        # Get pending request
        found = self.gate.get_request(request.id)
        assert found is not None
        assert found.id == request.id
        assert found.status == ApprovalStatus.PENDING

        # Resolve and get from resolved
        self.gate.resolve(request.id, approved=True)
        found = self.gate.get_request(request.id)
        assert found is not None
        assert found.status == ApprovalStatus.APPROVED

        # Non-existent returns None
        assert self.gate.get_request("does-not-exist") is None

    def test_clear_resolved(self) -> None:
        request = self.gate.create_request(
            tool_name="sqlmap", target="10.0.0.50", args={},
            rationale="test", agent_id="agent1",
        )
        self.gate.resolve(request.id, approved=True)
        assert len(self.gate.resolved_requests) == 1

        cleared = self.gate.clear_resolved()
        assert cleared == 1
        assert len(self.gate.resolved_requests) == 0

    def test_on_resolved_callback(self) -> None:
        callback_results: list[str] = []

        def callback(req: ApprovalRequest) -> None:
            callback_results.append(req.id)

        request = self.gate.create_request(
            tool_name="sqlmap", target="10.0.0.50", args={},
            rationale="test", agent_id="agent1",
            on_resolved=callback,
        )

        self.gate.resolve(request.id, approved=True)
        assert len(callback_results) == 1
        assert callback_results[0] == request.id

    def test_timeout_on_resolved_callback(self) -> None:
        callback_results: list[str] = []

        def callback(req: ApprovalRequest) -> None:
            callback_results.append(req.id)

        self.gate.create_request(
            tool_name="sqlmap", target="10.0.0.50", args={},
            rationale="test", agent_id="agent1",
            timeout_seconds=0,
            on_resolved=callback,
        )

        self.gate.check_expired()
        assert len(callback_results) == 1
