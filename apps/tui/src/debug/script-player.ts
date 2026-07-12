/**
 * script-player.ts — M2: NON-INTERACTIVE HEADLESS MODE SCRIPT PLAYER
 *
 * Reads a JSON script file and executes it against an Ink-rendered TUI
 * by feeding keystrokes through the real Ink input path (stdin.write).
 * Captures rendered frames after each step for later analysis.
 *
 * All results are accumulated into a HeadlessRunResult for JSON export.
 */

import { readFileSync } from "node:fs";
import {
  type ScriptFile,
  type ScriptCommand,
  type HeadlessRunResult,
  type FrameRecord,
  type WsEventLog,
  type RestCallLog,
  type ScreenTransitionLog,
} from "./types.js";
import { createCapturedIO, type CapturedStdout } from "./capture.js";

// ---------------------------------------------------------------------------
// Helpers: key sequences
// ---------------------------------------------------------------------------

const KEY_MAP: Record<string, string> = {
  up: "\x1b[A",
  down: "\x1b[B",
  return: "\r",
  escape: "\x1b",
  backspace: "\x7f",
};

function keySequence(key: string): string {
  return KEY_MAP[key] ?? key;
}

// ---------------------------------------------------------------------------
// ScriptPlayer
// ---------------------------------------------------------------------------

export class ScriptPlayer {
  private script: ScriptFile;
  private captured: ReturnType<typeof createCapturedIO>;
  private frames: FrameRecord[] = [];
  private wsEvents: WsEventLog[] = [];
  private restCalls: RestCallLog[] = [];
  private transitions: ScreenTransitionLog[] = [];
  private finalScreen = "unknown";

  /** Set to true on exit to stop waiting loops */
  private stopped = false;

  constructor(scriptPath: string) {
    const raw = readFileSync(scriptPath, "utf-8");
    this.script = JSON.parse(raw) as ScriptFile;
    this.captured = createCapturedIO(
      this.script.columns ?? 100,
      this.script.rows ?? 40,
    );
  }

  /** Get the captured I/O for use with Ink's render(). */
  get io() {
    return this.captured;
  }

  /** The stdout frame capture. */
  get stdout(): CapturedStdout {
    return this.captured.stdout;
  }

  /** The stdin stream for injecting keypresses. */
  get stdin() {
    return this.captured.stdin;
  }

  /** Terminal columns to use. */
  get columns(): number {
    return this.script.columns ?? 100;
  }

  /** Terminal rows to use. */
  get rows(): number {
    return this.script.rows ?? 40;
  }

  /** Run the full script and return the result. */
  async run(timeoutMs = 30_000): Promise<HeadlessRunResult> {
    const startedAt = new Date().toISOString();
    let exitReason: HeadlessRunResult["exitReason"] = "completed";
    let exitMessage: string | undefined;

    try {
      await this.runWithTimeout(this.script.commands, timeoutMs);
    } catch (err) {
      if (err instanceof ScriptError) {
        exitReason = err.reason;
        exitMessage = err.message;
      } else if (err instanceof TimeoutError) {
        exitReason = "timeout";
        exitMessage = err.message;
      } else {
        exitReason = "error";
        exitMessage = (err as Error).message;
      }
    } finally {
      this.stopped = true;
    }

    return {
      scriptLabel: this.script.label,
      startedAt,
      completedAt: new Date().toISOString(),
      exitReason,
      exitMessage,
      columns: this.columns,
      rows: this.rows,
      frames: this.frames,
      wsEvents: this.wsEvents,
      restCalls: this.restCalls,
      transitions: this.transitions,
      finalScreen: this.finalScreen,
    };
  }

  // -----------------------------------------------------------------------
  // Execution
  // -----------------------------------------------------------------------

  private async runWithTimeout(
    commands: ScriptCommand[],
    timeoutMs: number,
  ): Promise<void> {
    return new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => {
        reject(new TimeoutError(`Script timed out after ${timeoutMs}ms`));
      }, timeoutMs);

      this.executeCommands(commands)
        .then(() => {
          clearTimeout(timer);
          resolve();
        })
        .catch((err) => {
          clearTimeout(timer);
          reject(err);
        });
    });
  }

  private async executeCommands(
    commands: ScriptCommand[],
  ): Promise<void> {
    for (const cmd of commands) {
      if (this.stopped) break;
      await this.executeCommand(cmd);
    }
  }

  private async executeCommand(cmd: ScriptCommand): Promise<void> {
    switch (cmd.type) {
      // --- Terminal config ---
      case "setColumns": {
        this.captured.stdout.columns = cmd.columns;
        break;
      }
      case "setRows": {
        this.captured.stdout.rows = cmd.rows;
        break;
      }

      // --- Input simulation ---
      case "keypress": {
        const seq = keySequence(cmd.key);
        this.captured.stdin.write(seq);
        // Wait for Ink to process the input and React to re-render
        await waitTick();
        // Additional wait for complex state updates
        await waitTick();
        break;
      }
      case "text": {
        for (const char of cmd.value) {
          this.captured.stdin.write(char);
          await waitTick();
        }
        await waitTick();
        break;
      }

      // --- Timing ---
      case "wait": {
        await waitMs(cmd.ms);
        break;
      }
      case "waitForFrame": {
        await this.waitForFrame(cmd.contains, cmd.timeout ?? 5000);
        break;
      }

      // --- Assertions ---
      case "assertFrameContains": {
        const frame = this.captured.stdout.lastFrame() ?? "";
        if (!frame.includes(cmd.value)) {
          throw new ScriptError(
            "assertion_failed",
            `Frame does not contain "${cmd.value}". Last frame: ${frame.slice(0, 200)}`,
          );
        }
        break;
      }

      // --- Frame capture ---
      case "captureFrame": {
        this.captureFrame(cmd.label);
        break;
      }

      // --- Sub-steps ---
      case "step": {
        this.captureFrame(`start: ${cmd.label}`);
        await this.executeCommands(cmd.commands);
        this.captureFrame(`end: ${cmd.label}`);
        break;
      }

      default:
        throw new ScriptError(
          "error",
          `Unknown command type: ${(cmd as ScriptCommand).type}`,
        );
    }
  }

  // -----------------------------------------------------------------------
  // Frame capture
  // -----------------------------------------------------------------------

  captureFrame(label: string): void {
    const text = this.captured.stdout.lastFrame() ?? "";
    this.frames.push({ label, text, ts: new Date().toISOString() });
  }

  // -----------------------------------------------------------------------
  // Wait helpers
  // -----------------------------------------------------------------------

  private async waitForFrame(
    contains: string,
    timeoutMs: number,
  ): Promise<void> {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const frame = this.captured.stdout.lastFrame() ?? "";
      if (frame.includes(contains)) return;
      await waitMs(50);
    }
    const last = this.captured.stdout.lastFrame() ?? "";
    throw new ScriptError(
      "assertion_failed",
      `Timed out waiting for "${contains}" in frame. Last frame (200 chars): ${last.slice(0, 200)}`,
    );
  }

  // -----------------------------------------------------------------------
  // External hooks for main loop instrumentation
  // -----------------------------------------------------------------------

  recordWsEvent(event: WsEventLog): void {
    this.wsEvents.push(event);
  }

  recordRestCall(call: RestCallLog): void {
    this.restCalls.push(call);
  }

  recordTransition(from: string, to: string): void {
    this.transitions.push({ from, to });
    this.finalScreen = to;
  }
}

// ---------------------------------------------------------------------------
// Custom errors
// ---------------------------------------------------------------------------

class ScriptError extends Error {
  reason: HeadlessRunResult["exitReason"];
  constructor(reason: HeadlessRunResult["exitReason"], message: string) {
    super(message);
    this.reason = reason;
    this.name = "ScriptError";
  }
}

class TimeoutError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "TimeoutError";
  }
}

// ---------------------------------------------------------------------------
// Wait utilities
// ---------------------------------------------------------------------------

function waitTick(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

function waitMs(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
