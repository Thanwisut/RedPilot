/**
 * capture.ts — frame-capture utility for debug/headless modes.
 *
 * Provides a custom Stdout class (same pattern as ink-testing-library)
 * that captures rendered output frames, and a helper to create Ink render
 * options with captured I/O.
 */

import { EventEmitter } from "node:events";

// ---------------------------------------------------------------------------
// Custom captured I/O streams
// ---------------------------------------------------------------------------

export class CapturedStdout extends EventEmitter {
  columns: number;
  rows: number;
  frames: string[] = [];
  private _lastFrame: string | undefined;

  constructor(columns = 100, rows = 40) {
    super();
    this.columns = columns;
    this.rows = rows;
  }

  get isTTY(): boolean {
    return true;
  }

  write = (frame: string): boolean => {
    this.frames.push(frame);
    this._lastFrame = frame;
    return true;
  };

  lastFrame = (): string | undefined => this._lastFrame;

  setEncoding(): void {}
  setRawMode(): void {}
  ref(): void {}
  unref(): void {}
  resume(): void {}
  pause(): void {}
  read = (): null => null;
}

export class CapturedStderr extends EventEmitter {
  frames: string[] = [];
  private _lastFrame: string | undefined;

  write = (frame: string): boolean => {
    this.frames.push(frame);
    this._lastFrame = frame;
    return true;
  };

  lastFrame = (): string | undefined => this._lastFrame;

  get isTTY(): boolean {
    return true;
  }
  setEncoding(): void {}
  setRawMode(): void {}
  ref(): void {}
  unref(): void {}
  resume(): void {}
  pause(): void {}
  read = (): null => null;
}

export class CapturedStdin extends EventEmitter {
  isTTY = true;
  private data: string | null = null;

  constructor() {
    super();
  }

  write = (data: string): void => {
    this.data = data;
    this.emit("readable");
    this.emit("data", data);
  };

  setEncoding(): void {}
  setRawMode(): void {}
  ref(): void {}
  unref(): void {}
  resume(): void {}
  pause(): void {}

  read = (): string | null => {
    const d = this.data;
    this.data = null;
    return d;
  };
}

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

export interface CapturedIO {
  stdout: CapturedStdout;
  stderr: CapturedStderr;
  stdin: CapturedStdin;
}

export function createCapturedIO(columns = 100, rows = 40): CapturedIO {
  return {
    stdout: new CapturedStdout(columns, rows),
    stderr: new CapturedStderr(),
    stdin: new CapturedStdin(),
  };
}
