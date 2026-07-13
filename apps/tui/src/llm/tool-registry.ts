import type { ToolDefinition, ToolCall } from "./types.js";

export const AVAILABLE_TOOLS: ToolDefinition[] = [
  // ---- Original agents (mock tools) ----
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

  // ---- New LLM-callable tools ----
  {
    name: "shell_exec",
    description:
      "Execute arbitrary shell commands inside the isolated sandbox. The command must be provided as a list of strings (argv). For shell features like pipes and redirects, use [\"/bin/sh\", \"-c\", \"...\"]. Requires human approval for every invocation.",
    parameters: {
      type: "object",
      properties: {
        command: {
          type: "array",
          description: "The command to execute as a list of strings (e.g. [\"nmap\", \"-sT\", \"target\"])",
          items: { type: "string" },
        },
        description: {
          type: "string",
          description: "Human-readable description of what this command does",
        },
      },
      required: ["command"],
    },
  },
  {
    name: "spawn_sub_agent",
    description:
      "Create a new sub-agent in the engagement task graph. The new node is subject to normal dispatch, retry, and failure handling by the Task Manager. Returns the new node's ID.",
    parameters: {
      type: "object",
      properties: {
        agent_id: {
          type: "string",
          description: "The agent manifest ID for the sub-agent (e.g. subdomain_agent, port_scan_agent)",
        },
        task_description: {
          type: "string",
          description: "Human-readable description of what this sub-agent should do",
        },
        target: {
          type: "string",
          description: "The target host, domain, or URL for the sub-agent",
        },
        depends_on: {
          type: "array",
          description: "Optional list of node IDs this sub-agent depends on",
          items: { type: "string" },
        },
      },
      required: ["agent_id", "task_description", "target"],
    },
  },
  {
    name: "browser",
    description:
      "Browser automation using Playwright. Supports navigate, click, type, scroll, screenshot (read_only), and execute_js, upload_file, download_file (dangerous). All actions are logged.",
    parameters: {
      type: "object",
      properties: {
        action: {
          type: "string",
          enum: ["navigate", "click", "type", "scroll", "screenshot", "execute_js", "upload_file", "download_file"],
          description: "The browser action to perform",
        },
        url: {
          type: "string",
          description: "URL for navigate action, or current page context for other actions",
        },
        selector: {
          type: "string",
          description: "CSS selector for click/type/scroll actions",
        },
        value: {
          type: "string",
          description: "Value for type action (text to type)",
        },
        script: {
          type: "string",
          description: "JavaScript code for execute_js action (requires approval)",
        },
      },
      required: ["action"],
    },
  },
  {
    name: "list_directory",
    description:
      "List files and directories within the engagement scratch directory.",
    parameters: {
      type: "object",
      properties: {
        path: {
          type: "string",
          description: "Relative path within the scratch directory",
        },
        recursive: {
          type: "boolean",
          description: "Whether to list recursively",
        },
      },
      required: ["path"],
    },
  },
  {
    name: "read_file",
    description:
      "Read file contents from the engagement scratch directory.",
    parameters: {
      type: "object",
      properties: {
        path: {
          type: "string",
          description: "Relative path within the scratch directory",
        },
      },
      required: ["path"],
    },
  },
  {
    name: "write_file",
    description:
      "Write content to a file within the engagement scratch directory. Requires human approval.",
    parameters: {
      type: "object",
      properties: {
        path: {
          type: "string",
          description: "Relative path within the scratch directory",
        },
        content: {
          type: "string",
          description: "Content to write to the file",
        },
      },
      required: ["path", "content"],
    },
  },
  {
    name: "edit_file",
    description:
      "Edit a file by replacing the first occurrence of old_string with new_string. Requires human approval.",
    parameters: {
      type: "object",
      properties: {
        path: {
          type: "string",
          description: "Relative path within the scratch directory",
        },
        old_string: {
          type: "string",
          description: "The string to replace",
        },
        new_string: {
          type: "string",
          description: "The replacement string",
        },
      },
      required: ["path", "old_string", "new_string"],
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
