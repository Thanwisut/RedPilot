/**
 * types.ts — shared types for debug logging, headless scripting, and state dumps.
 */

// ---------------------------------------------------------------------------
// Debug log entry types (M1)
// ---------------------------------------------------------------------------

export interface DebugLogEntry {
  ts: string; // ISO 8601
  event: string;
  data: Record<string, unknown>;
}

export interface WsEventLog {
  type: string;
  session_id?: string;
  payload: unknown;
  ts: string;
}

export interface RestCallLog {
  method: string;
  url: string;
  status: number;
  body?: unknown;
}

export interface ScreenTransitionLog {
  from: string;
  to: string;
}

export interface UserInputLog {
  kind: "keypress" | "text";
  key?: string;
  length?: number; // for text input, log length, NOT the raw value
}

export interface TerminalDimensionsLog {
  columns: number;
  rows: number;
}

export interface ErrorLog {
  message: string;
  stack?: string;
}

export interface FrameSnapshotLog {
  text: string;
  lineCount: number;
}

// ---------------------------------------------------------------------------
// Headless script schema (M2)
// ---------------------------------------------------------------------------

export type ScriptCommand =
  | { type: "setColumns"; columns: number }
  | { type: "setRows"; rows: number }
  | { type: "keypress"; key: "up" | "down" | "return" | "escape" | "backspace" }
  | { type: "text"; value: string }
  | { type: "wait"; ms: number }
  | { type: "waitForFrame"; contains: string; timeout?: number }
  | { type: "assertFrameContains"; value: string }
  | { type: "captureFrame"; label: string }
  | { type: "step"; label: string; commands: ScriptCommand[] };

export interface ScriptFile {
  /** Display name for this script */
  label: string;
  /** Terminal width to simulate */
  columns?: number;
  /** Terminal height to simulate */
  rows?: number;
  /** Sequence of commands */
  commands: ScriptCommand[];
}

// ---------------------------------------------------------------------------
// Headless run result (M2 output)
// ---------------------------------------------------------------------------

export interface FrameRecord {
  label: string;
  text: string;
  ts: string;
}

export interface HeadlessRunResult {
  scriptLabel: string;
  startedAt: string;
  completedAt: string;
  /** How the run ended */
  exitReason: "completed" | "timeout" | "assertion_failed" | "error";
  exitMessage?: string;
  /** Terminal dimensions used */
  columns: number;
  rows: number;
  /** All captured frames with labels */
  frames: FrameRecord[];
  /** Sequence of WS events received */
  wsEvents: WsEventLog[];
  /** Sequence of REST calls made */
  restCalls: RestCallLog[];
  /** Screen transitions observed */
  transitions: ScreenTransitionLog[];
  /** Final screen reached */
  finalScreen?: string;
}
