import type { ToolDefinition, ToolCall } from "./types.js";

export const AVAILABLE_TOOLS: ToolDefinition[] = [
  {
    name: "recon_agent",
    description:
      "Performs subdomain discovery and reconnaissance on a target domain. Use when the user asks to scan, recon, enumerate subdomains, or discover assets for a domain.",
    parameters: {
      type: "object",
      properties: {
        target: {
          type: "string",
          description: "The target domain to scan (e.g. example.com)",
        },
      },
      required: ["target"],
    },
  },
  {
    name: "port_scan_agent",
    description:
      "Scans open ports and running services on a target host or IP. Use when the user asks to scan ports, check open ports, or find services.",
    parameters: {
      type: "object",
      properties: {
        target: {
          type: "string",
          description: "The target hostname or IP address",
        },
        ports: {
          type: "string",
          description: "Port range to scan (e.g. 22,80,443 or 1-1000)",
        },
      },
      required: ["target"],
    },
  },
  {
    name: "web_scan_agent",
    description:
      "Performs web application vulnerability scanning and technology fingerprinting on a target URL. Use when the user asks to scan a web app, find vulnerabilities, or identify technologies.",
    parameters: {
      type: "object",
      properties: {
        target: {
          type: "string",
          description: "The target URL to scan (e.g. https://example.com)",
        },
      },
      required: ["target"],
    },
  },
  {
    name: "vulnerability_agent",
    description:
      "Performs comprehensive vulnerability assessment on a target. Use when the user asks to find vulnerabilities, check for CVEs, or assess security posture.",
    parameters: {
      type: "object",
      properties: {
        target: {
          type: "string",
          description: "The target domain, IP, or URL",
        },
      },
      required: ["target"],
    },
  },
];

export function getToolDefinition(name: string): ToolDefinition | undefined {
  return AVAILABLE_TOOLS.find((t) => t.name === name);
}

export function formatToolCall(tc: ToolCall): string {
  const def = getToolDefinition(tc.name);
  const args = Object.entries(tc.arguments)
    .map(([k, v]) => `  ${k}: ${v}`)
    .join("\n");
  return [
    `Tool: ${tc.name}`,
    def ? `  ${def.description}` : "",
    "Arguments:",
    args,
  ]
    .filter(Boolean)
    .join("\n");
}
