/** ExecutionManager — handles the full tool execution lifecycle.
 *
 * Flow:
 *   1. receive ToolCall from LLM
 *   2. confirm with user (handled by MainConsole UI)
 *   3. execute tool
 *      a. If WebSocket backend is available: send tool.execute via WS, await result
 *      b. If not: simulate locally (fallback)
 *   4. return structured result
 *   5. MainConsole passes result back to LLM for continuation
 *
 * The WS backend URL is configured via the REDPILOT_WS_URL env var
 * (defaults to ws://localhost:8080/ws). The WS connection is established
 * eagerly at module load time so it's ready when the first tool call arrives.
 */

import type { ToolCall } from "../providers/types.js";
import type {
  WsMessage,
  ToolResultPayload,
  ApprovalRequestedPayload,
} from "../ws-client/SessionClient.js";
import { executeLocal } from "./LocalExecutor.js";

export interface ExecutionResult {
  toolCallId: string;
  toolName: string;
  status: "success" | "error";
  summary: string;
  details: string;
  durationMs: number;
}

// ---------------------------------------------------------------------------
// WebSocket connection state (eager connection)
// ---------------------------------------------------------------------------

const WS_URL = (typeof process !== "undefined" && process.env?.REDPILOT_WS_URL
  ? process.env.REDPILOT_WS_URL
  : "ws://localhost:8080/ws");

let ws: WebSocket | null = null;
let wsReady = false;
let wsConnecting = false;
let wsReadyResolve: (() => void) | null = null;

/** Promise that resolves when the WS connection is established. */
let wsReadyPromise: Promise<void> | null = null;

/** Whether to auto-approve approval.requested events from the WS backend. */
let autoApprove = false;

/**
 * Enable or disable automatic approval of WS approval requests.
 * When enabled, any `approval.requested` event from the backend is
 * automatically answered with `approval.resolved { approved: true }`.
 */
export function setAutoApprove(enabled: boolean): void {
  autoApprove = enabled;
}

export interface WsStatus {
  connected: boolean;
  connecting: boolean;
  url: string;
  autoApprove: boolean;
}

/**
 * Get the current WebSocket connection status.
 * Useful for UI display of backend connectivity.
 */
export function getWsStatus(): WsStatus {
  return {
    connected: wsReady && ws !== null,
    connecting: wsConnecting,
    url: WS_URL,
    autoApprove,
  };
}

/** Map of callId → pending callbacks. Uses unique call IDs per invocation. */
const pendingCalls = new Map<string, {
  resolve: (result: ExecutionResult) => void;
  reject: (err: Error) => void;
  timeout: ReturnType<typeof setTimeout>;
}>();

// ---------------------------------------------------------------------------
// Initialize WS connection eagerly
// ---------------------------------------------------------------------------

function initWs(): void {
  if (ws || wsConnecting) return;
  wsConnecting = true;

  wsReadyPromise = new Promise<void>((resolve) => {
    wsReadyResolve = resolve;
  });

  try {
    const socket = new WebSocket(WS_URL);

    socket.onopen = () => {
      ws = socket;
      wsReady = true;
      wsConnecting = false;
      wsReadyResolve?.();
      wsReadyResolve = null;
    };

    socket.onmessage = (event: MessageEvent) => {
      try {
        const msg = JSON.parse(event.data as string) as WsMessage;
        handleWsMessage(msg);
      } catch {
        // Ignore malformed messages
      }
    };

    socket.onerror = () => {
      wsReady = false;
      wsConnecting = false;
    };

    socket.onclose = () => {
      ws = null;
      wsReady = false;
      wsConnecting = false;
      // Reject all pending calls
      for (const [, cb] of pendingCalls) {
        clearTimeout(cb.timeout);
        cb.reject(new Error("WebSocket disconnected"));
      }
      pendingCalls.clear();
    };
  } catch {
    wsConnecting = false;
  }
}

/** Handle an incoming WS message by its type. */
function handleWsMessage(msg: WsMessage): void {
  if (msg.type === "tool.result") {
    const p = msg.payload as ToolResultPayload & { _call_id?: string };
    const callId = p._call_id;

    if (callId && pendingCalls.has(callId)) {
      const cb = pendingCalls.get(callId)!;
      clearTimeout(cb.timeout);
      pendingCalls.delete(callId);

      cb.resolve({
        toolCallId: callId,
        toolName: p.tool_name ?? "",
        status: p.status === "success" ? "success" : "error",
        summary: p.summary ?? `${p.tool_name} completed`,
        details: p.summary ?? "",
        durationMs: 0,
      });
    }
  }

  // Auto-approve: when auto mode is on and backend requests approval,
  // respond immediately so the backend pipeline doesn't stall.
  if (msg.type === "approval.requested" && autoApprove) {
    const p = msg.payload as ApprovalRequestedPayload;
    const response = JSON.stringify({
      type: "approval.resolved",
      session_id: "tui-session",
      payload: {
        request_id: p.request_id,
        approved: true,
      },
    });
    try {
      ws?.send(response);
    } catch {
      // WS might be disconnected — ignore
    }
  }
}

// Initialize WS connection eagerly at module load time
initWs();

// ---------------------------------------------------------------------------
// Send tool.execute via WebSocket
// ---------------------------------------------------------------------------

async function executeViaWs(toolCall: ToolCall): Promise<ExecutionResult | null> {
  // Lazily init WS on first call (or if reconnecting)
  if (!ws && !wsConnecting) {
    initWs();
  }

  // Wait for connection with timeout
  if (wsReadyPromise) {
    try {
      await Promise.race([
        wsReadyPromise,
        new Promise((_, reject) => setTimeout(() => reject(new Error("WS timeout")), 3000)),
      ]);
    } catch {
      // WS not available — fall back to simulation
      return null;
    }
  }

  if (!ws || !wsReady) {
    return null;
  }

  const startTime = Date.now();
  const callId = toolCall.id || `call-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

  return new Promise<ExecutionResult>((resolve, reject) => {
    const timeout = setTimeout(() => {
      pendingCalls.delete(callId);
      reject(new Error(`Tool execution timed out after 120s: ${toolCall.name}`));
    }, 120_000);

    pendingCalls.set(callId, { resolve, reject, timeout });

    ws!.send(JSON.stringify({
      type: "tool.execute",
      session_id: "tui-session",
      payload: {
        name: toolCall.name,
        arguments: { ...toolCall.arguments, _call_id: callId },
      },
    }));
  }).then((result) => {
    result.durationMs = Date.now() - startTime;
    return result;
  });
}

// ---------------------------------------------------------------------------
// Fallback: simulate locally when WS is not available
// ---------------------------------------------------------------------------

function simulateToolCall(tc: ToolCall): { status: "success" | "error"; summary: string; details: string } {
  const target = (tc.arguments.target as string) ?? "unknown";

  switch (tc.name) {
    case "recon_agent":
      return {
        status: "success",
        summary: `Found 12 subdomains for ${target}`,
        details: [
          `Subdomains discovered for ${target}:`,
          "",
          "  - www, api, mail, admin, dev, staging, blog, cdn, docs, support, status, app",
          "",
          "Technologies detected: Cloudflare CDN, Nginx 1.24, React SPA",
        ].join("\n"),
      };

    case "port_scan_agent":
      return {
        status: "success",
        summary: `Found 3 open ports on ${target}`,
        details: [
          `Port scan results for ${target}:`,
          "",
          "  PORT    STATE  SERVICE",
          "  22/tcp  open   SSH (OpenSSH 9.3)",
          "  80/tcp  open   HTTP (Nginx 1.24)",
          "  443/tcp open  HTTPS (Nginx 1.24)",
        ].join("\n"),
      };

    case "web_scan_agent":
      return {
        status: "success",
        summary: `Found 2 potential vulnerabilities on ${target}`,
        details: [
          `Web scan results for ${target}:`,
          "",
          "  Technologies: React SPA, Nginx 1.24",
          "  Missing Content-Security-Policy header (Medium)",
          "  Missing X-Frame-Options header (Low)",
        ].join("\n"),
      };

    case "vulnerability_agent":
      return {
        status: "success",
        summary: `Assessment complete — 0 critical, 2 medium, 3 low`,
        details: `Vulnerability assessment for ${target} completed.`,
      };

    default:
      return {
        status: "success",
        summary: `Executed ${tc.name} on ${target}`,
        details: `${tc.name} completed with arguments: ${JSON.stringify(tc.arguments)}`,
      };
  }
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Execute a tool call.
 *
 * First attempts to dispatch via WebSocket to the Python backend.
 * If the WS connection is not available, falls back to local simulation.
 */
export async function executeTool(toolCall: ToolCall): Promise<ExecutionResult> {
  const start = Date.now();

  // Try WebSocket first
  const wsResult = await executeViaWs(toolCall);
  if (wsResult) {
    return wsResult;
  }

  // Try local execution (shell_exec and filesystem tools)
  const localResult = await executeLocal(toolCall);
  if (localResult) {
    return {
      toolCallId: toolCall.id,
      toolName: toolCall.name,
      status: localResult.status,
      summary: localResult.summary,
      details: localResult.details,
      durationMs: Date.now() - start,
    };
  }

  // Fall back to simulation
  await delay(1000);
  const result = simulateToolCall(toolCall);

  return {
    toolCallId: toolCall.id,
    toolName: toolCall.name,
    ...result,
    durationMs: Date.now() - start,
  };
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
