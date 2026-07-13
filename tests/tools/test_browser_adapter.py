"""Tests for BrowserAdapter — command construction, JSON parsing, manifest.

The browser adapter now emits argv that runs the ``redpilot-browser`` CLI
script inside the Docker sandbox. These tests verify the adapter's command
construction, JSON payload format, and output parsing, without needing
a running Docker container or Playwright.
"""

import json

import pytest
from redpilot_tools.adapters.browser_adapter import (
    BROWSER_MANIFEST,
    BrowserAdapter,
)


class TestBrowserAdapter:
    """BrowserAdapter command building and output parsing."""

    def setup_method(self) -> None:
        self.adapter = BrowserAdapter()

    # ------------------------------------------------------------------
    # Manifest
    # ------------------------------------------------------------------

    def test_manifest_is_correct(self) -> None:
        assert BROWSER_MANIFEST.name == "browser"
        assert BROWSER_MANIFEST.category == "evidence"
        assert BROWSER_MANIFEST.dangerous is True
        assert BROWSER_MANIFEST.requires_approval is True
        assert BROWSER_MANIFEST.sandbox_profile.value == "browser"

    def test_manifest_binary_is_redpilot_browser(self) -> None:
        assert BROWSER_MANIFEST.binary == "redpilot-browser"

    # ------------------------------------------------------------------
    # Build command — argv construction
    # ------------------------------------------------------------------

    def test_build_command_navigate(self) -> None:
        argv = self.adapter.build_command(
            {"action": "navigate", "url": "https://example.com"},
            "/tmp/scratch",
        )
        assert argv[0] == "python3"
        assert "/usr/local/bin/redpilot-browser" in argv[1]
        # The JSON payload should be the third argument
        payload = json.loads(argv[2])
        assert payload["action"] == "navigate"
        assert payload["url"] == "https://example.com"

    def test_build_command_screenshot(self) -> None:
        argv = self.adapter.build_command(
            {"action": "screenshot"},
            "/tmp/scratch",
        )
        payload = json.loads(argv[2])
        assert payload["action"] == "screenshot"
        assert payload["output_dir"] == "/tmp/scratch"

    def test_build_command_click(self) -> None:
        argv = self.adapter.build_command(
            {"action": "click", "selector": "#submit-btn"},
            "/tmp/scratch",
        )
        payload = json.loads(argv[2])
        assert payload["action"] == "click"
        assert payload["selector"] == "#submit-btn"

    def test_build_command_type(self) -> None:
        argv = self.adapter.build_command(
            {"action": "type", "selector": "#search", "value": "hello"},
            "/tmp/scratch",
        )
        payload = json.loads(argv[2])
        assert payload["action"] == "type"
        assert payload["selector"] == "#search"
        assert payload["value"] == "hello"

    def test_build_command_execute_js(self) -> None:
        argv = self.adapter.build_command(
            {"action": "execute_js", "script": "document.title"},
            "/tmp/scratch",
        )
        payload = json.loads(argv[2])
        assert payload["action"] == "execute_js"
        assert payload["script"] == "document.title"

    def test_build_command_scroll(self) -> None:
        argv = self.adapter.build_command(
            {"action": "scroll"},
            "/tmp/scratch",
        )
        payload = json.loads(argv[2])
        assert payload["action"] == "scroll"

    def test_build_command_unknown_action_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown browser action"):
            self.adapter.build_command(
                {"action": "nonexistent"},
                "/tmp/scratch",
            )

    def test_build_command_payload_always_includes_output_dir(self) -> None:
        argv = self.adapter.build_command(
            {"action": "navigate", "url": "https://example.com"},
            "/custom/scratch/path",
        )
        payload = json.loads(argv[2])
        assert payload["output_dir"] == "/custom/scratch/path"

    # ------------------------------------------------------------------
    # JSON payload construction (tested separately)
    # ------------------------------------------------------------------

    def test_build_json_payload_navigate(self) -> None:
        payload = json.loads(BrowserAdapter.build_json_payload(
            {"action": "navigate", "url": "https://example.com"},
            "/scratch",
        ))
        assert payload["action"] == "navigate"
        assert payload["url"] == "https://example.com"
        assert payload["output_dir"] == "/scratch"

    def test_build_json_payload_defaults(self) -> None:
        """Missing optional fields should default to empty strings."""
        payload = json.loads(BrowserAdapter.build_json_payload(
            {"action": "navigate"},
            "/scratch",
        ))
        assert payload["url"] == ""
        assert payload["selector"] == ""
        assert payload["value"] == ""
        assert payload["script"] == ""

    # ------------------------------------------------------------------
    # Output parsing
    # ------------------------------------------------------------------

    def test_parse_output_success(self) -> None:
        stdout = json.dumps({
            "success": True,
            "action": "navigate",
            "data": {
                "url": "https://example.com",
                "title": "Example Domain",
                "status_code": 200,
            },
        })
        parsed = self.adapter.parse_output(
            stdout, "", 0, "/tmp/scratch",
        )
        assert parsed["success"] is True
        assert parsed["action"] == "navigate"
        assert parsed["data"]["url"] == "https://example.com"
        assert parsed["data"]["title"] == "Example Domain"

    def test_parse_output_failure(self) -> None:
        stdout = json.dumps({
            "success": False,
            "action": "navigate",
            "error": "Timeout navigating to URL",
        })
        parsed = self.adapter.parse_output(
            stdout, "error output", 1, "/tmp/scratch",
        )
        assert parsed["success"] is False
        assert "Timeout" in (parsed.get("error") or "")

    def test_parse_output_empty_stdout(self) -> None:
        """Empty stdout should still produce a result with exit code check."""
        parsed = self.adapter.parse_output(
            "", "", 0, "/tmp/scratch",
        )
        assert parsed["success"] is True  # exit code 0
        assert parsed["stdout"] == ""

    def test_parse_output_non_json_stdout(self) -> None:
        """Non-JSON stdout should fall back to exit code check."""
        parsed = self.adapter.parse_output(
            "Not JSON output\nSome other text",
            "", 0, "/tmp/scratch",
        )
        assert parsed["success"] is True  # exit code 0

    def test_parse_output_stdout_with_stderr(self) -> None:
        """Error in stderr should be captured."""
        parsed = self.adapter.parse_output(
            json.dumps({"success": False, "error": "Navigation failed"}),
            "Playwright error trace",
            1,
            "/tmp/scratch",
        )
        assert parsed["success"] is False
        assert parsed["stderr"] is not None

    # ------------------------------------------------------------------
    # Action tiers
    # ------------------------------------------------------------------

    def test_action_tiers(self) -> None:
        assert BrowserAdapter.get_action_tier("navigate") == "read_only"
        assert BrowserAdapter.get_action_tier("click") == "read_only"
        assert BrowserAdapter.get_action_tier("type") == "read_only"
        assert BrowserAdapter.get_action_tier("scroll") == "read_only"
        assert BrowserAdapter.get_action_tier("screenshot") == "read_only"
        assert BrowserAdapter.get_action_tier("execute_js") == "dangerous"
        assert BrowserAdapter.get_action_tier("upload_file") == "dangerous"
        assert BrowserAdapter.get_action_tier("download_file") == "dangerous"

    def test_is_action_dangerous(self) -> None:
        assert BrowserAdapter.is_action_dangerous("execute_js") is True
        assert BrowserAdapter.is_action_dangerous("upload_file") is True
        assert BrowserAdapter.is_action_dangerous("download_file") is True
        assert BrowserAdapter.is_action_dangerous("navigate") is False
        assert BrowserAdapter.is_action_dangerous("screenshot") is False
