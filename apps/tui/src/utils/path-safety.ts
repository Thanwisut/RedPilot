/** Path safety — containment checks for local filesystem operations.
 *
 * Every filesystem tool (list_directory, read_file, write_file, edit_file)
 * must validate that the requested path stays within the sandbox root.
 *
 * The sandbox root defaults to ~/.redpilot/scratch/ and can be overridden
 * via the REDPILOT_SCRATCH_DIR env var.
 *
 * Uses Path.resolve() semantics: resolving a relative path joins it to the
 * root, while resolving an absolute path replaces the root entirely.
 * The startsWith(root) check catches all escape attempts including:
 *   - ../ traversal resolving above the root
 *   - Absolute paths like /etc/passwd that replace the root
 *   - Symlink escapes (handled at the OS level by resolve())
 */

import { existsSync, mkdirSync } from "node:fs";
import { homedir } from "node:os";
import { resolve } from "node:path";

export class PathEscapeError extends Error {
  constructor(path: string, root: string) {
    super(
      `Path '${path}' escapes the sandbox root '${root}'. ` +
      "Path traversal and absolute paths outside the sandbox are not allowed.",
    );
    this.name = "PathEscapeError";
  }
}

/** Get the sandbox root directory. */
export function getSandboxRoot(): string {
  const envDir = typeof process !== "undefined"
    ? process.env.REDPILOT_SCRATCH_DIR
    : undefined;
  return envDir ?? resolve(homedir(), ".redpilot", "scratch");
}

/** Ensure the sandbox root directory exists. */
export function ensureSandboxRoot(): string {
  const root = getSandboxRoot();
  mkdirSync(root, { recursive: true });
  return root;
}

/**
 * Resolve a path relative to the sandbox root and validate containment.
 *
 * Uses a single guard: resolve the path, then verify the resolved path
 * starts with the sandbox root. This catches:
 *   - ``../etc/passwd`` → resolves above root → rejected by startsWith
 *   - ``/etc/passwd`` → absolute replaces root → rejected by startsWith
 *   - ``subdir/../../../etc`` → normalizes above root → rejected by startsWith
 *
 * @param requestedPath - The user/LLM-supplied path (relative or absolute)
 * @param sandboxRoot - The allowed root directory (defaults to getSandboxRoot())
 * @returns The resolved, contained absolute path
 * @throws PathEscapeError if the path escapes the sandbox
 */
export function resolveSafePath(
  requestedPath: string,
  sandboxRoot?: string,
): string {
  const root = resolve(sandboxRoot ?? getSandboxRoot());

  // Reject null bytes
  if (requestedPath.includes("\0")) {
    throw new PathEscapeError(requestedPath, root);
  }

  // Resolve: Path.resolve() normalizes .. and treats absolute paths as-is
  const resolved = resolve(root, requestedPath);

  // Single guard: resolved path must start with the root.
  // Use root + "/" separator to prevent bypass: e.g. "/dir/scratch-other/file"
  // starts with "/dir/scratch" but is outside the sandbox.
  const rootGuard = root.endsWith("/") ? root : root + "/";
  if (resolved !== root && !resolved.startsWith(rootGuard)) {
    throw new PathEscapeError(requestedPath, root);
  }

  return resolved;
}

/**
 * Like resolveSafePath, but also verifies the path exists on disk.
 * @throws PathEscapeError if path escapes
 * @throws Error if path doesn't exist
 */
export function resolveSafePathMustExist(
  requestedPath: string,
  sandboxRoot?: string,
): string {
  const resolved = resolveSafePath(requestedPath, sandboxRoot);
  if (!existsSync(resolved)) {
    throw new Error(
      `Path '${requestedPath}' does not exist (resolved to '${resolved}')`,
    );
  }
  return resolved;
}
