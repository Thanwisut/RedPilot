"""Tests for SubfinderAdapter — argv safety, output parsing, version drift.

Follows the same test patterns as the NmapAdapter tests.
"""

from __future__ import annotations

import pytest

from redpilot_tools.adapters.subfinder_adapter import SubfinderAdapter


class TestSubfinderAdapter:
    """SubfinderAdapter unit tests."""

    def setup_method(self) -> None:
        self.adapter = SubfinderAdapter()

    # ------------------------------------------------------------------
    # Manifest
    # ------------------------------------------------------------------

    def test_manifest_defined(self) -> None:
        assert self.adapter.manifest.name == "subfinder"
        assert self.adapter.manifest.category == "recon"
        assert self.adapter.manifest.binary == "subfinder"
        assert not self.adapter.manifest.dangerous
        assert not self.adapter.manifest.requires_approval

    def test_manifest_sandbox_profile(self) -> None:
        from redpilot_core.models.tool_manifest import SandboxProfile
        assert self.adapter.manifest.sandbox_profile == SandboxProfile.NETWORK_SCAN_STANDARD

    # ------------------------------------------------------------------
    # Argv safety — must always return list[str], never a shell string
    # ------------------------------------------------------------------

    def test_build_command_returns_list(self) -> None:
        argv = self.adapter.build_command(
            {"domain": "example.com"}, "/tmp/scratch",
        )
        assert isinstance(argv, list)
        assert all(isinstance(arg, str) for arg in argv)

    def test_build_command_contains_subfinder_binary(self) -> None:
        argv = self.adapter.build_command(
            {"domain": "example.com"}, "/tmp/scratch",
        )
        assert argv[0] == "subfinder"

    def test_build_command_has_domain_and_silent(self) -> None:
        argv = self.adapter.build_command(
            {"domain": "example.com"}, "/tmp/scratch",
        )
        assert "-d" in argv
        assert "example.com" in argv
        assert "-silent" in argv

    def test_build_command_no_shell_metacharacters(self) -> None:
        """Validate that shell metacharacters in domain are rejected."""
        dangerous_domains = [
            "example.com; rm -rf /",
            "example.com | id",
            "$(whoami).com",
            "example.com`id`",
            "example.com &",
        ]
        for domain in dangerous_domains:
            with pytest.raises(ValueError, match="not a valid hostname"):
                self.adapter.build_command(
                    {"domain": domain}, "/tmp/scratch",
                )

    def test_build_command_sources_flag(self) -> None:
        argv = self.adapter.build_command(
            {"domain": "test.com", "sources": "all"}, "/tmp/scratch",
        )
        assert "-all" in argv

    def test_build_command_default_sources_omitted(self) -> None:
        argv = self.adapter.build_command(
            {"domain": "test.com", "sources": "default"}, "/tmp/scratch",
        )
        assert "-all" not in argv

    def test_build_command_recursive(self) -> None:
        argv = self.adapter.build_command(
            {"domain": "test.com", "recursive": True}, "/tmp/scratch",
        )
        assert "-recursive" in argv

    def test_build_command_no_recursive_by_default(self) -> None:
        argv = self.adapter.build_command(
            {"domain": "test.com"}, "/tmp/scratch",
        )
        assert "-recursive" not in argv

    def test_build_command_max_time(self) -> None:
        argv = self.adapter.build_command(
            {"domain": "test.com", "max_time": 30}, "/tmp/scratch",
        )
        assert "-max-time" in argv
        idx = argv.index("-max-time")
        assert argv[idx + 1] == "30"

    def test_build_command_empty_domain_raises(self) -> None:
        with pytest.raises(ValueError, match="required"):
            self.adapter.build_command({"domain": ""}, "/tmp/scratch")

    def test_build_command_missing_domain_raises(self) -> None:
        with pytest.raises(ValueError, match="required"):
            self.adapter.build_command({}, "/tmp/scratch")

    # ------------------------------------------------------------------
    # Fuzz test — ensure no shell string slips through
    # ------------------------------------------------------------------

    def test_fuzz_argv_is_never_shell_string(self) -> None:
        """Exercise build_command with various valid inputs and verify
        every returned element is a plain string with no shell metacharacters."""
        test_cases = [
            {"domain": "example.com"},
            {"domain": "sub.example.com", "sources": "all"},
            {"domain": "a-b.example.com", "recursive": True, "max_time": 60},
            {"domain": "example.co.uk", "sources": "default"},
        ]
        shell_special = set(";&|`$(){}[]<>#!*?~")
        for args in test_cases:
            argv = self.adapter.build_command(args, "/tmp/scratch")
            assert isinstance(argv, list)
            for arg in argv:
                assert isinstance(arg, str)
                # No arg should contain shell special characters
                assert not shell_special.intersection(arg), (
                    f"Shell metacharacter found in argv element: {arg!r}"
                )

    # ------------------------------------------------------------------
    # Parse output
    # ------------------------------------------------------------------

    def test_parse_output_empty(self) -> None:
        parsed = self.adapter.parse_output("", "", 0, "/tmp/scratch")
        assert parsed == {"subdomains": [], "count": 0}

    def test_parse_output_single_domain(self) -> None:
        parsed = self.adapter.parse_output("mail.example.com\n", "", 0, "/tmp/scratch")
        assert parsed["count"] == 1
        assert parsed["subdomains"] == [{"host": "mail.example.com"}]

    def test_parse_output_multiple_domains(self) -> None:
        output = "mail.example.com\nwww.example.com\napi.example.com\n"
        parsed = self.adapter.parse_output(output, "", 0, "/tmp/scratch")
        assert parsed["count"] == 3
        assert len(parsed["subdomains"]) == 3

    def test_parse_output_deduplicates(self) -> None:
        stdout = "mail.example.com\nMAIL.example.com\nMail.Example.Com\n"
        parsed = self.adapter.parse_output(stdout, "", 0, "/tmp/scratch")
        assert parsed["count"] == 1  # All same host, case-insensitive
        assert parsed["subdomains"] == [{"host": "mail.example.com"}]

    def test_parse_output_skips_non_domain_lines(self) -> None:
        output = (
            "[INF] Loading config from /etc/subfinder/config.yaml\n"
            "mail.example.com\n"
            "[WRN] Some sources timed out\n"
            "www.example.com\n"
        )
        parsed = self.adapter.parse_output(output, "", 0, "/tmp/scratch")
        assert parsed["count"] == 2

    def test_parse_output_skips_bracketed_lines(self) -> None:
        stdout = "[2024-01-01] [INF] Starting scan\nmail.example.com\n"
        parsed = self.adapter.parse_output(stdout, "", 0, "/tmp/scratch")
        assert parsed["count"] == 1

    def test_parse_output_version_stderr_ignored(self) -> None:
        """Version info on stderr should not appear in parsed output."""
        parsed = self.adapter.parse_output(
            "mail.example.com",
            "[INF] Current Version: v2.14.0\n",
            0, "/tmp/scratch",
        )
        assert parsed["count"] == 1
        assert "Current Version" not in str(parsed)

    # ------------------------------------------------------------------
    # Version drift
    # ------------------------------------------------------------------

    def test_check_version_without_pin(self) -> None:
        # Create a separate adapter with no version pin to avoid mutating
        # the shared _SUBFINDER_MANIFEST class attribute (which would
        # break subsequent tests that depend on the pinned range).
        from redpilot_tools.adapters.subfinder_adapter import SubfinderAdapter as SA
        from redpilot_core.models.tool_manifest import ToolManifest
        no_pin_adapter = SA()
        no_pin_adapter.manifest = ToolManifest(
            name="subfinder",
            version_pinned=None,
        )
        assert no_pin_adapter.check_version("v2.14.0")

    def test_check_version_satisfies_range(self) -> None:
        # v2.14.0 satisfies >=2.14.0,<3.0.0
        assert self.adapter.check_version("v2.14.0")
        assert self.adapter.check_version("2.99.0")
        assert not self.adapter.check_version("3.0.0")
        assert not self.adapter.check_version("1.9.0")

    def test_check_version_rejects_leading_v_in_parse(self) -> None:
        # Our parser handles leading v
        assert self.adapter.check_version("v2.14.0")
        assert self.adapter.check_version("v2.99.0")
        assert not self.adapter.check_version("v3.0.0")

    # ------------------------------------------------------------------
    # Target validation
    # ------------------------------------------------------------------

    def test_validate_domain_accepts_valid(self) -> None:
        valid = [
            "example.com",
            "sub.example.com",
            "my-domain.example.com",
            "a.b.c.example.com",
        ]
        for domain in valid:
            self.adapter._validate_domain(domain)  # Should not raise

    def test_validate_domain_rejects_invalid(self) -> None:
        invalid = [
            "",
            "-example.com",
            "example.com-",
            "exa mple.com",
            "a" * 300 + ".com",  # Too long
        ]
        for domain in invalid:
            with pytest.raises(ValueError):
                self.adapter._validate_domain(domain)

    # ------------------------------------------------------------------
    # Domain-looks check
    # ------------------------------------------------------------------

    def test_looks_like_domain(self) -> None:
        assert SubfinderAdapter._looks_like_domain("mail.example.com")
        assert SubfinderAdapter._looks_like_domain("test.co.uk")
        assert not SubfinderAdapter._looks_like_domain("[INF] message")
        assert not SubfinderAdapter._looks_like_domain("(error) line")
        assert not SubfinderAdapter._looks_like_domain("nodots")
        assert not SubfinderAdapter._looks_like_domain("")

    # ------------------------------------------------------------------
    # Required capabilities (subfinder doesn't need raw sockets)
    # ------------------------------------------------------------------

    def test_required_capabilities_default(self) -> None:
        assert self.adapter.required_capabilities({}) == []
        assert self.adapter.required_capabilities({"domain": "test.com"}) == []
