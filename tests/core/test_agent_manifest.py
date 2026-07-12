"""Tests for AgentManifest and the built-in agent registry."""


from redpilot_core.models.agent_manifest import (
    BUILTIN_AGENTS,
    AgentCluster,
    AgentManifest,
    FailureHandlingStrategy,
    PermissionLevel,
)


class TestPermissionLevel:
    """PermissionLevel enum values and ordering."""

    def test_enum_values(self) -> None:
        assert PermissionLevel.READ_ONLY.value == "read_only"
        assert PermissionLevel.WRITE.value == "write"
        assert PermissionLevel.DANGEROUS.value == "dangerous"

    def test_ranking(self) -> None:
        assert AgentManifest._permission_rank(PermissionLevel.READ_ONLY) == 0
        assert AgentManifest._permission_rank(PermissionLevel.WRITE) == 1
        assert AgentManifest._permission_rank(PermissionLevel.DANGEROUS) == 2


class TestAgentCluster:
    """AgentCluster enum values."""

    def test_clusters_exist(self) -> None:
        assert AgentCluster.CORE.value == "core"
        assert AgentCluster.RECON.value == "recon"
        assert AgentCluster.EXPLOITATION.value == "exploitation"
        assert AgentCluster.POST_EXPLOITATION.value == "post_exploitation"
        assert AgentCluster.EVIDENCE.value == "evidence"


class TestAgentManifest:
    """AgentManifest creation and capability checks."""

    def test_create_minimal(self) -> None:
        manifest = AgentManifest(
            id="test_agent",
            cluster=AgentCluster.RECON,
        )
        assert manifest.id == "test_agent"
        assert manifest.cluster == AgentCluster.RECON
        assert manifest.tool_permission_level == PermissionLevel.READ_ONLY
        assert manifest.failure_handling == FailureHandlingStrategy.RETRY_WITH_BACKOFF

    def test_can_use_tool_allowed_and_permission_ok(self) -> None:
        manifest = AgentManifest(
            id="recon_agent",
            cluster=AgentCluster.RECON,
            tools_allowed=["nmap", "whois"],
            tool_permission_level=PermissionLevel.READ_ONLY,
        )
        assert manifest.can_use_tool("nmap", PermissionLevel.READ_ONLY)
        assert not manifest.can_use_tool("sqlmap", PermissionLevel.WRITE)  # not in allowed list

    def test_can_use_tool_permission_too_high(self) -> None:
        manifest = AgentManifest(
            id="recon_agent",
            cluster=AgentCluster.RECON,
            tools_allowed=["nmap", "metasploit"],
            tool_permission_level=PermissionLevel.READ_ONLY,
        )
        # Tool is in allowed list but requires DANGEROUS permission
        assert not manifest.can_use_tool("metasploit", PermissionLevel.DANGEROUS)

    def test_manifest_entry_roundtrip(self) -> None:
        manifest = AgentManifest(
            id="sqli_agent",
            cluster=AgentCluster.EXPLOITATION,
            responsibilities=["Test for SQL injection vulnerabilities"],
            inputs=["endpoints", "parameters"],
            outputs=["finding", "evidence_refs"],
            tools_allowed=["sqlmap"],
            tool_permission_level=PermissionLevel.WRITE,
            memory_access=["task_memory", "knowledge_cache"],
            escalation="notify_critic",
            failure_handling=FailureHandlingStrategy.RETRY_WITH_BACKOFF,
        )

        entry = manifest.to_manifest_entry()
        assert entry["id"] == "sqli_agent"
        assert entry["cluster"] == "exploitation"
        assert entry["tool_permission_level"] == "write"

        restored = AgentManifest.from_manifest_entry(entry)
        assert restored.id == manifest.id
        assert restored.cluster == manifest.cluster
        assert restored.tool_permission_level == manifest.tool_permission_level
        assert restored.failure_handling == manifest.failure_handling
        assert restored.tools_allowed == manifest.tools_allowed


class TestBuiltinAgents:
    """The built-in agent registry from the architecture doc."""

    def test_builtin_agents_exist(self) -> None:
        assert len(BUILTIN_AGENTS) > 0

    def test_core_agents_present(self) -> None:
        assert "planner_agent" in BUILTIN_AGENTS
        assert "task_manager" in BUILTIN_AGENTS
        assert "critic_agent" in BUILTIN_AGENTS
        assert "reflection_agent" in BUILTIN_AGENTS
        assert "verifier_agent" in BUILTIN_AGENTS
        assert "memory_agent" in BUILTIN_AGENTS
        assert "retry_agent" in BUILTIN_AGENTS

    def test_recon_agents_present(self) -> None:
        assert "recon_agent" in BUILTIN_AGENTS
        assert "subdomain_agent" in BUILTIN_AGENTS
        assert "directory_enum_agent" in BUILTIN_AGENTS
        assert "code_analysis_agent" in BUILTIN_AGENTS
        assert "cloud_agent" in BUILTIN_AGENTS

    def test_exploitation_agents_present(self) -> None:
        assert "exploit_agent" in BUILTIN_AGENTS
        assert "web_exploitation_agent" in BUILTIN_AGENTS
        assert "auth_agent" in BUILTIN_AGENTS

    def test_post_exploitation_agents_present(self) -> None:
        assert "post_exploitation_agent" in BUILTIN_AGENTS
        assert "privilege_escalation_agent" in BUILTIN_AGENTS
        assert "ad_agent" in BUILTIN_AGENTS

    def test_evidence_agents_present(self) -> None:
        assert "evidence_collector" in BUILTIN_AGENTS
        assert "browser_agent" in BUILTIN_AGENTS
        assert "report_agent" in BUILTIN_AGENTS

    def test_all_agents_have_unique_ids(self) -> None:
        ids = list(BUILTIN_AGENTS.keys())
        assert len(ids) == len(set(ids))

    def test_all_agents_have_valid_clusters(self) -> None:
        for manifest in BUILTIN_AGENTS.values():
            assert isinstance(manifest.cluster, AgentCluster)

    def test_dangerous_agents_have_correct_permission(self) -> None:
        dangerous = ["post_exploitation_agent", "privilege_escalation_agent", "ad_agent"]
        for agent_id in dangerous:
            assert BUILTIN_AGENTS[agent_id].tool_permission_level == PermissionLevel.DANGEROUS

    def test_recon_agents_are_read_only(self) -> None:
        for manifest in BUILTIN_AGENTS.values():
            if manifest.cluster == AgentCluster.RECON:
                assert manifest.tool_permission_level == PermissionLevel.READ_ONLY
