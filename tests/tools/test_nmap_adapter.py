"""Tests for NmapAdapter — command construction, XML parsing, version checks."""

import pytest
from redpilot_tools.adapters.nmap_adapter import (
    NMAP_MANIFEST,
    NmapAdapter,
    _check_constraint,
    _parse_version,
    _satisfies_semver_range,
)

SAMPLE_NMAP_XML = """<?xml version="1.0"?>
<nmaprun scanner="nmap" args="nmap -sT -oX - scanme.nmap.org" start="12345">
  <scaninfo type="connect" protocol="tcp" numservices="1000"/>
  <host starttime="12345" endtime="12346">
    <status state="up" reason="syn-ack"/>
    <address addr="45.33.32.156" addrtype="ipv4"/>
    <ports>
      <port protocol="tcp" portid="22">
        <state state="open" reason="syn-ack" reason_ttl="0"/>
        <service name="ssh" method="table" conf="3"/>
      </port>
      <port protocol="tcp" portid="80">
        <state state="open" reason="syn-ack" reason_ttl="0"/>
        <service name="http" product="Apache httpd" version="2.4.58" method="probed" conf="10"/>
      </port>
      <port protocol="tcp" portid="443">
        <state state="filtered" reason="no-response" reason_ttl="0"/>
        <service name="https" method="table" conf="3"/>
      </port>
    </ports>
  </host>
  <runstats>
    <finished time="12346" timestr="..." elapsed="1.23" summary="Nmap done at ..."/>
    <hosts up="1" down="0" total="1"/>
  </runstats>
</nmaprun>"""


class TestNmapAdapter:
    """NmapAdapter command building and output parsing."""

    def setup_method(self) -> None:
        self.adapter = NmapAdapter()

    def test_build_command_defaults(self) -> None:
        argv = self.adapter.build_command(
            {"target": "10.0.0.1"},
            "/tmp/scratch",
        )
        assert argv[0] == "nmap"
        assert "-sT" in argv  # default scan type
        assert "-oX" in argv
        assert "-" in argv  # stdout
        assert "-T3" in argv  # default timing
        assert "--max-rate" in argv
        assert "100" in argv  # default rate limit
        assert argv[-1] == "10.0.0.1"

    def test_build_command_syn_scan(self) -> None:
        argv = self.adapter.build_command(
            {"target": "10.0.0.1", "scan_type": "syn"},
            "/tmp/scratch",
        )
        assert "-sS" in argv

    def test_build_command_udp_scan(self) -> None:
        argv = self.adapter.build_command(
            {"target": "10.0.0.1", "scan_type": "udp"},
            "/tmp/scratch",
        )
        assert "-sU" in argv

    def test_build_command_with_ports(self) -> None:
        argv = self.adapter.build_command(
            {"target": "10.0.0.1", "ports": "22,80,443"},
            "/tmp/scratch",
        )
        assert "-p" in argv
        p_idx = argv.index("-p")
        assert argv[p_idx + 1] == "22,80,443"

    def test_build_command_with_service_detection(self) -> None:
        argv = self.adapter.build_command(
            {"target": "10.0.0.1", "service_detection": True},
            "/tmp/scratch",
        )
        assert "-sV" in argv

    def test_build_command_timing_template(self) -> None:
        argv = self.adapter.build_command(
            {"target": "10.0.0.1", "timing_template": "T4"},
            "/tmp/scratch",
        )
        assert "-T4" in argv

    def test_build_command_cidr_target(self) -> None:
        argv = self.adapter.build_command(
            {"target": "10.0.0.0/24"},
            "/tmp/scratch",
        )
        assert argv[-1] == "10.0.0.0/24"

    def test_build_command_hostname_target(self) -> None:
        argv = self.adapter.build_command(
            {"target": "scanme.nmap.org"},
            "/tmp/scratch",
        )
        assert argv[-1] == "scanme.nmap.org"

    def test_build_command_invalid_target_raises(self) -> None:
        with pytest.raises(ValueError, match="not a valid"):
            self.adapter.build_command(
                {"target": "rm -rf /"},
                "/tmp/scratch",
            )

    def test_build_command_empty_target_raises(self) -> None:
        with pytest.raises(ValueError, match="required"):
            self.adapter.build_command(
                {"target": ""},
                "/tmp/scratch",
            )

    def test_build_command_never_contains_shell_metachar(self) -> None:
        """Fuzz test: shell metacharacters must be treated as literal args."""
        dangerous_inputs = [
            "; rm -rf /",
            "`whoami`",
            "$(cat /etc/passwd)",
            "10.0.0.1 | cat /etc/shadow",
            "10.0.0.1 && echo pwned",
        ]
        for target in dangerous_inputs:
            with pytest.raises(ValueError):
                self.adapter.build_command(
                    {"target": target},
                    "/tmp/scratch",
                )

    def test_parse_output_success(self) -> None:
        parsed = self.adapter.parse_output(
            SAMPLE_NMAP_XML, "", 0, "/tmp/scratch",
        )
        assert parsed["total_hosts"] == 1
        assert parsed["open_ports_count"] == 2
        assert len(parsed["ports"]) == 2

        # Check open ports
        ports = parsed["ports"]
        assert ports[0]["port"] == 22
        assert ports[0]["service"] == "ssh"
        assert ports[1]["port"] == 80
        assert ports[1]["service"] == "http"
        assert ports[1].get("version") == "2.4.58"

    def test_parse_output_filtered_port_excluded(self) -> None:
        """Filtered ports (not 'open') should not appear in the results."""
        parsed = self.adapter.parse_output(
            SAMPLE_NMAP_XML, "", 0, "/tmp/scratch",
        )
        port_ids = [p["port"] for p in parsed["ports"]]
        assert 443 not in port_ids  # filtered

    def test_parse_output_empty_xml(self) -> None:
        parsed = self.adapter.parse_output("", "", 0, "/tmp/scratch")
        assert parsed["ports"] == []

    def test_parse_output_malformed_xml(self) -> None:
        parsed = self.adapter.parse_output(
            "not valid xml<<>>>", "", 0, "/tmp/scratch",
        )
        assert parsed["ports"] == []

    def test_parse_output_scan_stats(self) -> None:
        parsed = self.adapter.parse_output(
            SAMPLE_NMAP_XML, "", 0, "/tmp/scratch",
        )
        assert parsed["scan_stats"]["type"] == "connect"
        assert parsed["scan_stats"]["protocol"] == "tcp"

    def test_manifest_is_correct(self) -> None:
        assert NMAP_MANIFEST.name == "nmap"
        assert NMAP_MANIFEST.sandbox_profile.value == "network_scan_standard"
        assert NMAP_MANIFEST.dangerous is False
        assert NMAP_MANIFEST.requires_approval is False
        assert NMAP_MANIFEST.rate_limit == {"requests_per_sec": 100}

    def test_check_version_correct(self) -> None:
        assert self.adapter.check_version("7.90")
        assert self.adapter.check_version("7.94")
        assert self.adapter.check_version("7.99")

    def test_check_version_out_of_range(self) -> None:
        assert not self.adapter.check_version("7.80")  # below >=7.90
        assert not self.adapter.check_version("8.0")   # at <8.0 boundary
        assert not self.adapter.check_version("8.1")    # above <8.0


class TestNmapVersionParsing:
    """Semver range matching helpers."""

    def test_parse_version(self) -> None:
        assert _parse_version("7.94") == (7, 94)
        assert _parse_version("v7.94") == (7, 94)
        assert _parse_version("1.2.3") == (1, 2, 3)

    def test_check_constraint(self) -> None:
        parsed = (7, 94)
        assert _check_constraint(parsed, ">=7.90")
        assert _check_constraint(parsed, "<8.0")
        assert not _check_constraint(parsed, ">=8.0")
        assert not _check_constraint(parsed, "<7.90")

    def test_satisfies_semver_range(self) -> None:
        assert _satisfies_semver_range("7.90", ">=7.90,<8.0")
        assert _satisfies_semver_range("7.94", ">=7.90,<8.0")
        assert _satisfies_semver_range("7.99", ">=7.90,<8.0")
        assert not _satisfies_semver_range("7.80", ">=7.90,<8.0")
        assert not _satisfies_semver_range("8.0", ">=7.90,<8.0")
        assert not _satisfies_semver_range("8.1", ">=7.90,<8.0")

    def test_satisfies_no_pin(self) -> None:
        assert _satisfies_semver_range("1.0", "1.0")
        assert not _satisfies_semver_range("2.0", "1.0")
