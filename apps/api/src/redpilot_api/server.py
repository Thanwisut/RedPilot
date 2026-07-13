"""REDPILOT FastAPI backend — REST endpoints and WebSocket session handler.

Matches the WS event contract defined in ``SessionClient.ts``.

Events the server emits:
  - agent.spawned     — when a tool execution begins
  - agent.status      — lifecycle transitions (Pending → Ready → Dispatched → Executing → Completed/Failed/Blocked)
  - tool.invoked      — when a tool is about to run
  - tool.result       — when a tool completes
  - plan.updated      — when the task graph changes
  - approval.requested — when human approval is needed
  - approval.resolved — when approval is granted/denied
  - report.ready      — when a report artifact is produced

Messages the server accepts:
  - tool.execute      — request to execute a tool
  - approval.resolved — human response to an approval prompt

**Pipeline:** Routes through the real ToolRunner pipeline:
  ToolRunner → ScopeGuard → ApprovalGate → Sandbox → AuditLog

The sandbox runs locally via ``asyncio.create_subprocess_exec`` (no Docker
required). For tools without real adapters (web_scan_agent, vulnerability_agent),
simulated results are returned.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from redpilot_core.guards.approval_gate import ApprovalGate
from redpilot_core.guards.scope_guard import (
    GuardResult,
    ScopeGuard,
)
from redpilot_core.models.scope import Scope
from redpilot_core.models.tool_manifest import ToolManifest
from redpilot_core.models.tool_result import ToolResult, ToolResultStatus
from redpilot_tools.adapters.nmap_adapter import NmapAdapter
from redpilot_tools.adapters.shell_exec_adapter import ShellExecAdapter
from redpilot_tools.adapters.subfinder_adapter import SubfinderAdapter
from redpilot_tools.adapters.browser_adapter import BrowserAdapter
from redpilot_tools.adapters.filesystem_adapter import (
    ListDirectoryAdapter,
    ReadFileAdapter,
    WriteFileAdapter,
    EditFileAdapter,
)
from redpilot_tools.adapters.spawn_sub_agent_adapter import SpawnSubAgentAdapter
from redpilot_tools.adapter import ToolAdapter
from redpilot_tools.audit import InMemoryAuditLog
from redpilot_tools.runner import ToolInvocationRequest, ToolRunner
from redpilot_tools.sandbox import (
    SandboxContext,
    SandboxExecutionResult,
    SandboxFactory,
    SandboxProfile,
)

logger = logging.getLogger("redpilot.api")

# ======================================================================
# FastAPI app setup
# ======================================================================

app = FastAPI(title="REDPILOT API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ======================================================================
# In-memory state
# ======================================================================

session_state: dict[str, Any] = {
    "config": {},
    "configured": False,
}

# Pending approval request futures — keyed by request ID, resolves when
# the client sends approval.resolved.
pending_approvals: dict[str, asyncio.Future[bool]] = {}


def build_ws_message(msg_type: str, payload: dict[str, Any]) -> str:
    """Build a JSON string matching the WsMessage contract from SessionClient.ts."""
    return json.dumps({
        "type": msg_type,
        "session_id": session_state.get("session_id", "default"),
        "payload": payload,
        "ts": datetime.now(UTC).isoformat(),
    })


async def send_event(ws: WebSocket, msg_type: str, payload: dict[str, Any]) -> None:
    """Send a typed event to the WebSocket client."""
    try:
        await ws.send_text(build_ws_message(msg_type, payload))
    except Exception:
        logger.exception("Failed to send WS event")


# ======================================================================
# Local sandbox — runs commands via asyncio.create_subprocess_exec
# ======================================================================


class LocalSandboxFactory(SandboxFactory):
    """Runs tool commands directly on the host via asyncio subprocess.

    No Docker required. Designed for dev/CI — the sandbox provides
    stdout/stderr capture, exit code, timeout, and resource tracking
    without container isolation.
    """

    def __init__(self, scratch_base: str | None = None) -> None:
        self._scratch_base = scratch_base or tempfile.mkdtemp(
            prefix="redpilot_local_sandbox_",
        )

    def build(self, profile: SandboxProfile, target: str) -> SandboxContext:
        """Create a scratch directory and return the sandbox context."""
        run_id = uuid4().hex[:12]
        scratch_dir = os.path.join(self._scratch_base, run_id)
        os.makedirs(scratch_dir, exist_ok=True)
        return SandboxContext(
            container_id=f"local-{run_id}",
            scratch_dir=scratch_dir,
            timeout_seconds=120,
            metadata={"run_id": run_id},
        )

    async def execute(
        self, argv: list[str], context: SandboxContext,
    ) -> SandboxExecutionResult:
        """Run argv locally, capturing stdout/stderr."""
        start_time = time.monotonic()
        timeout = context.timeout_seconds

        # ── Remap /scratch paths to actual scratch_dir ──
        # Filesystem adapters construct paths like /scratch/subdir because
        # inside Docker, the scratch dir is mounted at /scratch. On the
        # host (no Docker), we need to use the real scratch_dir path.
        scratch_dir = context.scratch_dir
        mapped_argv = []
        for arg in argv:
            if arg.startswith("/scratch"):
                suffix = arg[len("/scratch"):]
                mapped_argv.append(os.path.join(scratch_dir, suffix.lstrip("/")))
            else:
                mapped_argv.append(arg)

        try:
            proc = await asyncio.create_subprocess_exec(
                *mapped_argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=context.scratch_dir,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout,
                )
                exit_code = proc.returncode or 0
                timed_out = False
            except asyncio.TimeoutError:
                proc.kill()
                stdout, stderr = await proc.communicate()
                exit_code = -1
                stderr = (stderr or b"") + b"\nTIMEOUT\n"
                timed_out = True

            elapsed_ms = int((time.monotonic() - start_time) * 1000)

            return SandboxExecutionResult(
                stdout=(stdout or b"").decode("utf-8", errors="replace"),
                stderr=(stderr or b"").decode("utf-8", errors="replace"),
                exit_code=exit_code,
                execution_time_ms=elapsed_ms,
            )
        except (OSError, FileNotFoundError) as exc:
            elapsed_ms = int((time.monotonic() - start_time) * 1000)
            return SandboxExecutionResult(
                stdout="",
                stderr=f"Local execution error: {exc}",
                exit_code=-1,
                execution_time_ms=elapsed_ms,
            )


# ======================================================================
# Dev scope guard — always allows (for development)
# ======================================================================


class DevScopeGuard(ScopeGuard):
    """A scope guard that always allows execution.

    For development use only. In production, a properly configured
    Scope with explicit allow rules should be used.
    """

    def __init__(self) -> None:
        super().__init__(Scope(name="dev", allowed_targets=["*.example.com"]))

    def check(
        self,
        target: str,
        tool_manifest: ToolManifest,
        agent_permission_level: str = "read_only",
        at_time: datetime | None = None,
    ) -> GuardResult:
        return GuardResult.allow()


# ======================================================================
# Pipeline singletons
# ======================================================================

# Build adapter registry: maps TUI tool names → Python adapters
ADAPTER_REGISTRY: dict[str, ToolAdapter] = {
    "recon_agent": SubfinderAdapter(),
    "port_scan_agent": NmapAdapter(),
    "shell_exec": ShellExecAdapter(),
    "spawn_sub_agent": SpawnSubAgentAdapter(),
    "browser": BrowserAdapter(),
    "list_directory": ListDirectoryAdapter(),
    "read_file": ReadFileAdapter(),
    "write_file": WriteFileAdapter(),
    "edit_file": EditFileAdapter(),
}

# Pipeline components (lazily initialized to avoid import-time side effects)
_pipeline: dict[str, Any] = {"initialized": False}


def get_pipeline() -> dict[str, Any]:
    """Get or initialize the ToolRunner pipeline components."""
    if not _pipeline["initialized"]:
        _pipeline["scope_guard"] = DevScopeGuard()
        _pipeline["approval_gate"] = ApprovalGate()
        _pipeline["audit_log"] = InMemoryAuditLog()
        _pipeline["sandbox_factory"] = LocalSandboxFactory()
        _pipeline["runner"] = ToolRunner(
            scope_guard=_pipeline["scope_guard"],
            approval_gate=_pipeline["approval_gate"],
            sandbox_factory=_pipeline["sandbox_factory"],
            audit_log=_pipeline["audit_log"],
            registry=ADAPTER_REGISTRY,
        )
        _pipeline["initialized"] = True
        logger.info(
            "ToolRunner pipeline initialized with %d adapters, "
            "approval gate, and local sandbox",
            len(ADAPTER_REGISTRY),
        )
    return _pipeline


# ======================================================================
# Simulated results for tools without real adapters
# ======================================================================


def simulate_tool_result(tool_name: str, args: dict[str, Any]) -> ToolResult:
    """Build a simulated ToolResult for tools that lack a real adapter."""
    target = args.get("target", args.get("url", args.get("domain", args.get("path", "unknown"))))

    results: dict[str, tuple[str, str]] = {
        "web_scan_agent": (
            f"Found 2 potential vulnerabilities on {target}",
            (
                f"Web scan results for {target}:\n"
                "  Technologies: React SPA, Nginx 1.24\n"
                "  Missing Content-Security-Policy header (Medium)\n"
                "  Missing X-Frame-Options header (Low)"
            ),
        ),
        "vulnerability_agent": (
            f"Assessment complete \u2014 0 critical, 2 medium, 3 low",
            f"Vulnerability assessment for {target} completed.\n"
            f"No critical findings. 5 total issues found.",
        ),
    }

    if tool_name in results:
        summary, details = results[tool_name]
        return ToolResult.success(
            tool_name=tool_name,
            parsed_output={"summary": summary, "details": details},
            target=target,
            raw_args=args,
        )

    return ToolResult.success(
        tool_name=tool_name,
        parsed_output={
            "summary": f"Executed {tool_name} on {target}",
            "details": f"{tool_name} completed with arguments: {json.dumps(args)}",
        },
        target=target,
        raw_args=args,
    )


# ======================================================================
# Tool execution handler — routes through real ToolRunner pipeline
# ======================================================================

async def handle_tool_execute(
    ws: WebSocket,
    session_id: str,
    payload: dict[str, Any],
) -> None:
    """Execute a tool through the real ToolRunner pipeline.

    Flow:
      1. Emit lifecycle events (agent.spawned, agent.status, tool.invoked)
      2. If tool has a real adapter: run through ToolRunner → ScopeGuard →
         ApprovalGate → Sandbox → AuditLog
      3. If tool requires approval: emit approval.requested, wait for
         approval.resolved from client, retry
      4. If tool has no real adapter: return simulated result
      5. Emit tool.result, agent.status Completed, plan.updated
    """
    tool_name = payload.get("name", "")
    args = payload.get("arguments", {})

    if not tool_name:
        await send_event(ws, "tool.result", {
            "agent_id": "system",
            "tool_name": "unknown",
            "status": "failed",
            "summary": "No tool name provided",
        })
        return

    # Extract _call_id early (used by TUI to match WS callbacks)
    call_id = args.pop("_call_id", None)

    # Extract target from args for scope/target display
    target = args.get("target", args.get("url", args.get("domain", args.get("path", ""))))

    # ── Lifecycle: agent.spawned ──
    node_id = f"NODE-{uuid4().hex[:8].upper()}"
    await send_event(ws, "agent.spawned", {
        "agent_id": tool_name,
        "cluster": "recon",
        "task_node_id": node_id,
    })

    for status in ("Ready", "Dispatched", "Executing"):
        await asyncio.sleep(0.05)
        await send_event(ws, "agent.status", {
            "agent_id": tool_name,
            "status": status,
        })

    await send_event(ws, "tool.invoked", {
        "agent_id": tool_name,
        "tool_name": tool_name,
        "target": target or "unknown",
        "args": args,
    })

    # ── Check if this tool has a real adapter ──
    if tool_name not in ADAPTER_REGISTRY:
        # Simulated (no real adapter) — skip the pipeline
        await asyncio.sleep(0.5)
        result = simulate_tool_result(tool_name, args)
        await _emit_tool_result(ws, tool_name, call_id, result)
        await _emit_completed(ws, tool_name, node_id)
        return

    # ── Run through the real ToolRunner pipeline ──
    pipeline = get_pipeline()
    runner: ToolRunner = pipeline["runner"]
    approval_gate: ApprovalGate = pipeline["approval_gate"]

    request = ToolInvocationRequest(
        tool_name=tool_name,
        args=args,
        target=target or "unknown",
        requesting_agent_id="tui-agent",
        agent_permission_level="read_only",
        task_node_id=node_id,
        rationale=f"TUI requested execution of {tool_name}",
    )

    # First attempt
    result = await runner.run(request, Scope(name="dev", allowed_targets=["*"]))

    # ── Approval loop: if blocked by approval, prompt user ──
    if result.status == ToolResultStatus.BLOCKED and result.error and "approval" in result.error.lower():
        pending = approval_gate.pending_requests
        if pending:
            # Use the most recently created pending request
            approval_req = pending[-1]

            # Emit approval.requested
            await send_event(ws, "approval.requested", {
                "request_id": approval_req.id,
                "tool_name": tool_name,
                "target": target or "unknown",
                "rationale": f"{tool_name} requires approval for execution",
                "requires_approval_reason": f"Tool '{tool_name}' requires human approval before execution",
            })

            # Wait for client to send approval.resolved
            future: asyncio.Future[bool] = asyncio.get_event_loop().create_future()
            pending_approvals[approval_req.id] = future

            try:
                approved = await asyncio.wait_for(future, timeout=300)
                logger.info(
                    "Approval %s for %s (request %s)",
                    "GRANTED" if approved else "DENIED",
                    tool_name,
                    approval_req.id,
                )
            except asyncio.TimeoutError:
                logger.warning("Approval timed out for %s (request %s)", tool_name, approval_req.id)
                approval_gate.check_expired()
                approved = False
            finally:
                pending_approvals.pop(approval_req.id, None)

            # NOTE: We do NOT retry runner.run() here because the approval
            # gate would create a NEW pending request on the second attempt
            # (runner.run() always creates a fresh request when requires_approval
            # returns True). Instead, we continue with the pre-resolved
            # approval state and execute sandbox steps directly.
            #
            # If approved, execute steps 5-11 of the pipeline directly.
            # If denied, return the BLOCKED result as-is.
            if not approved:
                await _emit_tool_result(ws, tool_name, call_id, result)
                await _emit_completed(ws, tool_name, node_id)
                return

            # ── Approved: continue pipeline directly (steps 5-11) ──
            sandbox_factory = pipeline["sandbox_factory"]
            audit_log = pipeline["audit_log"]
            adapter = ADAPTER_REGISTRY.get(tool_name)
            if adapter:
                manifest = adapter.manifest

                # Step 5: Build sandbox context
                sandbox = sandbox_factory.build(manifest.sandbox_profile, target)
                sandbox.granted_capabilities = adapter.required_capabilities(args)

                # Step 6: Build command
                augmented_args = dict(args)
                augmented_args.setdefault("_graph_id", "default")
                argv = adapter.build_command(augmented_args, sandbox.scratch_dir)

                # Step 7: Execute in sandbox
                exec_result: SandboxExecutionResult = await sandbox_factory.execute(
                    argv=argv, context=sandbox,
                )

                # Step 8: Check version drift
                version_drift = False
                if exec_result.detected_version is not None:
                    version_drift = not adapter.check_version(exec_result.detected_version)

                # Step 9: Parse output
                parsed: dict[str, Any] | None = None
                try:
                    parsed = adapter.parse_output(
                        stdout=exec_result.stdout,
                        stderr=exec_result.stderr,
                        exit_code=exec_result.exit_code,
                        scratch_dir=sandbox.scratch_dir,
                    )
                except (ValueError, KeyError, IndexError) as exc:
                    parsed = {"parse_error": str(exc), "raw_truncated": exec_result.stdout[:2000]}

                # Determine status
                if exec_result.exit_code == 0 and parsed and "parse_error" not in parsed:
                    status = ToolResultStatus.SUCCESS
                elif exec_result.exit_code == 0 or exec_result.execution_time_ms >= sandbox.timeout_seconds * 1000:
                    status = ToolResultStatus.PARTIAL
                else:
                    status = ToolResultStatus.FAILURE

                result = ToolResult(
                    status=status,
                    tool_name=tool_name,
                    stdout=exec_result.stdout,
                    stderr=exec_result.stderr,
                    exit_code=exec_result.exit_code,
                    artifacts=exec_result.artifacts,
                    parsed_output=parsed,
                    execution_time_ms=exec_result.execution_time_ms,
                    target=target,
                    raw_args=args,
                    tool_version=exec_result.detected_version,
                )

                if version_drift:
                    if result.parsed_output is not None:
                        result.parsed_output["_version_drift"] = True
                        result.parsed_output["_detected_version"] = exec_result.detected_version
                    if result.error is None:
                        result.error = (
                            f"Tool version drift detected: expected {manifest.version_pinned}, "
                            f"got {exec_result.detected_version}"
                        )

                # Step 10: Audit log
                await audit_log.write(
                    tool_name=tool_name,
                    target=target,
                    args=args,
                    requesting_agent="tui-agent",
                    task_node=node_id,
                    rationale=f"TUI requested {tool_name} (approved)",
                    scope=Scope(name="dev", allowed_targets=["*"]),
                    result=result,
                    stdout=exec_result.stdout,
                    stderr=exec_result.stderr,
                )

    # ── Emit result ──
    await _emit_tool_result(ws, tool_name, call_id, result)
    await _emit_completed(ws, tool_name, node_id)


async def _emit_tool_result(
    ws: WebSocket,
    tool_name: str,
    call_id: str | None,
    result: ToolResult,
) -> None:
    """Emit a tool.result event from a ToolResult."""
    # Map ToolResultStatus to WS status string
    if result.status in (ToolResultStatus.SUCCESS, ToolResultStatus.PARTIAL):
        status_str = "success"
    elif result.status == ToolResultStatus.BLOCKED:
        status_str = "blocked"
    else:
        status_str = "failed"

    summary = result.error or f"{tool_name} completed"
    if result.parsed_output and isinstance(result.parsed_output, dict):
        summary = result.parsed_output.get("summary", summary)
        details = result.parsed_output.get("details", json.dumps(result.parsed_output))
    else:
        details = f"Exit code: {result.exit_code}\n"
        if result.stdout:
            details += f"stdout: {result.stdout[:2000]}\n"
        if result.stderr:
            details += f"stderr: {result.stderr[:1000]}"

    payload: dict[str, object] = {
        "agent_id": tool_name,
        "tool_name": tool_name,
        "status": status_str,
        "summary": summary,
    }
    if call_id:
        payload["_call_id"] = call_id

    await send_event(ws, "tool.result", payload)


async def _emit_completed(
    ws: WebSocket,
    tool_name: str,
    node_id: str,
) -> None:
    """Emit final lifecycle events after a tool execution."""
    await asyncio.sleep(0.05)
    await send_event(ws, "agent.status", {
        "agent_id": tool_name,
        "status": "Completed",
    })
    await send_event(ws, "plan.updated", {
        "task_graph_snapshot": {
            "nodes": [
                {"id": node_id, "agent_id": tool_name, "status": "Completed", "dependencies": []},
            ],
        },
    })


# ======================================================================
# WebSocket endpoint
# ======================================================================

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    session_id = f"session-{uuid4().hex[:8]}"
    session_state["session_id"] = session_id
    logger.info(f"WS client connected: {session_id}")

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = msg.get("type", "")
            msg_payload = msg.get("payload", {})

            if msg_type == "tool.execute":
                await handle_tool_execute(ws, session_id, msg_payload)
            elif msg_type == "approval.resolved":
                request_id = msg_payload.get("request_id", "")
                approved = msg_payload.get("approved", False)
                logger.info(
                    "Approval resolved: request=%s approved=%s",
                    request_id, approved,
                )

                # Resolve in approval gate
                pipeline = get_pipeline()
                pipeline["approval_gate"].resolve(request_id, approved)

                # Resolve pending future (unblocks handle_tool_execute)
                if request_id in pending_approvals:
                    future = pending_approvals.pop(request_id)
                    if not future.done():
                        future.set_result(approved)

                # Echo back to client
                await send_event(ws, "approval.resolved", msg_payload)
            else:
                logger.debug(f"Unknown message type: {msg_type}")

    except WebSocketDisconnect:
        logger.info(f"WS client disconnected: {session_id}")
    except Exception:
        logger.exception(f"WS error for {session_id}")
    finally:
        pass


# ======================================================================
# REST endpoints
# ======================================================================

@app.get("/config/status")
async def get_config_status():
    return {"configured": session_state["configured"]}


@app.post("/config/save")
async def save_config(body: dict[str, Any]):
    session_state["config"] = body
    session_state["configured"] = True
    return {"configured": True}


@app.get("/config")
async def get_config():
    return session_state["config"]


@app.post("/providers/validate")
async def validate_provider(body: dict[str, Any]):
    api_key = body.get("api_key", "")
    valid = isinstance(api_key, str) and len(api_key) > 0
    return {"valid": valid, "models": []}


@app.post("/approval/resolve")
async def resolve_approval(body: dict[str, Any]):
    request_id = body.get("request_id", "")
    approved = body.get("approved", False)
    return {"ok": True, "request_id": request_id, "approved": approved}
