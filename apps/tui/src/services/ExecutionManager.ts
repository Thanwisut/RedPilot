/** ExecutionManager — handles the full tool execution lifecycle.
 *
 * Flow:
 *   1. receive ToolCall from LLM
 *   2. confirm with user (handled by MainConsole UI)
 *   3. execute tool (simulated locally — backend not yet available)
 *   4. return structured result
 *   5. MainConsole passes result back to LLM for continuation
 */

import type { ToolCall } from "../providers/types.js";

export interface ExecutionResult {
  toolCallId: string;
  toolName: string;
  status: "success" | "error";
  summary: string;
  details: string;
  durationMs: number;
}

/**
 * Execute a tool call locally.
 *
 * Since the WebSocket backend doesn't exist yet, this simulates execution.
 * Each tool returns a plausible result based on its name and arguments.
 * When a real backend is available, this will dispatch via WebSocket instead.
 */
export async function executeTool(toolCall: ToolCall): Promise<ExecutionResult> {
  const start = Date.now();

  // Artificial delay to show the execution screen
  await delay(1500);

  const result = simulateToolCall(toolCall);

  return {
    toolCallId: toolCall.id,
    toolName: toolCall.name,
    ...result,
    durationMs: Date.now() - start,
  };
}

function simulateToolCall(tc: ToolCall): { status: "success" | "error"; summary: string; details: string } {
  const target = (tc.arguments.target as string) ?? "unknown";

  switch (tc.name) {
    case "recon_agent":
      return {
        status: "success",
        summary: `Found 12 subdomains for ${target}`,
        details: [
          `Subdomains discovered for ${target}:`,
          "",
          "  - www.${target}",
          "  - api.${target}",
          "  - mail.${target}",
          "  - admin.${target}",
          "  - dev.${target}",
          "  - staging.${target}",
          "  - blog.${target}",
          "  - cdn.${target}",
          "  - docs.${target}",
          "  - support.${target}",
          "  - status.${target}",
          "  - app.${target}",
          "",
          "Technologies detected: Cloudflare CDN, Nginx 1.24, React SPA",
        ].join("\n"),
      };

    case "port_scan_agent": {
      const ports = (tc.arguments.ports as string) ?? "22,80,443";
      return {
        status: "success",
        summary: `Found 3 open ports on ${target}`,
        details: [
          `Port scan results for ${target}:`,
          "",
          "  PORT    STATE  SERVICE",
          "  22/tcp  open   SSH (OpenSSH 9.3)",
          "  80/tcp  open   HTTP (Nginx 1.24)",
          "  443/tcp open  HTTPS (Nginx 1.24)",
          "",
          `Scanned ports: ${ports}`,
        ].join("\n"),
      };
    }

    case "web_scan_agent":
      return {
        status: "success",
        summary: `Found 2 potential vulnerabilities on ${target}`,
        details: [
          `Web scan results for ${target}:`,
          "",
          "  Technology: React SPA, Nginx 1.24",
          "  CMS: None detected",
          "",
          "  Potential issues:",
          "  - Missing Content-Security-Policy header (Medium)",
          "  - Missing X-Frame-Options header (Low)",
          "",
          "  No critical vulnerabilities found.",
        ].join("\n"),
      };

    case "vulnerability_agent":
      return {
        status: "success",
        summary: `Assessment complete for ${target} — 0 critical, 2 medium, 3 low`,
        details: [
          `Vulnerability assessment for ${target}:`,
          "",
          "  Severity  Count",
          "  Critical  0",
          "  High      0",
          "  Medium    2",
          "  Low       3",
          "",
          "  Medium findings:",
          "  - Missing CSP header",
          "  - TLS 1.0 supported",
          "",
          "  Low findings:",
          "  - Missing X-Frame-Options",
          "  - Server version disclosure",
          "  - Cookie missing Secure flag",
        ].join("\n"),
      };

    default:
      return {
        status: "success",
        summary: `Executed ${tc.name} on ${target}`,
        details: `${tc.name} completed with arguments: ${JSON.stringify(tc.arguments, null, 2)}`,
      };
  }
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
