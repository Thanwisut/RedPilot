"""Tests for ToolManifest and SandboxProfile models."""

from redpilot_core.models.tool_manifest import SandboxProfile, ToolManifest


class TestSandboxProfile:
    """SandboxProfile enum values."""

    def test_profiles_exist(self) -> None:
        assert SandboxProfile.NETWORK_SCAN_STANDARD.value == "network_scan_standard"
        assert SandboxProfile.WEB_SCAN.value == "web_scan"
        assert SandboxProfile.EXPLOIT.value == "exploit"
        assert SandboxProfile.CODE_ANALYSIS.value == "code_analysis"
        assert SandboxProfile.BROWSER.value == "browser"


class TestToolManifest:
    """ToolManifest creation and permission inference."""

    def test_create_readonly_tool(self) -> None:
        manifest = ToolManifest(
            name="nmap",
            category="recon",
            binary="nmap",
            version_pinned="7.94",
            sandbox_profile=SandboxProfile.NETWORK_SCAN_STANDARD,
            description="Network exploration tool and security scanner",
        )
        assert manifest.name == "nmap"
        assert manifest.effective_permission_level == "read_only"
        assert not manifest.requires_approval
        assert not manifest.dangerous

    def test_create_dangerous_tool(self) -> None:
        manifest = ToolManifest(
            name="metasploit",
            category="exploitation",
            binary="msfconsole",
            sandbox_profile=SandboxProfile.EXPLOIT,
            dangerous=True,
            description="Metasploit exploitation framework",
        )
        assert manifest.dangerous
        assert manifest.requires_approval  # auto-set by dangerous flag
        assert manifest.effective_permission_level == "dangerous"

    def test_create_approval_required_tool(self) -> None:
        manifest = ToolManifest(
            name="sqlmap",
            category="exploitation",
            binary="sqlmap",
            sandbox_profile=SandboxProfile.WEB_SCAN,
            requires_approval=True,
            description="SQL injection automation tool",
        )
        assert not manifest.dangerous
        assert manifest.requires_approval
        assert manifest.effective_permission_level == "write"

    def test_manifest_entry_roundtrip(self) -> None:
        manifest = ToolManifest(
            name="nuclei",
            category="vulnerability_scan",
            binary="nuclei",
            version_pinned="3.3.x",
            input_schema={"targets": ["str"], "templates": ["str"]},
            output_parser="nuclei_json_parser",
            sandbox_profile=SandboxProfile.WEB_SCAN,
            requires_approval=False,
            rate_limit={"requests_per_sec": 50},
            dangerous=False,
            description="Fast vulnerability scanner based on YAML templates",
        )

        entry = manifest.to_manifest_entry()
        assert entry["name"] == "nuclei"
        assert entry["sandbox_profile"] == "web_scan"
        assert entry["rate_limit"]["requests_per_sec"] == 50

        restored = ToolManifest.from_manifest_entry(entry)
        assert restored.name == manifest.name
        assert restored.sandbox_profile == manifest.sandbox_profile
        assert restored.rate_limit == manifest.rate_limit
        assert restored.version_pinned == manifest.version_pinned
        assert restored.input_schema == manifest.input_schema

    def test_none_binary_for_python_tools(self) -> None:
        manifest = ToolManifest(
            name="custom_scanner",
            category="recon",
            binary=None,
            description="A pure-Python scanner",
        )
        assert manifest.binary is None

    def test_defaults(self) -> None:
        manifest = ToolManifest(name="test_tool")
        assert manifest.category == "general"
        assert manifest.sandbox_profile == SandboxProfile.NETWORK_SCAN_STANDARD
        assert not manifest.requires_approval
        assert not manifest.dangerous
