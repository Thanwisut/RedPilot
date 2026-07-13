/** Command safety — blocklist/allowlist for local shell_exec mode.
 *
 * Before executing a shell command on the host, we check against a
 * blocklist of dangerous commands and patterns. This is defense-in-depth:
 * the command is always passed as argv list (not a shell string), and
 * each argv element is validated individually.
 */

/** Commands that are NEVER allowed in local mode, regardless of arguments. */
const BLOCKED_COMMANDS = new Set([
  "rm", "rmdir", "del", "deltree",   // Deletion
  "dd", "mkfs", "fdisk", "parted",    // Disk operations
  "chmod", "chown", "chgrp",          // Permission changes
  "sudo", "su", "doas", "pkexec",     // Privilege escalation
  "passwd", "useradd", "userdel",     // User management
  "shutdown", "reboot", "halt",       // System control
  "mount", "umount", "swapoff",       // Mount operations
  "insmod", "rmmod", "modprobe",      // Kernel modules
  "iptables", "nft", "ufw",           // Firewall
  "docker", "podman", "nerdctl",      // Containers
  "kill", "killall", "pkill",         // Process control
  "nohup", "disown", "bg", "fg",     // Job control in background
  "wget", "curl", "nc", "netcat",     // Network download (could fetch malware)
]);

/** Patterns that are NEVER allowed in any argv element. */
const BLOCKED_PATTERNS = [
  /rm\s*-rf?\s*\/$/i,             // rm -rf /
  /:\(\s*\)\s*\{[^}]*\}\s*;/,     // Fork bomb
  /mkfs/,                          // Format filesystem
  /\/dev\/(sd[a-z]|nvme[0-9]|hd[a-z])\b/,  // Raw disk device
];

/** Maximum argv length for a single command. */
const MAX_ARGV_LENGTH = 100;

/** Maximum single argument length. */
const MAX_ARG_LENGTH = 4096;

/** Maximum total command string length. */
const MAX_COMMAND_LENGTH = 65536;

export class CommandBlockedError extends Error {
  constructor(reason: string) {
    super(`Command blocked by safety guard: ${reason}`);
    this.name = "CommandBlockedError";
  }
}

export interface CommandSafetyResult {
  allowed: boolean;
  reason?: string;
}

/**
 * Validate a command for local execution.
 *
 * @param argv - The command as a list of strings
 * @returns A safety result with reason if blocked
 */
export function checkCommandSafety(argv: string[]): CommandSafetyResult {
  // Check length limits
  if (argv.length === 0) {
    return { allowed: false, reason: "Empty command" };
  }
  if (argv.length > MAX_ARGV_LENGTH) {
    return {
      allowed: false,
      reason: `Command has ${argv.length} arguments (max ${MAX_ARGV_LENGTH})`,
    };
  }

  const commandStr = argv.join(" ");
  if (commandStr.length > MAX_COMMAND_LENGTH) {
    return {
      allowed: false,
      reason: `Command too long (${commandStr.length} chars, max ${MAX_COMMAND_LENGTH})`,
    };
  }

  // Check each argv element
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i]!;

    // Check length
    if (arg.length > MAX_ARG_LENGTH) {
      return {
        allowed: false,
        reason: `Argument ${i} too long (${arg.length} chars, max ${MAX_ARG_LENGTH})`,
      };
    }

    // Check for null bytes
    if (arg.includes("\0")) {
      return { allowed: false, reason: `Argument ${i} contains null byte` };
    }
  }

  // Check the executable (first element)
  const executable = argv[0]!;
  const execName = executable.split("/").pop() ?? executable;

  // Block known dangerous commands
  if (BLOCKED_COMMANDS.has(execName)) {
    return {
      allowed: false,
      reason: `Command '${execName}' is blocked for security reasons`,
    };
  }

  // Check the full command string for dangerous patterns
  for (const pattern of BLOCKED_PATTERNS) {
    if (pattern.test(commandStr)) {
      return {
        allowed: false,
        reason: `Command matches blocked pattern: ${pattern}`,
      };
    }
  }

  return { allowed: true };
}
