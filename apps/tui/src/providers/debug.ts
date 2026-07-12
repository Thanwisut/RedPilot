/** Debug logging — only writes to stderr when --debug or REDPILOT_DEBUG=1 */

let _enabled: boolean | null = null;

function isDebug(): boolean {
  if (_enabled === null) {
    _enabled =
      process.env.REDPILOT_DEBUG === "1" ||
      process.argv.includes("--debug");
  }
  return _enabled;
}

export function debugLog(...args: unknown[]): void {
  if (isDebug()) {
    console.error(...args);
  }
}
