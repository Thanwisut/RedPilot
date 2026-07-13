import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { mkdirSync, writeFileSync, rmSync, existsSync } from "node:fs";
import { resolve, join } from "node:path";
import { tmpdir } from "node:os";

import {
  getSandboxRoot,
  ensureSandboxRoot,
  resolveSafePath,
  resolveSafePathMustExist,
  PathEscapeError,
} from "../path-safety.js";

// ======================================================================
// getSandboxRoot
// ======================================================================

describe("getSandboxRoot", () => {
  const ORIG_ENV = process.env.REDPILOT_SCRATCH_DIR;

  afterEach(() => {
    if (ORIG_ENV !== undefined) {
      process.env.REDPILOT_SCRATCH_DIR = ORIG_ENV;
    } else {
      delete process.env.REDPILOT_SCRATCH_DIR;
    }
  });

  it("returns env var when set", () => {
    process.env.REDPILOT_SCRATCH_DIR = "/custom/sandbox";
    expect(getSandboxRoot()).toBe("/custom/sandbox");
  });

  it("returns default path when env var is not set", () => {
    delete process.env.REDPILOT_SCRATCH_DIR;
    const root = getSandboxRoot();
    expect(root).toContain(".redpilot/scratch");
    expect(root).not.toContain("undefined");
  });
});

// ======================================================================
// resolveSafePath — core containment
// ======================================================================

describe("resolveSafePath", () => {
  const sandboxRoot = resolve(tmpdir(), "redpilot-test-sandbox");

  beforeEach(() => {
    mkdirSync(sandboxRoot, { recursive: true });
    mkdirSync(join(sandboxRoot, "subdir"), { recursive: true });
    writeFileSync(join(sandboxRoot, "test.txt"), "hello");
  });

  afterEach(() => {
    rmSync(sandboxRoot, { recursive: true, force: true });
  });

  // ── Allowed paths ─────────────────────────────────────────────

  it("resolves a relative path to within the sandbox", () => {
    const result = resolveSafePath("test.txt", sandboxRoot);
    expect(result).toBe(join(sandboxRoot, "test.txt"));
  });

  it("resolves a subdirectory path", () => {
    const result = resolveSafePath("subdir", sandboxRoot);
    expect(result).toBe(join(sandboxRoot, "subdir"));
  });

  it("resolves nested subdirectory path", () => {
    const result = resolveSafePath("subdir/..", sandboxRoot);
    expect(result).toBe(sandboxRoot);
  });

  it("allows root directory itself (empty string)", () => {
    const result = resolveSafePath("", sandboxRoot);
    expect(result).toBe(sandboxRoot);
  });

  it("allows root directory itself (dot)", () => {
    const result = resolveSafePath(".", sandboxRoot);
    expect(result).toBe(sandboxRoot);
  });

  it("uses the default sandbox root when not specified", () => {
    process.env.REDPILOT_SCRATCH_DIR = sandboxRoot;
    const result = resolveSafePath("test.txt");
    expect(result).toBe(join(sandboxRoot, "test.txt"));
  });

  // ── Path traversal (../) ──────────────────────────────────────

  it("blocks ../ traversal that escapes above sandbox", () => {
    expect(() => {
      resolveSafePath("../", sandboxRoot);
    }).toThrow(PathEscapeError);
  });

  it("blocks deep ../ traversal", () => {
    expect(() => {
      resolveSafePath("subdir/../../etc", sandboxRoot);
    }).toThrow(PathEscapeError);
  });

  it("blocks multiple levels of ../ traversal", () => {
    expect(() => {
      resolveSafePath("subdir/../../../etc/passwd", sandboxRoot);
    }).toThrow(PathEscapeError);
  });

  // ── Absolute paths ────────────────────────────────────────────

  it("blocks absolute path (/etc/passwd)", () => {
    expect(() => {
      resolveSafePath("/etc/passwd", sandboxRoot);
    }).toThrow(PathEscapeError);
  });

  it("blocks absolute path (/tmp)", () => {
    expect(() => {
      resolveSafePath("/tmp", sandboxRoot);
    }).toThrow(PathEscapeError);
  });

  // ── startsWith bypass (the critical security fix) ─────────────

  it("blocks path that starts with sandbox prefix but is outside (startsWith bypass)", () => {
    // If sandbox is /tmp/sandbox, then /tmp/sandbox-other/foo starts with /tmp/sandbox
    // but is OUTSIDE the sandbox. The rootGuard separator prevents this.
    const siblingDir = resolve(tmpdir(), "redpilot-test-sandbox-other");
    mkdirSync(siblingDir, { recursive: true });
    try {
      expect(() => {
        resolveSafePath("../redpilot-test-sandbox-other/evil.txt", sandboxRoot);
      }).toThrow(PathEscapeError);
    } finally {
      rmSync(siblingDir, { recursive: true, force: true });
    }
  });

  it("blocks path where sandbox root is a prefix of another directory name", () => {
    // root = /tmp/abc, path = /tmp/abcdef/file — startsWith would allow if no separator
    const weirdRoot = resolve(tmpdir(), "abc");
    mkdirSync(weirdRoot, { recursive: true });
    try {
      expect(() => {
        resolveSafePath("../abcdef/file", weirdRoot);
      }).toThrow(PathEscapeError);
    } finally {
      rmSync(weirdRoot, { recursive: true, force: true });
    }
  });

  // ── Null bytes ────────────────────────────────────────────────

  it("rejects null bytes in the path", () => {
    expect(() => {
      resolveSafePath("test.txt\0", sandboxRoot);
    }).toThrow(PathEscapeError);
  });

  it("rejects null bytes in mid-path", () => {
    expect(() => {
      resolveSafePath("sub\0dir/test.txt", sandboxRoot);
    }).toThrow(PathEscapeError);
  });
});

// ======================================================================
// resolveSafePathMustExist
// ======================================================================

describe("resolveSafePathMustExist", () => {
  const sandboxRoot = resolve(tmpdir(), "redpilot-test-sandbox-exist");

  beforeEach(() => {
    mkdirSync(sandboxRoot, { recursive: true });
    writeFileSync(join(sandboxRoot, "existing.txt"), "i exist");
  });

  afterEach(() => {
    rmSync(sandboxRoot, { recursive: true, force: true });
  });

  it("resolves and returns path when file exists", () => {
    const result = resolveSafePathMustExist("existing.txt", sandboxRoot);
    expect(result).toBe(join(sandboxRoot, "existing.txt"));
  });

  it("throws Error (not PathEscapeError) when file does not exist", () => {
    expect(() => {
      resolveSafePathMustExist("missing.txt", sandboxRoot);
    }).toThrow("does not exist");
  });

  it("still blocks path escape", () => {
    expect(() => {
      resolveSafePathMustExist("../etc/passwd", sandboxRoot);
    }).toThrow(PathEscapeError);
  });
});

// ======================================================================
// ensureSandboxRoot
// ======================================================================

describe("ensureSandboxRoot", () => {
  const testRoot = resolve(tmpdir(), "redpilot-test-ensure");

  afterEach(() => {
    rmSync(testRoot, { recursive: true, force: true });
  });

  it("creates the sandbox directory if it does not exist", () => {
    process.env.REDPILOT_SCRATCH_DIR = testRoot;
    expect(existsSync(testRoot)).toBe(false);
    const result = ensureSandboxRoot();
    expect(existsSync(testRoot)).toBe(true);
    expect(result).toBe(testRoot);
  });

  it("returns existing directory without error", () => {
    mkdirSync(testRoot, { recursive: true });
    process.env.REDPILOT_SCRATCH_DIR = testRoot;
    const result = ensureSandboxRoot();
    expect(result).toBe(testRoot);
  });
});

// ======================================================================
// PathEscapeError
// ======================================================================

describe("PathEscapeError", () => {
  it("has correct name and message", () => {
    const err = new PathEscapeError("/bad/path", "/sandbox");
    expect(err.name).toBe("PathEscapeError");
    expect(err.message).toContain("/bad/path");
    expect(err.message).toContain("/sandbox");
    expect(err.message).toContain("escapes");
    expect(err instanceof Error).toBe(true);
  });
});
