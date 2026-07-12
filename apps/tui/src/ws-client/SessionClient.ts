/** Typed WebSocket client for the REDPILOT WS event contract.
 *
 * This is the SINGLE typed contract the real FastAPI backend must match.
 * Every event type and payload shape is defined here — no `any` anywhere.
 *
 * Reconnect strategy: exponential backoff starting at 500ms, max 30s,
 * jittered (±25%). Caller provides an `onEvent` callback for all events
 * and individual callbacks for specific types if needed.
 *
 * @example
 *   const client = new SessionClient("ws://localhost:8080");
 *   client.on("agent.status", (msg) => console.log(msg.payload));
 *   client.connect();
 */

// ---------------------------------------------------------------------------
// WS message envelope
// ---------------------------------------------------------------------------

export interface WsMessage<T = unknown> {
  type: string;
  session_id: string;
  payload: T;
  ts: string; // ISO 8601
}

// ---------------------------------------------------------------------------
// Event payload types — THIS IS THE CONTRACT
// ---------------------------------------------------------------------------

export interface AgentSpawnedPayload {
  agent_id: string;
  cluster: string;
  task_node_id: string;
}

export interface AgentStatusPayload {
  agent_id: string;
  status:
    | "Pending"
    | "Ready"
    | "Dispatched"
    | "Executing"
    | "Completed"
    | "Failed"
    | "Blocked";
}

export interface TokenDeltaPayload {
  agent_id: string;
  text: string;
}

export interface ToolInvokedPayload {
  agent_id: string;
  tool_name: string;
  target: string;
  args: Record<string, unknown>;
}

export interface ToolResultPayload {
  agent_id: string;
  tool_name: string;
  status: string;
  summary: string;
}

export interface ApprovalRequestedPayload {
  request_id: string;
  tool_name: string;
  target: string;
  rationale: string;
  requires_approval_reason: string;
}

export interface ApprovalResolvedPayload {
  request_id: string;
  approved: boolean;
}

export interface PlanUpdatedPayload {
  // Task graph snapshot — enough to render a tree
  task_graph_snapshot: {
    nodes: Array<{
      id: string;
      agent_id: string;
      status: string;
      dependencies: string[];
    }>;
  };
}

export interface ReportReadyPayload {
  report_path: string;
}

// ---------------------------------------------------------------------------
// Event map — maps event type strings to their payload types
// ---------------------------------------------------------------------------

export interface RedpilotEventMap {
  "agent.spawned": AgentSpawnedPayload;
  "agent.status": AgentStatusPayload;
  "token.delta": TokenDeltaPayload;
  "tool.invoked": ToolInvokedPayload;
  "tool.result": ToolResultPayload;
  "approval.requested": ApprovalRequestedPayload;
  "approval.resolved": ApprovalResolvedPayload;
  "plan.updated": PlanUpdatedPayload;
  "report.ready": ReportReadyPayload;
}

export type RedpilotEventType = keyof RedpilotEventMap & string;

export type WsMessageTyped<K extends RedpilotEventType> = WsMessage<
  RedpilotEventMap[K]
>;

// ---------------------------------------------------------------------------
// Outgoing message types the TUI can send
// ---------------------------------------------------------------------------

export interface ToolExecutePayload {
  name: string;
  arguments: Record<string, unknown>;
}

export interface ApprovalResolveOutgoing {
  type: "approval.resolved";
  session_id: string;
  payload: ApprovalResolvedPayload;
}

export interface ToolExecuteOutgoing {
  type: "tool.execute";
  session_id: string;
  payload: ToolExecutePayload;
}

export type OutgoingMessage = ApprovalResolveOutgoing | ToolExecuteOutgoing;

import { getLogger } from "../debug/debug-logger.js";

// ---------------------------------------------------------------------------
// SessionClient
// ---------------------------------------------------------------------------

export type EventCallback<T> = (msg: WsMessage<T>) => void;

export class SessionClient {
  private ws: WebSocket | null = null;
  private url: string;
  private sessionId: string;
  private reconnectAttempt = 0;
  private maxReconnectDelay = 30_000;
  private initialReconnectDelay = 500;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private destroyed = false;

  /** Generic event handlers — one per event type */
  private handlers = new Map<string, Set<EventCallback<unknown>>>();

  /** Connection lifecycle callbacks */
  private onConnect_: (() => void) | null = null;
  private onDisconnect_: ((code: number) => void) | null = null;

  constructor(url: string, sessionId?: string) {
    this.url = url;
    this.sessionId =
      sessionId ?? `session-${Math.random().toString(36).slice(2, 10)}`;
  }

  // -----------------------------------------------------------------------
  // Connection
  // -----------------------------------------------------------------------

  connect(): void {
    if (this.destroyed) return;
    this.cleanup();

    try {
      this.ws = new WebSocket(this.url);
    } catch {
      this.scheduleReconnect();
      return;
    }

    this.ws.onopen = () => {
      this.reconnectAttempt = 0;
      this.onConnect_?.();
    };

    this.ws.onmessage = (event: MessageEvent) => {
      try {
        const msg = JSON.parse(event.data as string) as WsMessage;
        this.dispatch(msg);
      } catch {
        // Ignore malformed messages
      }
    };

    this.ws.onclose = (event: CloseEvent) => {
      this.onDisconnect_?.(event.code);
      if (!this.destroyed) {
        this.scheduleReconnect();
      }
    };

    this.ws.onerror = () => {
      // onclose will fire after onerror, which triggers reconnect
    };
  }

  disconnect(): void {
    this.destroyed = true;
    this.cleanup();
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  // -----------------------------------------------------------------------
  // Send
  // -----------------------------------------------------------------------

  send(msg: OutgoingMessage): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg));
      const logger = getLogger();
      logger.logWsSent({ type: msg.type, payload: msg.payload });
    }
  }

  /** Convenience: send an approval.resolved message */
  sendApproval(requestId: string, approved: boolean): void {
    this.send({
      type: "approval.resolved",
      session_id: this.sessionId,
      payload: { request_id: requestId, approved },
    });
  }

  /** Send a tool.execute message — triggers agent execution in the backend */
  sendToolExecute(name: string, args: Record<string, unknown>): void {
    this.send({
      type: "tool.execute",
      session_id: this.sessionId,
      payload: { name, arguments: args },
    });
  }

  // -----------------------------------------------------------------------
  // Event subscription
  // -----------------------------------------------------------------------

  on<K extends RedpilotEventType>(
    type: K,
    cb: EventCallback<RedpilotEventMap[K]>,
  ): () => void {
    if (!this.handlers.has(type)) {
      this.handlers.set(type, new Set());
    }
    // eslint-disable-next-line @typescript-eslint/no-non-null-assertion
    this.handlers.get(type)!.add(cb as EventCallback<unknown>);

    // Return unsubscribe function
    return () => {
      this.handlers.get(type)?.delete(cb as EventCallback<unknown>);
    };
  }

  /** Subscribe to ALL events (for logging or catch-all rendering). */
  onAny(cb: EventCallback<unknown>): () => void {
    return this.on("*" as RedpilotEventType, cb);
  }

  // -----------------------------------------------------------------------
  // Connection lifecycle callbacks
  // -----------------------------------------------------------------------

  onConnect(cb: () => void): void {
    this.onConnect_ = cb;
  }

  onDisconnect(cb: (code: number) => void): void {
    this.onDisconnect_ = cb;
  }

  getSessionId(): string {
    return this.sessionId;
  }

  // -----------------------------------------------------------------------
  // Private
  // -----------------------------------------------------------------------

  private dispatch(msg: WsMessage): void {
    // Log to debug logger
    const logger = getLogger();
    logger.logWsEvent({
      type: msg.type,
      session_id: msg.session_id,
      payload: msg.payload,
      ts: msg.ts,
    });

    const handlers = this.handlers.get(msg.type);
    if (handlers) {
      for (const cb of handlers) {
        try {
          cb(msg);
        } catch {
          // Handler errors should not break the event loop
        }
      }
    }
    // Also dispatch to '*' catch-all handlers
    const catchAll = this.handlers.get("*" as RedpilotEventType);
    if (catchAll) {
      for (const cb of catchAll) {
        try {
          cb(msg);
        } catch {
          // noop
        }
      }
    }
  }

  private scheduleReconnect(): void {
    if (this.destroyed) return;
    const delay = Math.min(
      this.initialReconnectDelay * 2 ** this.reconnectAttempt +
        Math.random() * this.initialReconnectDelay * 0.5,
      this.maxReconnectDelay,
    );
    this.reconnectAttempt++;
    this.reconnectTimer = setTimeout(() => {
      this.connect();
    }, delay);
  }

  private cleanup(): void {
    if (this.ws) {
      this.ws.onopen = null;
      this.ws.onmessage = null;
      this.ws.onclose = null;
      this.ws.onerror = null;
      if (
        this.ws.readyState === WebSocket.OPEN ||
        this.ws.readyState === WebSocket.CONNECTING
      ) {
        this.ws.close();
      }
      this.ws = null;
    }
  }
}
