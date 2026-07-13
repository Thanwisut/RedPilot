import { describe, it, expect } from "vitest";

import { checkCommandSafety, CommandBlockedError } from "../command-safety.js";

// ======================================================================
// checkCommandSafety
// ======================================================================

describe("checkCommandSafety", () => {
  // ── Basic validation ──────────────────────────────────────────

  it("allows a basic safe command", () => {
    const result = checkCommandSafety(["ls", "-la", "/tmp"]);
    expect(result.allowed).toBe(true);
    expect(result.reason).toBeUndefined();
  });

  it("allows echo with arguments", () => {
    const result = checkCommandSafety(["echo", "hello", "world"]);
    expect(result.allowed).toBe(true);
  });

  it("allows standard system tools", () => {
    const safeCommands = [
      ["cat", "/etc/hostname"],
      ["echo", "test"],
      ["grep", "pattern", "file.txt"],
      ["find", ".", "-name", "*.ts"],
      ["head", "-n", "10", "file.txt"],
      ["tail", "-f", "log.txt"],
      ["sort", "data.txt"],
      ["wc", "-l", "file.txt"],
      ["ps", "aux"],
      ["date"],
      ["whoami"],
      ["env"],
      ["pwd"],
      ["which", "node"],
    ];
    for (const cmd of safeCommands) {
      const result = checkCommandSafety(cmd);
      expect(result.allowed).toBe(true), `Expected '${cmd[0]}' to be allowed`;
    }
  });

  // ── Empty / invalid input ─────────────────────────────────────

  it("blocks an empty command", () => {
    const result = checkCommandSafety([]);
    expect(result.allowed).toBe(false);
    expect(result.reason).toContain("Empty");
  });

  it("blocks command with null byte in argument", () => {
    const result = checkCommandSafety(["echo", "hello\0world"]);
    expect(result.allowed).toBe(false);
    expect(result.reason).toContain("null byte");
  });

  it("blocks null byte in executable name", () => {
    const result = checkCommandSafety(["ec\0ho", "test"]);
    expect(result.allowed).toBe(false);
    expect(result.reason).toContain("null byte");
  });

  // ── Blocked commands ──────────────────────────────────────────

  it("blocks rm", () => {
    const result = checkCommandSafety(["rm", "-rf", "/tmp"]);
    expect(result.allowed).toBe(false);
    expect(result.reason).toContain("rm");
  });

  it("blocks rm with absolute path", () => {
    const result = checkCommandSafety(["rm", "-rf", "/var/log"]);
    expect(result.allowed).toBe(false);
  });

  it("blocks rmdir", () => {
    const result = checkCommandSafety(["rmdir", "/tmp/dir"]);
    expect(result.allowed).toBe(false);
  });

  it("blocks sudo", () => {
    const result = checkCommandSafety(["sudo", "ls"]);
    expect(result.allowed).toBe(false);
    expect(result.reason).toContain("sudo");
  });

  it("blocks docker", () => {
    const result = checkCommandSafety(["docker", "ps"]);
    expect(result.allowed).toBe(false);
    expect(result.reason).toContain("docker");
  });

  it("blocks podman", () => {
    const result = checkCommandSafety(["podman", "run", "--rm", "alpine"]);
    expect(result.allowed).toBe(false);
  });

  it("blocks chmod", () => {
    const result = checkCommandSafety(["chmod", "+x", "script.sh"]);
    expect(result.allowed).toBe(false);
  });

  it("blocks chown", () => {
    const result = checkCommandSafety(["chown", "root:root", "file"]);
    expect(result.allowed).toBe(false);
  });

  it("blocks curl", () => {
    const result = checkCommandSafety(["curl", "https://evil.com"]);
    expect(result.allowed).toBe(false);
    expect(result.reason).toContain("curl");
  });

  it("blocks wget", () => {
    const result = checkCommandSafety(["wget", "https://evil.com"]);
    expect(result.allowed).toBe(false);
  });

  it("blocks nc / netcat", () => {
    const result = checkCommandSafety(["nc", "-l", "-p", "9999"]);
    expect(result.allowed).toBe(false);
  });

  it("blocks dd (disk destroyer)", () => {
    const result = checkCommandSafety(["dd", "if=/dev/zero", "of=/dev/sda"]);
    expect(result.allowed).toBe(false);
  });

  it("blocks mkfs (filesystem formatter)", () => {
    const result = checkCommandSafety(["mkfs.ext4", "/dev/sda1"]);
    expect(result.allowed).toBe(false);
  });

  it("blocks fdisk", () => {
    const result = checkCommandSafety(["fdisk", "/dev/sda"]);
    expect(result.allowed).toBe(false);
  });

  it("blocks kill", () => {
    const result = checkCommandSafety(["kill", "-9", "1234"]);
    expect(result.allowed).toBe(false);
  });

  it("blocks iptables", () => {
    const result = checkCommandSafety(["iptables", "-F"]);
    expect(result.allowed).toBe(false);
  });

  it("blocks mount", () => {
    const result = checkCommandSafety(["mount", "/dev/sda1", "/mnt"]);
    expect(result.allowed).toBe(false);
  });

  it("blocks shutdown", () => {
    const result = checkCommandSafety(["shutdown", "-h", "now"]);
    expect(result.allowed).toBe(false);
  });

  it("blocks passwd", () => {
    const result = checkCommandSafety(["passwd", "root"]);
    expect(result.allowed).toBe(false);
  });

  // ── Blocked by executable path with blocked base name ─────────

  it("blocks command with absolute path to a dangerous executable", () => {
    const result = checkCommandSafety(["/usr/bin/rm", "-rf", "/"]);
    expect(result.allowed).toBe(false);
    expect(result.reason).toContain("rm");
  });

  it("blocks command with relative path to a dangerous executable", () => {
    const result = checkCommandSafety(["./docker", "ps"]);
    expect(result.allowed).toBe(false);
    expect(result.reason).toContain("docker");
  });

  // ── Dangerous patterns ────────────────────────────────────────

  it("blocks rm -rf / pattern", () => {
    const result = checkCommandSafety(["rm", "-rf", "/"]);
    expect(result.allowed).toBe(false);
  });

  it("blocks mkfs pattern", () => {
    const result = checkCommandSafety(["somecmd", "--format", "mkfs.ext4"]);
    expect(result.allowed).toBe(false);
  });

  // ── Length limits ─────────────────────────────────────────────

  it("blocks command with too many arguments", () => {
    const manyArgs = ["echo"];
    for (let i = 0; i < 150; i++) {
      manyArgs.push(`arg${i}`);
    }
    const result = checkCommandSafety(manyArgs);
    expect(result.allowed).toBe(false);
    expect(result.reason).toContain("arguments");
  });

  it("blocks command with too-long argument", () => {
    const tooLong = ["echo", "a".repeat(5000)];
    const result = checkCommandSafety(tooLong);
    expect(result.allowed).toBe(false);
    expect(result.reason).toContain("too long");
  });

  it("blocks extremely long command string", () => {
    const longArg = ["echo", "a".repeat(70000)];
    const result = checkCommandSafety(longArg);
    expect(result.allowed).toBe(false);
    expect(result.reason).toContain("too long");
  });

  // ── Safe edge cases ──────────────────────────────────────────

  it("allows git commands", () => {
    const result = checkCommandSafety(["git", "status"]);
    expect(result.allowed).toBe(true);
  });

  it("allows node commands", () => {
    const result = checkCommandSafety(["node", "script.js"]);
    expect(result.allowed).toBe(true);
  });

  it("allows python commands", () => {
    const result = checkCommandSafety(["python3", "-c", "print('hello')"]);
    expect(result.allowed).toBe(true);
  });

  it("allows npm commands", () => {
    const result = checkCommandSafety(["npm", "test"]);
    expect(result.allowed).toBe(true);
  });

  it("allows commands with dashes in arguments", () => {
    const result = checkCommandSafety(["echo", "--flag", "value"]);
    expect(result.allowed).toBe(true);
  });

  // ── Case sensitivity ──────────────────────────────────────────

  it("blocks RM (uppercase) — the rm -rf / pattern is case-insensitive by design for safety", () => {
    const result = checkCommandSafety(["RM", "-RF", "/"]);
    // The BLOCKED_PATTERNS regex /rm\s*-rf?\s*\/$/i is case-insensitive
    // so uppercase RM -RF / also triggers the pattern match
    expect(result.allowed).toBe(false);
    expect(result.reason).toContain("blocked pattern");
  });
});

// ======================================================================
// CommandBlockedError
// ======================================================================

describe("CommandBlockedError", () => {
  it("has correct name and message", () => {
    const err = new CommandBlockedError("rm is dangerous");
    expect(err.name).toBe("CommandBlockedError");
    expect(err.message).toContain("rm is dangerous");
    expect(err.message).toContain("blocked");
    expect(err instanceof Error).toBe(true);
  });
});
