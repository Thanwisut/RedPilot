/** Playwright MCP wrapper — executes browser actions using @playwright/mcp.
 *
 * Spawns @playwright/mcp as an MCP server via stdio transport, connects
 * via the MCP client, calls the requested browser tool, and returns the result.
 *
 * This replaces the Python-based redpilot-browser CLI for local mode.
 * The backend (server.py) can also use this approach when run locally.
 *
 * Mapped actions:
 *   navigate  → browser_navigate
 *   click     → browser_click
 *   type      → browser_type
 *   scroll    → browser_scroll
 *   screenshot → browser_screenshot
 *   execute_js → browser_run_code_unsafe
 */

import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

export interface BrowserActionResult {
  action: string;
  success: boolean;
  data?: string;
  screenshot?: string;
  error?: string;
}

const ACTION_MAP: Record<string, string> = {
  navigate: "browser_navigate",
  click: "browser_click",
  type: "browser_type",
  scroll: "browser_scroll",
  screenshot: "browser_screenshot",
  execute_js: "browser_run_code_unsafe",
};

const SUPPORTED_ACTIONS = Object.keys(ACTION_MAP);

/** Maximum time to wait for browser action (ms). */
const BROWSER_TIMEOUT = 30_000;

/** Cached client instance. Reused across calls within the same session. */
let cachedClient: {
  client: Client;
  transport: StdioClientTransport;
} | null = null;

async function getClient(): Promise<Client> {
  if (cachedClient) {
    // Check if the transport is still connected
    return cachedClient.client;
  }

  const transport = new StdioClientTransport({
    command: "npx",
    args: ["-y", "@playwright/mcp@latest"],
    stderr: "pipe",
  });

  const client = new Client(
    { name: "redpilot-browser", version: "1.0.0" },
    { capabilities: {} },
  );

  await client.connect(transport);
  cachedClient = { client, transport };
  return client;
}

function cleanupConnection(): void {
  if (cachedClient) {
    try {
      cachedClient.transport.close();
    } catch {
      // ignore
    }
    cachedClient = null;
  }
}

/**
 * Execute a browser action via Playwright MCP.
 *
 * @param action - The browser action to perform (navigate, click, type, etc.)
 * @param args - Arguments for the action (url, selector, value, script)
 * @returns Result with success status, data, and optional screenshot reference
 */
export async function executeBrowserAction(
  action: string,
  args: {
    url?: string;
    selector?: string;
    value?: string;
    script?: string;
  },
  options?: { timeoutMs?: number },
): Promise<BrowserActionResult> {
  const timeout = options?.timeoutMs ?? BROWSER_TIMEOUT;

  if (!SUPPORTED_ACTIONS.includes(action)) {
    return {
      action,
      success: false,
      error: `Unsupported browser action: "${action}". Supported: ${SUPPORTED_ACTIONS.join(", ")}`,
    };
  }

  const mcpAction = ACTION_MAP[action]!;

  // Build MCP arguments
  const mcpArgs: Record<string, unknown> = {};

  switch (action) {
    case "navigate":
      if (!args.url) {
        return { action, success: false, error: "URL is required for navigate action" };
      }
      mcpArgs.url = args.url;
      break;

    case "click":
      if (args.url) mcpArgs.url = args.url;
      if (args.selector) mcpArgs.selector = args.selector;
      break;

    case "type":
      if (args.selector) mcpArgs.selector = args.selector;
      if (args.value) mcpArgs.value = args.value;
      if (args.url) mcpArgs.url = args.url;
      break;

    case "scroll":
      if (args.selector) mcpArgs.selector = args.selector;
      break;

    case "screenshot":
      if (args.url) mcpArgs.url = args.url;
      // Optional: pass selector for element screenshot
      if (args.selector) mcpArgs.selector = args.selector;
      break;

    case "execute_js":
      if (!args.script) {
        return { action, success: false, error: "Script is required for execute_js action" };
      }
      mcpArgs.code = args.script;
      break;
  }

  try {
    const client = await getClient();

    const result = await Promise.race([
      client.callTool({
        name: mcpAction,
        arguments: mcpArgs,
      }),
      new Promise<never>((_, reject) =>
        setTimeout(() => reject(new Error(`Browser action timed out after ${timeout}ms`)), timeout),
      ),
    ]);

    return {
      action,
      success: true,
      data: typeof result === "string" ? result : JSON.stringify(result),
    };
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err);

    // If the connection died, reset the cache so next call reconnects
    if (msg.includes("Connection closed") || msg.includes("disconnected") || msg.includes("timed out")) {
      cleanupConnection();
    }

    return {
      action,
      success: false,
      error: msg,
    };
  }
}
