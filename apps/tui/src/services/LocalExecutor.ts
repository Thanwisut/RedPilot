/** LocalExecutor — runs shell_exec and filesystem tools on the host
 * using Node.js child_process and fs, with safety guards.
 *
 * This is the "local mode" fallback between WS backend and simulation.
 * It runs tools for real on the local machine when the Python backend
 * is not available.
 *
 * **Safety guards:**
 * - Path containment: all file ops scoped to ~/.redpilot/scratch/
 * - Command blocklist: rm, sudo, docker, chmod, mkfs, etc. blocked
 * - Path traversal: ../ and absolute paths outside sandbox rejected
 * - argv-only execution (never shell strings) for shell_exec
 */

import { spawn } from "node:child_process";
import { readFile, writeFile, readdir, mkdir } from "node:fs/promises";
import { join, relative } from "node:path";

import type { ToolCall } from "../providers/types.js";
import { checkCommandSafety } from "../utils/command-safety.js";
import {
  getSandboxRoot,
  ensureSandboxRoot,
  resolveSafePath,
  resolveSafePathMustExist,
  PathEscapeError,
} from "../utils/path-safety.js";

export interface LocalExecutionResult {
  status: "success" | "error";
  summary: string;
  details: string;
}

// ======================================================================
// SHELL EXEC
// ======================================================================

async function executeShellExec(args: Record<string, unknown>): Promise<LocalExecutionResult> {
  const command = args.command as string[] | undefined;
  if (!command || !Array.isArray(command) || command.length === 0) {
    return {
      status: "error",
      summary: "No command provided",
      details: "The 'command' argument must be a non-empty array of strings.",
    };
  }

  // Validate every element is a string
  for (let i = 0; i < command.length; i++) {
    if (typeof command[i] !== "string") {
      return {
        status: "error",
        summary: "Invalid command argument",
        details: `Element ${i} of 'command' must be a string, got ${typeof command[i]}`,
      };
    }
  }

  // Safety check against command blocklist
  const safety = checkCommandSafety(command as string[]);
  if (!safety.allowed) {
    return {
      status: "error",
      summary: "Command blocked by safety guard",
      details: `Reason: ${safety.reason}\n\nCommand: ${command.join(" ")}\n\nTip: Use the WebSocket backend (start the Python server) for dangerous commands, or use a different approach.`,
    };
  }

  // Run the command via spawn (argv-only, no shell)
  try {
    const stdout: string[] = [];
    const stderr: string[] = [];
    let exitCode = 0;

    await new Promise<void>((resolve, reject) => {
      const child = spawn(command[0]!, command.slice(1), {
        timeout: 30_000, // 30s timeout
        stdio: ["ignore", "pipe", "pipe"],
        windowsHide: true,
      });

      child.stdout?.on("data", (data: Buffer) => {
        stdout.push(data.toString());
      });

      child.stderr?.on("data", (data: Buffer) => {
        stderr.push(data.toString());
      });

      child.on("close", (code) => {
        exitCode = code ?? -1;
        resolve();
      });

      child.on("error", (err) => {
        reject(err);
      });
    });

    const stdoutStr = stdout.join("");
    const stderrStr = stderr.join("");

    if (exitCode === 0) {
      return {
        status: "success",
        summary: `Command completed (exit code 0)`,
        details: [
          `Command: ${command.join(" ")}`,
          `Exit code: 0`,
          `stdout: ${stdoutStr.slice(0, 2000) || "(empty)"}`,
          stderrStr ? `stderr: ${stderrStr.slice(0, 1000)}` : "",
        ].filter(Boolean).join("\n"),
      };
    } else {
      return {
        status: "error",
        summary: `Command failed (exit code ${exitCode})`,
        details: [
          `Command: ${command.join(" ")}`,
          `Exit code: ${exitCode}`,
          stdoutStr ? `stdout: ${stdoutStr.slice(0, 2000)}` : "",
          stderrStr ? `stderr: ${stderrStr.slice(0, 1000)}` : "",
        ].filter(Boolean).join("\n"),
      };
    }
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);
    return {
      status: "error",
      summary: "Command execution failed",
      details: `Error: ${msg}\nCommand: ${command.join(" ")}`,
    };
  }
}

// ======================================================================
// LIST DIRECTORY
// ======================================================================

async function executeListDirectory(args: Record<string, unknown>): Promise<LocalExecutionResult> {
  const path = (args.path as string) ?? "";
  const recursive = args.recursive === true;

  try {
    const sandboxRoot = ensureSandboxRoot();
    const resolved = resolveSafePath(path || ".", sandboxRoot);

    // Use readdir with recursive option if available (Node 20+)
    const entries: string[] = [];
    const dirs: string[] = [];

    async function scan(dir: string, prefix: string): Promise<void> {
      const items = await readdir(dir, { withFileTypes: true });
      for (const item of items) {
        const fullPath = join(dir, item.name);
        const relPath = join(prefix, item.name);
        if (item.isDirectory()) {
          dirs.push(`${relPath}/`);
          if (recursive) {
            await scan(fullPath, relPath);
          }
        } else {
          entries.push(relPath);
        }
      }
    }

    await scan(resolved, "");

    const allItems = [...entries, ...dirs].sort();
    const sandboxRelDir = relative(sandboxRoot, resolved) || ".";

    return {
      status: "success",
      summary: `Listed directory: ${sandboxRelDir} (${allItems.length} entries)`,
      details: [
        `Path: ${sandboxRelDir}`,
        `Absolute: ${resolved}`,
        "",
        ...allItems.map((item) => `  ${item}`),
        "",
        `${allItems.length} entries found.`,
      ].join("\n"),
    };
  } catch (err: unknown) {
    if (err instanceof PathEscapeError) {
      return { status: "error", summary: "Path not allowed", details: err.message };
    }
    const msg = err instanceof Error ? err.message : String(err);
    return { status: "error", summary: "Failed to list directory", details: msg };
  }
}

// ======================================================================
// READ FILE
// ======================================================================

async function executeReadFile(args: Record<string, unknown>): Promise<LocalExecutionResult> {
  const path = (args.path as string) ?? "";

  if (!path) {
    return { status: "error", summary: "No path specified", details: "The 'path' argument is required." };
  }

  try {
    const sandboxRoot = getSandboxRoot();
    const resolved = resolveSafePathMustExist(path, sandboxRoot);

    const content = await readFile(resolved, "utf-8");
    const maxBytes = 100_000;
    const truncated = content.length > maxBytes;

    return {
      status: "success",
      summary: `Read file: ${relative(sandboxRoot, resolved)} (${content.length} bytes)`,
      details: [
        `File: ${relative(sandboxRoot, resolved)}`,
        `Size: ${content.length} bytes`,
        truncated ? `(showing first ${maxBytes} bytes)` : "",
        "",
        truncated ? content.slice(0, maxBytes) : content,
        truncated ? `\n... (${content.length - maxBytes} more bytes)` : "",
      ].filter(Boolean).join("\n"),
    };
  } catch (err: unknown) {
    if (err instanceof PathEscapeError) {
      return { status: "error", summary: "Path not allowed", details: err.message };
    }
    const msg = err instanceof Error ? err.message : String(err);
    return { status: "error", summary: "Failed to read file", details: msg };
  }
}

// ======================================================================
// WRITE FILE
// ======================================================================

async function executeWriteFile(args: Record<string, unknown>): Promise<LocalExecutionResult> {
  const path = (args.path as string) ?? "";
  const content = (args.content as string) ?? "";

  if (!path) {
    return { status: "error", summary: "No path specified", details: "The 'path' argument is required." };
  }

  try {
    const sandboxRoot = ensureSandboxRoot();
    const resolved = resolveSafePath(path, sandboxRoot);

    // Ensure parent directory exists
    const parent = join(resolved, "..");
    await mkdir(parent, { recursive: true });

    await writeFile(resolved, content, "utf-8");

    return {
      status: "success",
      summary: `Wrote ${content.length} bytes to ${relative(sandboxRoot, resolved)}`,
      details: [
        `File: ${relative(sandboxRoot, resolved)}`,
        `Absolute: ${resolved}`,
        `Bytes written: ${content.length}`,
        "",
        "Note: In production this requires human approval.",
      ].join("\n"),
    };
  } catch (err: unknown) {
    if (err instanceof PathEscapeError) {
      return { status: "error", summary: "Path not allowed", details: err.message };
    }
    const msg = err instanceof Error ? err.message : String(err);
    return { status: "error", summary: "Failed to write file", details: msg };
  }
}

// ======================================================================
// EDIT FILE
// ======================================================================

async function executeEditFile(args: Record<string, unknown>): Promise<LocalExecutionResult> {
  const path = (args.path as string) ?? "";
  const oldStr = (args.old_string as string) ?? "";
  const newStr = (args.new_string as string) ?? "";

  if (!path) {
    return { status: "error", summary: "No path specified", details: "The 'path' argument is required." };
  }
  if (!oldStr) {
    return { status: "error", summary: "No old_string specified", details: "The 'old_string' argument is required." };
  }

  try {
    const sandboxRoot = getSandboxRoot();
    const resolved = resolveSafePathMustExist(path, sandboxRoot);

    const content = await readFile(resolved, "utf-8");

    // Find all occurrences
    const firstIndex = content.indexOf(oldStr);
    if (firstIndex === -1) {
      return {
        status: "error",
        summary: "String not found",
        details: `The string '${oldStr.slice(0, 100)}' was not found in the file.`,
      };
    }

    // Count occurrences
    const count = content.split(oldStr).length - 1;
    if (count > 1) {
      return {
        status: "error",
        summary: "Multiple occurrences found",
        details: `Found ${count} occurrences of the string. For safety, edit_file only works with unique strings. Found in file: ${relative(sandboxRoot, resolved)}`,
      };
    }

    const newContent = content.replace(oldStr, newStr);
    await writeFile(resolved, newContent, "utf-8");

    return {
      status: "success",
      summary: `Replaced 1 occurrence in ${relative(sandboxRoot, resolved)}`,
      details: [
        `File: ${relative(sandboxRoot, resolved)}`,
        `Replaced: "${oldStr.slice(0, 100)}"`,
        `With: "${newStr.slice(0, 100)}"`,
        "",
        "Note: In production this requires human approval.",
      ].join("\n"),
    };
  } catch (err: unknown) {
    if (err instanceof PathEscapeError) {
      return { status: "error", summary: "Path not allowed", details: err.message };
    }
    if (err instanceof Error && err.message.includes("does not exist")) {
      return { status: "error", summary: "File not found", details: err.message };
    }
    const msg = err instanceof Error ? err.message : String(err);
    return { status: "error", summary: "Failed to edit file", details: msg };
  }
}

// ======================================================================
// Public dispatch
// ======================================================================

/**
 * Execute a tool locally using Node.js APIs.
 *
 * @param toolCall - The tool call to execute
 * @returns Execution result, or null if the tool isn't a local-mode tool
 */
export async function executeLocal(toolCall: ToolCall): Promise<LocalExecutionResult | null> {
  switch (toolCall.name) {
    case "shell_exec":
      return executeShellExec(toolCall.arguments);
    case "list_directory":
      return executeListDirectory(toolCall.arguments);
    case "read_file":
      return executeReadFile(toolCall.arguments);
    case "write_file":
      return executeWriteFile(toolCall.arguments);
    case "edit_file":
      return executeEditFile(toolCall.arguments);
    default:
      return null; // Not a local-mode tool
  }
}
