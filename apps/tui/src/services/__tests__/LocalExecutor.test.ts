import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { mkdirSync, writeFileSync, rmSync, readFileSync, existsSync } from "node:fs";
import { resolve, join } from "node:path";
import { tmpdir } from "node:os";
import { randomBytes } from "node:crypto";

import { executeLocal } from "../LocalExecutor.js";

import type { ToolCall } from "../../providers/types.js";

// Helper: create a ToolCall-like object
function toolCall(name: string, args: Record<string, unknown>, id?: string): ToolCall {
  return { id: id ?? `call-${name}`, name, arguments: args };
}

// Helper: get the unique sandbox path for this test run
function sandboxPath(label: string): string {
  return resolve(tmpdir(), `redpilot-localexec-test-${label}-${randomBytes(4).toString("hex")}`);
}

describe("executeLocal — dispatch", () => {
  it("returns null for non-local tool (recon_agent)", async () => {
    const result = await executeLocal(toolCall("recon_agent", { target: "example.com" }));
    expect(result).toBeNull();
  });

  it("returns null for unknown tool", async () => {
    const result = await executeLocal(toolCall("some_made_up_tool", {}));
    expect(result).toBeNull();
  });
});

// ======================================================================
// shell_exec
// ======================================================================

describe("executeLocal — shell_exec", () => {
  it("runs a simple echo command and returns success", async () => {
    const result = await executeLocal(toolCall("shell_exec", {
      command: ["echo", "hello world"],
    }));
    expect(result).not.toBeNull();
    expect(result!.status).toBe("success");
    expect(result!.summary).toContain("exit code 0");
    expect(result!.details).toContain("hello world");
  });

  it("runs a command and captures stdout", async () => {
    const result = await executeLocal(toolCall("shell_exec", {
      command: ["echo", "line1\nline2\nline3"],
    }));
    expect(result!.status).toBe("success");
    expect(result!.details).toContain("line1");
    expect(result!.details).toContain("line2");
  });

  it("reports exit code for failing command", async () => {
    const result = await executeLocal(toolCall("shell_exec", {
      command: ["bash", "-c", "exit 42"],
    }));
    expect(result!.status).toBe("error");
    expect(result!.summary).toContain("exit code 42");
  });

  it("reports stderr output", async () => {
    const result = await executeLocal(toolCall("shell_exec", {
      command: ["bash", "-c", "echo stderr message >&2; exit 1"],
    }));
    expect(result!.status).toBe("error");
    expect(result!.details).toContain("stderr");
  });

  it("reports error for non-existent executable", async () => {
    const result = await executeLocal(toolCall("shell_exec", {
      command: ["/path/to/nonexistent/binary"],
    }));
    expect(result!.status).toBe("error");
    expect(result!.summary).toContain("failed");
  });

  it("returns error for empty command array", async () => {
    const result = await executeLocal(toolCall("shell_exec", {
      command: [],
    }));
    expect(result!.status).toBe("error");
    expect(result!.summary).toContain("No command");
  });

  it("returns error for missing command argument", async () => {
    const result = await executeLocal(toolCall("shell_exec", {}));
    expect(result!.status).toBe("error");
    expect(result!.summary).toContain("No command");
  });

  it("returns error for non-array command", async () => {
    const result = await executeLocal(toolCall("shell_exec", {
      command: "echo hello",
    }));
    expect(result!.status).toBe("error");
    expect(result!.summary).toContain("No command");
  });

  it("blocks dangerous commands (rm)", async () => {
    const result = await executeLocal(toolCall("shell_exec", {
      command: ["rm", "-rf", "/tmp"],
    }));
    expect(result!.status).toBe("error");
    expect(result!.summary).toContain("blocked");
    expect(result!.summary).toContain("safety");
  });

  it("blocks sudo", async () => {
    const result = await executeLocal(toolCall("shell_exec", {
      command: ["sudo", "ls"],
    }));
    expect(result!.status).toBe("error");
    expect(result!.summary).toContain("blocked");
  });

  it("blocks docker", async () => {
    const result = await executeLocal(toolCall("shell_exec", {
      command: ["docker", "ps"],
    }));
    expect(result!.status).toBe("error");
    expect(result!.summary).toContain("blocked");
  });

  it("allows safe commands", async () => {
    const result = await executeLocal(toolCall("shell_exec", {
      command: ["ls", "-la"],
    }));
    expect(result!.status).toBe("success");
  });
});

// ======================================================================
// list_directory
// ======================================================================

describe("executeLocal — list_directory", () => {
  let root: string;

  beforeEach(() => {
    root = sandboxPath("listdir");
    mkdirSync(root, { recursive: true });
    process.env.REDPILOT_SCRATCH_DIR = root;
  });

  afterEach(() => {
    rmSync(root, { recursive: true, force: true });
    delete process.env.REDPILOT_SCRATCH_DIR;
  });

  it("lists files in the sandbox root", async () => {
    writeFileSync(join(root, "a.txt"), "a");
    writeFileSync(join(root, "b.txt"), "b");
    mkdirSync(join(root, "sub"), { recursive: true });

    const result = await executeLocal(toolCall("list_directory", { path: "" }));
    expect(result!.status).toBe("success");
    expect(result!.details).toContain("a.txt");
    expect(result!.details).toContain("b.txt");
    expect(result!.details).toContain("sub/");
    expect(result!.summary).toContain("3 entries");
  });

  it("lists files in a subdirectory", async () => {
    mkdirSync(join(root, "subdir"), { recursive: true });
    writeFileSync(join(root, "subdir", "deep.txt"), "deep");

    const result = await executeLocal(toolCall("list_directory", { path: "subdir" }));
    expect(result!.status).toBe("success");
    expect(result!.details).toContain("deep.txt");
  });

  it("returns error for path outside sandbox", async () => {
    const result = await executeLocal(toolCall("list_directory", { path: "/etc" }));
    expect(result!.status).toBe("error");
    expect(result!.summary).toContain("not allowed");
  });

  it("returns error for ../ traversal", async () => {
    const result = await executeLocal(toolCall("list_directory", { path: "../../etc" }));
    expect(result!.status).toBe("error");
    expect(result!.summary).toContain("not allowed");
  });

  it("handles empty directory", async () => {
    const result = await executeLocal(toolCall("list_directory", { path: "" }));
    expect(result!.status).toBe("success");
    expect(result!.summary).toContain("0 entries");
  });

  it("handles recursive listing", async () => {
    mkdirSync(join(root, "a", "b", "c"), { recursive: true });
    writeFileSync(join(root, "a", "x.txt"), "x");
    writeFileSync(join(root, "a", "b", "y.txt"), "y");
    writeFileSync(join(root, "a", "b", "c", "z.txt"), "z");

    const result = await executeLocal(toolCall("list_directory", {
      path: "a",
      recursive: true,
    }));
    expect(result!.status).toBe("success");
    expect(result!.details).toContain("x.txt");
    expect(result!.details).toContain("y.txt");
    expect(result!.details).toContain("z.txt");
  });
});

// ======================================================================
// read_file
// ======================================================================

describe("executeLocal — read_file", () => {
  let root: string;

  beforeEach(() => {
    root = sandboxPath("readfile");
    mkdirSync(root, { recursive: true });
    process.env.REDPILOT_SCRATCH_DIR = root;
  });

  afterEach(() => {
    rmSync(root, { recursive: true, force: true });
    delete process.env.REDPILOT_SCRATCH_DIR;
  });

  it("reads an existing file", async () => {
    writeFileSync(join(root, "data.txt"), "hello from test file");

    const result = await executeLocal(toolCall("read_file", { path: "data.txt" }));
    expect(result!.status).toBe("success");
    expect(result!.details).toContain("hello from test file");
    expect(result!.summary).toContain("data.txt");
    expect(result!.summary).toContain("20 bytes");
  });

  it("returns error for non-existent file", async () => {
    const result = await executeLocal(toolCall("read_file", { path: "not_here.txt" }));
    expect(result!.status).toBe("error");
    // The summary may vary depending on which error fires first:
    // "File not found" (resolveSafePathMustExist) or "Failed to read file" (catch-all)
    expect(result!.details.toLowerCase()).toContain("not");
    expect(result!.details.toLowerCase()).toContain("exist");
  });

  it("returns error for missing path argument", async () => {
    const result = await executeLocal(toolCall("read_file", {}));
    expect(result!.status).toBe("error");
    expect(result!.summary).toContain("No path");
  });

  it("returns error for path outside sandbox", async () => {
    const result = await executeLocal(toolCall("read_file", { path: "/etc/passwd" }));
    expect(result!.status).toBe("error");
    expect(result!.summary).toContain("not allowed");
  });

  it("reads a file in a subdirectory", async () => {
    mkdirSync(join(root, "nested"), { recursive: true });
    writeFileSync(join(root, "nested", "secret.txt"), "nested content");

    const result = await executeLocal(toolCall("read_file", { path: "nested/secret.txt" }));
    expect(result!.status).toBe("success");
    expect(result!.details).toContain("nested content");
  });
});

// ======================================================================
// write_file
// ======================================================================

describe("executeLocal — write_file", () => {
  let root: string;

  beforeEach(() => {
    root = sandboxPath("writefile");
    mkdirSync(root, { recursive: true });
    process.env.REDPILOT_SCRATCH_DIR = root;
  });

  afterEach(() => {
    rmSync(root, { recursive: true, force: true });
    delete process.env.REDPILOT_SCRATCH_DIR;
  });

  it("writes a new file in the sandbox", async () => {
    const result = await executeLocal(toolCall("write_file", {
      path: "new_file.txt",
      content: "file content here",
    }));
    expect(result!.status).toBe("success");
    expect(result!.summary).toContain("new_file.txt");
    expect(result!.summary).toContain("17 bytes");

    // Verify on disk
    expect(readFileSync(join(root, "new_file.txt"), "utf-8")).toBe("file content here");
  });

  it("creates parent directories when writing", async () => {
    const result = await executeLocal(toolCall("write_file", {
      path: "deep/nested/file.txt",
      content: "deep content",
    }));
    expect(result!.status).toBe("success");
    expect(existsSync(join(root, "deep", "nested", "file.txt"))).toBe(true);
    expect(readFileSync(join(root, "deep", "nested", "file.txt"), "utf-8")).toBe("deep content");
  });

  it("overwrites an existing file", async () => {
    writeFileSync(join(root, "existing.txt"), "old content");

    const result = await executeLocal(toolCall("write_file", {
      path: "existing.txt",
      content: "new content",
    }));
    expect(result!.status).toBe("success");
    expect(readFileSync(join(root, "existing.txt"), "utf-8")).toBe("new content");
  });

  it("returns error for path outside sandbox", async () => {
    const result = await executeLocal(toolCall("write_file", {
      path: "/etc/evil.txt",
      content: "bad stuff",
    }));
    expect(result!.status).toBe("error");
    expect(result!.summary).toContain("not allowed");
  });

  it("returns error for path with ../ traversal", async () => {
    const result = await executeLocal(toolCall("write_file", {
      path: "../outside.txt",
      content: "leaked",
    }));
    expect(result!.status).toBe("error");
    expect(result!.summary).toContain("not allowed");
  });

  it("returns error for missing path argument", async () => {
    const result = await executeLocal(toolCall("write_file", {}));
    expect(result!.status).toBe("error");
    expect(result!.summary).toContain("No path");
  });
});

// ======================================================================
// edit_file
// ======================================================================

describe("executeLocal — edit_file", () => {
  let root: string;

  beforeEach(() => {
    root = sandboxPath("editfile");
    mkdirSync(root, { recursive: true });
    process.env.REDPILOT_SCRATCH_DIR = root;
  });

  afterEach(() => {
    rmSync(root, { recursive: true, force: true });
    delete process.env.REDPILOT_SCRATCH_DIR;
  });

  it("replaces a string in an existing file", async () => {
    writeFileSync(join(root, "config.txt"), "api_key = OLD_KEY\nport = 8080\n");

    const result = await executeLocal(toolCall("edit_file", {
      path: "config.txt",
      old_string: "OLD_KEY",
      new_string: "NEW_KEY",
    }));
    expect(result!.status).toBe("success");
    expect(result!.summary).toContain("config.txt");

    const content = readFileSync(join(root, "config.txt"), "utf-8");
    expect(content).toContain("NEW_KEY");
    expect(content).not.toContain("OLD_KEY");
  });

  it("returns error when old_string is not found", async () => {
    writeFileSync(join(root, "config.txt"), "api_key = SOME_KEY\n");

    const result = await executeLocal(toolCall("edit_file", {
      path: "config.txt",
      old_string: "NOT_THERE",
      new_string: "replacement",
    }));
    expect(result!.status).toBe("error");
    expect(result!.summary).toContain("not found");
  });

  it("returns error when old_string matches multiple times", async () => {
    writeFileSync(join(root, "config.txt"), "duplicate\nduplicate\n");

    const result = await executeLocal(toolCall("edit_file", {
      path: "config.txt",
      old_string: "duplicate",
      new_string: "replaced",
    }));
    expect(result!.status).toBe("error");
    expect(result!.summary).toContain("Multiple occurrences");
  });

  it("returns error for file outside sandbox", async () => {
    const result = await executeLocal(toolCall("edit_file", {
      path: "/etc/hosts",
      old_string: "127.0.0.1",
      new_string: "0.0.0.0",
    }));
    expect(result!.status).toBe("error");
    expect(result!.summary).toContain("not allowed");
  });

  it("returns error for non-existent file", async () => {
    const result = await executeLocal(toolCall("edit_file", {
      path: "missing.txt",
      old_string: "old",
      new_string: "new",
    }));
    expect(result!.status).toBe("error");
    expect(result!.summary).toContain("not found");
  });

  it("returns error for missing path argument", async () => {
    const result = await executeLocal(toolCall("edit_file", {
      old_string: "old",
      new_string: "new",
    }));
    expect(result!.status).toBe("error");
    expect(result!.summary).toContain("No path");
  });

  it("returns error for missing old_string argument", async () => {
    const result = await executeLocal(toolCall("edit_file", {
      path: "x.txt",
      new_string: "new",
    }));
    expect(result!.status).toBe("error");
    expect(result!.summary).toContain("No old_string");
  });
});
