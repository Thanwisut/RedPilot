#!/usr/bin/env tsx
/**
 * headless-runner.ts — M2: NON-INTERACTIVE HEADLESS MODE
 *
 * Usage:
 *   tsx src/debug/headless-runner.ts --script <path> [options]
 *
 * This is a STANDALONE entry point (NOT imported by index.tsx). It:
 *   1. Starts the mock server on an ephemeral port
 *   2. Renders the TUI using ink-testing-library-style captured I/O
 *   3. Plays a scripted sequence of inputs through Ink's real input path
 *   4. Captures all frames and state
 *   5. Dumps the result as JSON to stdout (or a file)
 *   6. Exits with code 0 (success) or non-zero (failure)
 *
 * This is CI-friendly — no interactive terminal needed.
 */

import { writeFileSync } from "node:fs";
import { startTestServer } from "../screens/setupTestServer.js";
import { ScriptPlayer } from "./script-player.js";
import { enableDebug } from "./debug-logger.js";

// ---------------------------------------------------------------------------
// CLI arg parsing
// ---------------------------------------------------------------------------

function parseArgs(): {
  scriptPath: string | null;
  outputPath: string | null;
  debug: boolean;
  preConfigured: boolean;
  help: boolean;
} {
  const args = process.argv.slice(2);
  let scriptPath: string | null = null;
  let outputPath: string | null = null;
  let debug = false;
  let preConfigured = false;
  let help = false;

  for (let i = 0; i < args.length; i++) {
    switch (args[i]) {
      case "--script":
      case "-s":
        scriptPath = args[++i] ?? null;
        break;
      case "--output":
      case "-o":
        outputPath = args[++i] ?? null;
        break;
      case "--debug":
      case "-d":
        debug = true;
        break;
      case "--pre-configured":
      case "-c":
        preConfigured = true;
        break;
      case "--help":
      case "-h":
        help = true;
        break;
      default:
        console.error(`Unknown option: ${args[i]}`);
        process.exit(1);
    }
  }

  return { scriptPath, outputPath, debug, preConfigured, help };
}

// ---------------------------------------------------------------------------
// Help
// ---------------------------------------------------------------------------

function printHelp(): void {
  console.log(`
REDPILOT TUI — Headless mode

Run the TUI non-interactively with a scripted input file, capturing all
rendered frames and internal state for debugging or CI verification.

Usage:
  tsx src/debug/headless-runner.ts --script <path> [options]

Options:
  --script, -s <path>     Path to JSON script file (required)
  --output, -o <path>     Write JSON state dump to file instead of stdout
  --debug, -d             Enable debug logging
  --help, -h              Show this help

Exit codes:
  0   Script completed successfully
  1   Assertion failed during script execution
  2   Script timed out
  3   Internal error (server startup, rendering, etc.)

Examples:
  tsx src/debug/headless-runner.ts --script scripts/splash-wide.json
  tsx src/debug/headless-runner.ts --script scripts/provider-opencode.json --output result.json
`);
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main(): Promise<void> {
  const { scriptPath, outputPath, debug, preConfigured, help } = parseArgs();

  if (help) {
    printHelp();
    process.exit(0);
  }

  if (!scriptPath) {
    console.error("Error: --script <path> is required");
    printHelp();
    process.exit(3);
  }

  if (debug) {
    enableDebug();
  }

  // ---- Start mock server on ephemeral port ----
  console.error(`[headless] Starting mock server (pre-configured: ${preConfigured})...`);
  const server = await startTestServer({ configured: preConfigured });
  const port = server.port;
  console.error(`[headless] Mock server running on port ${port}`);

  // ---- Create script player ----
  const player = new ScriptPlayer(scriptPath);
  const io = player.io;

  console.error(`[headless] Running script: ${scriptPath}`);
  console.error(`[headless] Columns: ${player.columns}, Rows: ${player.rows}`);

  // ---- Render the TUI ----
  // We need to render the App component with our custom I/O.
  // Dynamic import so the Ink render call uses our captured streams.
  const { render } = await import("ink");

  // We render a minimal version of the TUI that routes to the right screen.
  // For headless mode, we just render the App component which handles
  // screen routing internally.
  const { default: React } = await import("react");
  const { App } = await import("../index.js");

  const instance = render(React.createElement(App), {
    stdout: io.stdout as unknown as NodeJS.WriteStream,
    stderr: io.stderr as unknown as NodeJS.WriteStream,
    stdin: io.stdin as unknown as NodeJS.ReadStream,
    debug: true,
    exitOnCtrlC: false,
    patchConsole: false,
  });

  // Workaround: override fetch to use the correct port
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (
    input: string | URL | Request,
    init?: RequestInit,
  ) => {
    const url =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : (input as Request).url;

    // Rewrite API_BASE URL to use our test server port
    const rewritten = url
      .replace("http://localhost:8080", `http://localhost:${port}`)
      .replace("ws://localhost:8080", `ws://localhost:${port}`);

    player.recordRestCall({
      method: init?.method ?? "GET",
      url: rewritten,
      status: 0,
    });

    const response = await originalFetch(rewritten, init);
    player.recordRestCall({
      method: init?.method ?? "GET",
      url: rewritten,
      status: response.status,
    });
    return response;
  };

  // ---- Wait a tick for React to render initial state ----
  await new Promise((resolve) => setTimeout(resolve, 100));

  // Capture initial frame
  player.captureFrame("initial");

  // ---- Run the script ----
  const result = await player.run(30_000);

  // ---- Restore global fetch ----
  globalThis.fetch = originalFetch;

  // ---- Cleanup ----
  instance.unmount();
  instance.cleanup();
  await server.close();

  // ---- Output ----
  const json = JSON.stringify(result, null, 2);

  if (outputPath) {
    writeFileSync(outputPath, json, "utf-8");
    console.error(`[headless] Results written to ${outputPath}`);
  } else {
    console.log(json);
  }

  // ---- Exit with code ----
  if (result.exitReason === "completed") {
    console.error(`[headless] Script completed successfully`);
    process.exit(0);
  } else if (result.exitReason === "assertion_failed") {
    console.error(`[headless] Assertion failed: ${result.exitMessage}`);
    process.exit(1);
  } else if (result.exitReason === "timeout") {
    console.error(`[headless] Timed out: ${result.exitMessage}`);
    process.exit(2);
  } else {
    console.error(`[headless] Error: ${result.exitMessage}`);
    process.exit(3);
  }
}

main().catch((err) => {
  console.error(`[headless] Fatal error: ${err.message}`);
  process.exit(3);
});
