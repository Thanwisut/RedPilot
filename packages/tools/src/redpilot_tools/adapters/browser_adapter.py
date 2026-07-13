"""Browser automation adapter — Playwright MCP integration for evidence collection.

Per architecture doc §7, the Browser Agent provides UI-layer testing and
evidence collection via Playwright. Actions are exposed as tool calls
through the standard ToolRunner pipeline.

The adapter runs inside a Docker sandbox using the ``redpilot-browser``
image (based on ``mcr.microsoft.com/playwright`` with Playwright Python
and the browser CLI script pre-installed).

The communication flow:
1. ``build_command()`` constructs argv that runs the browser CLI script
2. The CLI script (``redpilot-browser``) takes JSON args and runs Playwright
3. ``parse_output()`` reads the JSON results from stdout

**Action tier system:**
- **read_only** (no approval needed if target passes ScopeGuard):
  ``navigate``, ``click``, ``type``, ``scroll``, ``screenshot``
- **dangerous** (always requires approval):
  ``execute_js``, ``upload_file``, ``download_file``

ScopeGuard validates browser targets as domain names (extended to support
URLs/hostnames, not just IPs/CIDRs — see ``scope_guard.py``).

Every browser action is logged to the audit log with URL, action,
timestamp, and screenshot reference.
"""

from __future__ import annotations

import json
import os
from typing import Any

from redpilot_core.models.tool_manifest import SandboxProfile, ToolManifest

from redpilot_tools.adapter import ToolAdapter

_BROWSER_ACTIONS = [
    "navigate",
    "click",
    "type",
    "scroll",
    "screenshot",
    "execute_js",
    "upload_file",
    "download_file",
]

BROWSER_MANIFEST = ToolManifest(
    name="browser",
    category="evidence",
    binary="redpilot-browser",
    version_pinned=None,
    input_schema={
        "action": {
            "type": "enum",
            "required": True,
            "values": _BROWSER_ACTIONS,
        },
        "url": {
            "type": "string",
            "required": False,
        },
        "selector": {
            "type": "string",
            "required": False,
        },
        "value": {
            "type": "string",
            "required": False,
        },
        "script": {
            "type": "string",
            "required": False,
        },
        "wait_until": {
            "type": "string",
            "required": False,
        },
    },
    output_parser="browser_output_parser",
    sandbox_profile=SandboxProfile.BROWSER,
    requires_approval=True,  # Safe default — all actions require approval
    dangerous=True,  # Some actions (execute_js, upload, download) are dangerous
    rate_limit=None,
    description=(
        "Browser automation using Playwright. Supports navigate, click, type, "
        "scroll, screenshot (read_only tier), and execute_js, upload_file, "
        "download_file (dangerous tier). All actions are logged with URL, "
        "timestamp, and screenshot reference.\n\n"
        "NOTE: All browser actions currently require approval (safest default). "
        "Per-action tier refinement (read_only for navigate/click/type/scroll/"
        "screenshot) requires a ToolRunner pipeline enhancement to check "
        "adapter.get_action_tier() at runtime."
    ),
)

# Per-action security tiers
_ACTION_TIERS: dict[str, str] = {
    "navigate": "read_only",
    "click": "read_only",
    "type": "read_only",
    "scroll": "read_only",
    "screenshot": "read_only",
    "execute_js": "dangerous",
    "upload_file": "dangerous",
    "download_file": "dangerous",
}


class BrowserAdapter(ToolAdapter):
    """Adapter for Playwright browser automation actions.

    Communicates with a Python-based browser CLI script that runs
    inside the Docker sandbox container (``redpilot-browser`` image).
    The script accepts JSON on the command line and returns JSON on stdout.

    Security tier varies per action:
    - navigate/click/type/scroll/screenshot: read_only (scope-checked)
    - execute_js/upload_file/download_file: dangerous (always approved)
    """

    manifest = BROWSER_MANIFEST

    def build_command(self, args: dict[str, Any], scratch_dir: str) -> list[str]:
        """Build a command for the browser CLI script.

        Constructs an argv that runs the ``redpilot-browser`` CLI script
        with a JSON string argument containing the action and parameters.

        The CLI script (inside the Docker container) parses the JSON,
        executes the requested Playwright action, and outputs JSON
        on stdout.

        Args:
            args: Tool arguments containing ``action`` and optional params.
            scratch_dir: Path to scratch directory for screenshots/output.

        Returns:
            An argv list for the sandbox to execute.

        Raises:
            ValueError: If action is unknown or required params are missing.
        """
        action = args.get("action", "")
        if action not in _BROWSER_ACTIONS:
            msg = f"Unknown browser action: '{action}'. Valid: {', '.join(_BROWSER_ACTIONS)}"
            raise ValueError(msg)

        # Build the JSON payload for the CLI script
        payload: dict[str, Any] = {
            "action": action,
            "url": args.get("url", ""),
            "selector": args.get("selector", ""),
            "value": args.get("value", ""),
            "script": args.get("script", ""),
            "output_dir": scratch_dir,
        }

        # Set BROWSER_OUTPUT_DIR environment variable via the CLI script
        # The CLI script uses this env var for screenshot output
        json_payload = json.dumps(payload)

        # Run the browser CLI script with the JSON payload as argument
        return [
            "python3", "/usr/local/bin/redpilot-browser", json_payload,
        ]

    def parse_output(
        self,
        stdout: str,
        stderr: str,
        exit_code: int,
        scratch_dir: str,
    ) -> dict[str, Any]:
        """Parse browser action output from the CLI script's JSON response.

        Args:
            stdout: JSON output from the browser CLI script.
            stderr: Browser CLI script stderr.
            exit_code: Process exit code.
            scratch_dir: Path to scratch directory (may contain screenshots).

        Returns:
            A dict with parsed results. For screenshots, includes a
            reference to the screenshot file.
        """
        result: dict[str, Any] = {
            "action": "",
            "success": exit_code == 0,
            "stdout": stdout,
            "stderr": stderr,
            "screenshot_ref": None,
            "data": None,
        }

        # Try to parse JSON output from the CLI script
        if stdout and stdout.strip():
            for line in stdout.strip().split("\n"):
                line = line.strip()
                if line.startswith("{"):
                    try:
                        parsed = json.loads(line)
                        result["action"] = parsed.get("action", "")
                        result["success"] = parsed.get("success", exit_code == 0)
                        result["data"] = parsed.get("data")
                        if parsed.get("error"):
                            result["error"] = parsed.get("error")
                            result["stderr"] = (stderr + "\n" + parsed["error"]).strip()
                    except json.JSONDecodeError:
                        pass

        # Check for screenshot file in scratch directory
        screenshot_path = os.path.join(scratch_dir, "screenshot.png")
        if os.path.exists(screenshot_path):
            result["screenshot_ref"] = screenshot_path
            result["screenshot_size_bytes"] = os.path.getsize(screenshot_path)

        return result

    @staticmethod
    def get_action_tier(action: str) -> str:
        """Get the security tier for a browser action.

        Args:
            action: The browser action name.

        Returns:
            ``"dangerous"`` for execute_js/upload_file/download_file,
            ``"read_only"`` for all other actions.
        """
        return _ACTION_TIERS.get(action, "read_only")

    @staticmethod
    def is_action_dangerous(action: str) -> bool:
        """Check if a browser action is classified as dangerous.

        Args:
            action: The browser action name.

        Returns:
            True if the action requires human approval.
        """
        return _ACTION_TIERS.get(action, "read_only") == "dangerous"

    @staticmethod
    def build_json_payload(args: dict[str, Any], scratch_dir: str) -> str:
        """Build the JSON payload that the browser CLI script expects.

        This is separated from ``build_command`` so tests can verify the
        payload structure without needing a Docker sandbox.

        Args:
            args: The tool arguments.
            scratch_dir: Scratch directory for output files.

        Returns:
            A JSON string that the CLI script can parse.
        """
        payload: dict[str, Any] = {
            "action": args.get("action", ""),
            "url": args.get("url", ""),
            "selector": args.get("selector", ""),
            "value": args.get("value", ""),
            "script": args.get("script", ""),
            "output_dir": scratch_dir,
        }
        return json.dumps(payload)

    @staticmethod
    def is_json_output(line: str) -> bool:
        """Check if a line of output looks like JSON (starts with '{')."""
        return line.strip().startswith("{")
