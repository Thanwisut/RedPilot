#!/usr/bin/env python3
"""REDPILOT API server — FastAPI + WebSocket backend for tool execution.

Usage:
    python3 apps/api/run.py
    uv run python apps/api/run.py          # from project root
    uv run uvicorn redpilot_api.server:app  # alternative

Connects the TUI (running on port 8080 by default) to the Python backend
for real tool execution via the ToolRunner pipeline.

The server:
  - Listens on ws://localhost:8080 (WebSocket) for tool.execute messages
  - Serves REST endpoints at http://localhost:8080/config, /providers, etc.
  - Routes tool execution through ToolRunner → ScopeGuard → ApprovalGate → sandbox
"""

from __future__ import annotations

import logging
import sys

import uvicorn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    print(f"[redpilot] Starting REDPILOT API server on ws://localhost:{port}")
    print(f"[redpilot] WebSocket endpoint: ws://localhost:{port}/ws")
    uvicorn.run(
        "redpilot_api.server:app",
        host="0.0.0.0",
        port=port,
        log_level="info",
    )
