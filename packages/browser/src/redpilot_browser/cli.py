#!/usr/bin/env python3
"""Playwright browser CLI — runs inside the Docker sandbox container.

Accepts a JSON action on the command line (or stdin), executes it via
Playwright's Python API, and outputs structured JSON results on stdout.

Usage:
    python3 browser_cli.py '{"action": "navigate", "url": "https://example.com"}'
    python3 browser_cli.py '{"action": "screenshot", "url": "https://example.com"}'
    python3 browser_cli.py '{"action": "click", "selector": "#submit"}'
    python3 browser_cli.py '{"action": "type", "selector": "#search", "value": "hello"}'
    python3 browser_cli.py '{"action": "execute_js", "script": "document.title"}'

Actions:
    navigate   — Navigate to a URL
    screenshot — Take a screenshot of the current page
    click      — Click an element matching a CSS selector
    type       — Type text into an element
    scroll     — Scroll the page
    execute_js — Execute arbitrary JavaScript in the page context

Output:
    JSON with keys: success, action, data, error

The script opens a headless Chromium browser for each invocation.
A persistent browser context can be achieved by passing --persist-dir
with a directory path to save/load browser state between invocations.
"""

import json
import os
import sys
import time
from pathlib import Path


def parse_args() -> dict:
    """Parse action arguments from command line or stdin."""
    if len(sys.argv) > 1:
        raw = sys.argv[1]
    else:
        raw = sys.stdin.read()

    if not raw or not raw.strip():
        msg = "No input provided. Pass a JSON action as argument or via stdin."
        return {"error": msg}

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        msg = f"Invalid JSON input: {exc}"
        return {"error": msg}


def get_output_dir(action_args: dict) -> str:
    """Get the output directory for screenshots and artifacts.

    Priority order:
    1. ``output_dir`` from the JSON payload (set by BrowserAdapter)
    2. ``BROWSER_OUTPUT_DIR`` environment variable
    3. ``/scratch`` (the sandbox mount point)
    """
    output_dir = (
        action_args.get("output_dir")
        or os.environ.get("BROWSER_OUTPUT_DIR")
        or "/scratch"
    )
    try:
        Path(output_dir).mkdir(parents=True, exist_ok=True)
    except (OSError, PermissionError):
        # Fall back to a temp directory if the configured dir is not writable
        import tempfile
        output_dir = tempfile.mkdtemp(prefix="browser_output_")
    return output_dir


async def run_action(action_args: dict) -> dict:
    """Execute a browser action using Playwright.

    Args:
        action_args: Dict with 'action' key and action-specific params.

    Returns:
        Dict with success, action, data, and optional error.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return {
            "success": False,
            "error": (
                "Playwright Python package not installed. "
                "Run: pip install playwright && playwright install chromium"
            ),
        }

    action = action_args.get("action", "")
    url = action_args.get("url", "")
    selector = action_args.get("selector", "")
    value = action_args.get("value", "")
    script = action_args.get("script", "")
    output_dir = get_output_dir(action_args)

    result: dict = {
        "success": False,
        "action": action,
        "data": None,
        "error": None,
    }

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        try:
            if action == "navigate":
                if not url:
                    result["error"] = "URL is required for navigate action"
                    return result
                response = await page.goto(url, wait_until="networkidle")
                result["data"] = {
                    "url": page.url,
                    "title": await page.title(),
                    "status_code": response.status if response else None,
                }
                result["success"] = True

            elif action == "screenshot":
                if url:
                    await page.goto(url, wait_until="networkidle")
                # Wait a moment for rendering
                await page.wait_for_timeout(500)
                screenshot_path = os.path.join(output_dir, "screenshot.png")
                await page.screenshot(path=screenshot_path, full_page=True)
                await page.wait_for_timeout(100)
                file_size = os.path.getsize(screenshot_path) if os.path.exists(screenshot_path) else 0
                result["data"] = {
                    "screenshot_path": screenshot_path,
                    "file_size_bytes": file_size,
                    "url": page.url,
                    "title": await page.title(),
                }
                result["success"] = True

            elif action == "click":
                if not selector:
                    result["error"] = "Selector is required for click action"
                    return result
                await page.click(selector)
                await page.wait_for_load_state("networkidle")
                result["data"] = {
                    "url": page.url,
                    "title": await page.title(),
                    "clicked_selector": selector,
                }
                result["success"] = True

            elif action == "type":
                if not selector or value is None:
                    result["error"] = "Selector and value are required for type action"
                    return result
                await page.fill(selector, str(value))
                await page.wait_for_timeout(100)
                result["data"] = {
                    "filled_selector": selector,
                    "value": value,
                }
                result["success"] = True

            elif action == "scroll":
                await page.evaluate("window.scrollBy(0, window.innerHeight)")
                await page.wait_for_timeout(200)
                result["data"] = {
                    "scroll_y": await page.evaluate("window.scrollY"),
                }
                result["success"] = True

            elif action == "execute_js":
                if not script:
                    result["error"] = "Script is required for execute_js action"
                    return result
                js_result = await page.evaluate(script)
                result["data"] = {
                    "result": js_result,
                    "script": script,
                }
                result["success"] = True

            else:
                result["error"] = f"Unknown browser action: '{action}'"

        except Exception as exc:
            result["error"] = str(exc)
            result["success"] = False

        finally:
            await browser.close()

    return result


def main() -> None:
    """Entry point for the browser CLI."""
    args = parse_args()
    if "error" in args:
        print(json.dumps({"success": False, "error": args["error"]}))
        sys.exit(1)

    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        result = loop.run_until_complete(run_action(args))
        print(json.dumps(result, default=str))
        if not result.get("success", False):
            sys.exit(1)
    finally:
        loop.close()


if __name__ == "__main__":
    main()
