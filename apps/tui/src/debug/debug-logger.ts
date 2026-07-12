/**
 * debug-logger.ts — M1: DEBUG LOG FILE + RENDER SNAPSHOTS
 *
 * Activated by --debug flag or REDPILOT_DEBUG=1 env var.
 * Writes a structured, append-only log file:
 *   apps/tui/.debug/session-<timestamp>.log
 *
 * When debug is not active, all methods are no-ops (zero overhead).
 * Never logs raw API keys — only presence/length.
 */

import { appendFileSync, mkdirSync, existsSync, writeFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import type {
  DebugLogEntry,
  WsEventLog,
  RestCallLog,
  ScreenTransitionLog,
  UserInputLog,
  TerminalDimensionsLog,
  ErrorLog,
  FrameSnapshotLog,
} from "./types.js";

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const DEBUG_DIR = join(__dirname, "..", "..", ".debug");

// ---------------------------------------------------------------------------
// Singleton state
// ---------------------------------------------------------------------------

let _instance: DebugLogger | null = null;
let _enabled = false;

/** Check whether debug mode should be active. */
export function isDebugEnabled(): boolean {
  // Check env var first, then a module-level flag
  return process.env.REDPILOT_DEBUG === "1" || _enabled;
}

/** Enable debug mode programmatically (used by --debug flag). */
export function enableDebug(): void {
  _enabled = true;
}

// ---------------------------------------------------------------------------
// DebugLogger
// ---------------------------------------------------------------------------

export class DebugLogger {
  private logPath: string;
  private written = 0;

  constructor(logPath: string) {
    this.logPath = logPath;
  }

  /** Create the logger and open the log file. */
  static init(): DebugLogger {
    if (_instance) return _instance;

    const ts = new Date().toISOString().replace(/[:.]/g, "-");
    const logPath = join(DEBUG_DIR, `session-${ts}.log`);

    // Ensure debug directory exists
    if (!existsSync(DEBUG_DIR)) {
      mkdirSync(DEBUG_DIR, { recursive: true });
    }

    // Write header
    writeFileSync(logPath, `# REDPILOT debug session — ${new Date().toISOString()}\n`);
    writeFileSync(logPath, `# PID: ${process.pid}\n`, { flag: "a" });
    writeFileSync(logPath, `# Args: ${process.argv.slice(2).join(" ")}\n`, { flag: "a" });
    writeFileSync(logPath, "#\n", { flag: "a" });

    _instance = new DebugLogger(logPath);
    return _instance;
  }

  /** Get the existing instance (or no-op if not initialized). */
  static get(): DebugLogger {
    return _instance ?? new DebugLogger("/dev/null");
  }

  // -----------------------------------------------------------------------
  // Low-level write
  // -----------------------------------------------------------------------

  private write(entry: DebugLogEntry): void {
    try {
      const line = JSON.stringify(entry) + "\n";
      appendFileSync(this.logPath, line);
      this.written++;
    } catch {
      // Silently fail — logging should never crash the app
    }
  }

  private static entry(event: string, data: Record<string, unknown>): DebugLogEntry {
    return { ts: new Date().toISOString(), event, data };
  }

  // -----------------------------------------------------------------------
  // High-level logging methods
  // -----------------------------------------------------------------------

  /** Log a WebSocket event (type, payload shape, ts). */
  logWsEvent(wsEvent: WsEventLog): void {
    this.write(
      DebugLogger.entry("ws.received", {
        wsType: wsEvent.type,
        session_id: wsEvent.session_id,
        payload: DebugLogger.sanitizePayload(wsEvent.payload),
        ts: wsEvent.ts,
      }),
    );
  }

  /** Log an outgoing WebSocket message. */
  logWsSent(msg: { type: string; payload: unknown }): void {
    this.write(
      DebugLogger.entry("ws.sent", {
        wsType: msg.type,
        payload: DebugLogger.sanitizePayload(msg.payload),
      }),
    );
  }

  /** Log a REST call. */
  logRestCall(call: RestCallLog): void {
    this.write(
      DebugLogger.entry("rest.call", {
        method: call.method,
        url: call.url,
        status: call.status,
        bodyShape: call.body
          ? typeof call.body === "object"
            ? Object.keys(call.body as Record<string, unknown>)
            : typeof call.body
          : undefined,
      }),
    );
  }

  /** Log a screen transition. */
  logScreenTransition(transition: ScreenTransitionLog): void {
    this.write(
      DebugLogger.entry("screen.transition", {
        from: transition.from,
        to: transition.to,
      }),
    );
  }

  /** Log user input (NEVER the raw value of API keys). */
  logUserInput(input: UserInputLog): void {
    this.write(
      DebugLogger.entry("user.input", {
        kind: input.kind,
        ...(input.key ? { key: input.key } : {}),
        ...(input.length !== undefined ? { length: input.length } : {}),
      }),
    );
  }

  /** Log terminal dimensions at render time. */
  logTerminalDimensions(dims: TerminalDimensionsLog): void {
    this.write(
      DebugLogger.entry("terminal.dimensions", {
        columns: dims.columns,
        rows: dims.rows,
      }),
    );
  }

  /** Log a caught error with full stack trace. */
  logError(err: ErrorLog): void {
    this.write(
      DebugLogger.entry("error", {
        message: err.message,
        stack: err.stack,
      }),
    );
  }

  /** Log a render snapshot (the full text frame). */
  captureFrame(snapshot: FrameSnapshotLog): void {
    this.write(
      DebugLogger.entry("frame.snapshot", {
        text: snapshot.text,
        lineCount: snapshot.lineCount,
      }),
    );
  }

  /** Log a generic informational message. */
  logInfo(message: string, data?: Record<string, unknown>): void {
    this.write(DebugLogger.entry("info", { message, ...data }));
  }

  /** Get total entries written. */
  get entryCount(): number {
    return this.written;
  }

  // -----------------------------------------------------------------------
  // Helpers
  // -----------------------------------------------------------------------

  /**
   * Sanitize a payload for logging:
   * - Never log raw API key values
   * - Replace any field named "api_key" or "key" with a length/shape indicator
   */
  private static sanitizePayload(
    payload: unknown,
  ): unknown {
    if (Array.isArray(payload)) {
      return payload.map((item) => DebugLogger.sanitizePayload(item));
    }
    if (payload !== null && typeof payload === "object") {
      const sanitized: Record<string, unknown> = {};
      for (const [key, value] of Object.entries(
        payload as Record<string, unknown>,
      )) {
        if (key === "api_key" && typeof value === "string") {
          sanitized[key] = `[REDACTED length=${value.length}]`;
        } else if (key === "args" && typeof value === "object") {
          sanitized[key] = DebugLogger.sanitizePayload(value);
        } else {
          sanitized[key] = DebugLogger.sanitizePayload(value);
        }
      }
      return sanitized;
    }
    return payload;
  }

  getPath(): string {
    return this.logPath;
  }
}

// ---------------------------------------------------------------------------
// Convenience: no-op proxy for when debug is disabled
// ---------------------------------------------------------------------------

/** Obtain the debug logger. Returns a real logger if debug is enabled,
 *  or a no-op proxy if not. */
export function getLogger(): DebugLogger {
  if (!isDebugEnabled()) {
    return NoopLogger.instance;
  }
  if (!_instance) {
    return DebugLogger.init();
  }
  return _instance;
}

class NoopLogger {
  static instance = new NoopLogger() as unknown as DebugLogger;

  logWsEvent(_msg: WsEventLog): void {}
  logWsSent(_msg: { type: string; payload: unknown }): void {}
  logRestCall(_call: RestCallLog): void {}
  logScreenTransition(_t: ScreenTransitionLog): void {}
  logUserInput(_input: UserInputLog): void {}
  logTerminalDimensions(_dims: TerminalDimensionsLog): void {}
  logError(_err: ErrorLog): void {}
  captureFrame(_snap: FrameSnapshotLog): void {}
  logInfo(_msg: string, _data?: Record<string, unknown>): void {}

  get entryCount(): number {
    return 0;
  }

  getPath(): string {
    return "/dev/null";
  }
}
