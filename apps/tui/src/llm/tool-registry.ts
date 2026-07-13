import type { ToolDefinition, ToolCall } from "./types.js";

export const AVAILABLE_TOOLS: ToolDefinition[] = [
  // ---- Original agents (mock tools) ----
  {
    name: "recon_agent",
    description:
      "Performs subdomain discovery and reconnaissance on a target domain. CRITICAL: You MUST provide the 'target' argument or the tool WILL FAIL. Use when the user asks to scan, recon, enumerate subdomains, or discover assets for a domain. Example: recon_agent({\"target\": \"example.com\"}).",
    parameters: {
      type: "object",
      properties: {
        target: {
          type: "string",
          description:
            "REQUIRED — The target domain to scan (e.g. \"example.com\"). THIS IS MANDATORY — calling recon_agent without target fails.",
        },
      },
      required: ["target"],
    },
  },
  {
    name: "port_scan_agent",
    description:
      "Scans open ports and running services on a target host or IP. CRITICAL: You MUST provide the 'target' argument or the tool WILL FAIL. Use when the user asks to scan ports, check open ports, or find services. Example: port_scan_agent({\"target\": \"example.com\"}) or port_scan_agent({\"target\": \"192.168.1.1\", \"ports\": \"22,80,443\"}).",
    parameters: {
      type: "object",
      properties: {
        target: {
          type: "string",
          description:
            "REQUIRED — The target hostname or IP address (e.g. \"example.com\", \"192.168.1.1\"). THIS IS MANDATORY.",
        },
        ports: {
          type: "string",
          description:
            "Optional — Port range to scan (e.g. \"22,80,443\" or \"1-1000\"). If omitted, scans common ports.",
        },
      },
      required: ["target"],
    },
  },
  {
    name: "web_scan_agent",
    description:
      "Performs web application vulnerability scanning and technology fingerprinting on a target URL. CRITICAL: You MUST provide the 'target' argument or the tool WILL FAIL. Example: web_scan_agent({\"target\": \"https://example.com\"}).",
    parameters: {
      type: "object",
      properties: {
        target: {
          type: "string",
          description:
            "REQUIRED — The target URL to scan (e.g. \"https://example.com\"). THIS IS MANDATORY.",
        },
      },
      required: ["target"],
    },
  },
  {
    name: "vulnerability_agent",
    description:
      "Performs comprehensive vulnerability assessment on a target. CRITICAL: You MUST provide the 'target' argument or the tool WILL FAIL. Use when the user asks to find vulnerabilities, check for CVEs, or assess security posture. Example: vulnerability_agent({\"target\": \"example.com\"}).",
    parameters: {
      type: "object",
      properties: {
        target: {
          type: "string",
          description:
            "REQUIRED — The target domain, IP, or URL (e.g. \"example.com\", \"192.168.1.1\"). THIS IS MANDATORY.",
        },
      },
      required: ["target"],
    },
  },

  // ---- New LLM-callable tools ----
  {
    name: "shell_exec",
    description:
      "Execute arbitrary shell commands inside the isolated sandbox. CRITICAL: You MUST provide the 'command' argument (a non-empty array of strings) or the tool WILL FAIL. For shell features like pipes and redirects, use [\"/bin/sh\", \"-c\", \"your command here\"]. Requires human approval for every invocation. Example: {\"command\": [\"ls\", \"-la\"]} or {\"command\": [\"/bin/sh\", \"-c\", \"echo hello && pwd\"]}.",
    parameters: {
      type: "object",
      properties: {
        command: {
          type: "array",
          description:
            "REQUIRED — The command to execute as a LIST OF STRINGS (e.g. [\"ls\", \"-la\"], [\"cat\", \"file.txt\"], [\"/bin/sh\", \"-c\", \"echo hello\"]). THIS IS MANDATORY — calling shell_exec without command fails.",
          items: { type: "string" },
        },
        description: {
          type: "string",
          description: "Optional: human-readable description of what this command does (not needed for simple commands)",
        },
      },
      required: ["command"],
    },
  },
  {
    name: "spawn_sub_agent",
    description:
      "Create a new sub-agent in the engagement task graph. CRITICAL: You MUST provide all three required arguments (agent_id, task_description, target) or the tool WILL FAIL. Example: spawn_sub_agent({\"agent_id\": \"subdomain_agent\", \"task_description\": \"Scan for subdomains\", \"target\": \"example.com\"}).",
    parameters: {
      type: "object",
      properties: {
        agent_id: {
          type: "string",
          description:
            "REQUIRED — The agent manifest ID (e.g. \"subdomain_agent\", \"port_scan_agent\"). THIS IS MANDATORY.",
        },
        task_description: {
          type: "string",
          description:
            "REQUIRED — Human-readable description of what this sub-agent should do. THIS IS MANDATORY.",
        },
        target: {
          type: "string",
          description:
            "REQUIRED — The target host, domain, or URL for the sub-agent. THIS IS MANDATORY.",
        },
        depends_on: {
          type: "array",
          description:
            "Optional — List of node IDs this sub-agent depends on (e.g. [\"NODE-ABC123\"]). Omit if no dependencies.",
          items: { type: "string" },
        },
      },
      required: ["agent_id", "task_description", "target"],
    },
  },
  {
    name: "browser",
    description:
      "Browser automation using Playwright (Chromium, non-headless).\n\nCRITICAL RULES:\n1. You MUST provide an 'action' argument — calling browser() without action WILL FAIL.\n2. For 'navigate' action, you MUST also provide a 'url'.\n3. For 'click', 'type', 'scroll' actions, you MUST provide a 'selector'.\n4. For 'type', you MUST also provide a 'value' (the text to type).\n5. For 'screenshot', no additional args needed (captures current page).\n6. For 'execute_js', you MUST provide a 'script'.\n\nExamples of CORRECT usage:\n- browser({\"action\": \"navigate\", \"url\": \"https://example.com\"})\n- browser({\"action\": \"click\", \"selector\": \"#submit-btn\"})\n- browser({\"action\": \"type\", \"selector\": \"#search\", \"value\": \"cybersecurity news\"})\n- browser({\"action\": \"screenshot\"})\n\nWRONG (WILL FAIL): browser({})",
    parameters: {
      type: "object",
      properties: {
        action: {
          type: "string",
          enum: ["navigate", "click", "type", "screenshot", "execute_js"],
          description:
            "REQUIRED — The browser action to perform. Valid values: navigate (browse to url), click (click a target element), type (type text into a target element), screenshot (capture the page), execute_js (run JavaScript on the page).",
        },
        url: {
          type: "string",
          description:
            "REQUIRED for 'navigate' action — the full URL to navigate to (e.g. https://google.com). Optional for other actions (sets the page context).",
        },
        selector: {
          type: "string",
          description:
            "REQUIRED for 'click' and 'type' actions — an accessibility target or CSS selector identifying the element (e.g. '#search', 'button.submit', 'text=Hello'). Mapped to the 'target' parameter of the underlying MCP tool.",
        },
        value: {
          type: "string",
          description:
            "REQUIRED for 'type' action — the text to type into the target element (e.g. 'hello world').",
        },
        script: {
          type: "string",
          description:
            "REQUIRED for 'execute_js' action — JavaScript function body or code to run in the browser context (e.g. '() => document.title', '() => navigator.userAgent'). Must be a valid JavaScript function expression.",
        },
      },
      required: ["action"],
    },
  },
  {
    name: "list_directory",
    description:
      "List files and directories within the engagement scratch directory. You MUST provide a 'path' argument (use '.' for current directory).",
    parameters: {
      type: "object",
      properties: {
        path: {
          type: "string",
          description: "REQUIRED — Relative path within the scratch directory. Use '.' to list the current directory.",
        },
        recursive: {
          type: "boolean",
          description: "Whether to list recursively (default: false)",
        },
      },
      required: ["path"],
    },
  },
  {
    name: "read_file",
    description:
      "Read file contents from the engagement scratch directory. CRITICAL: You MUST provide the 'path' argument or the tool WILL FAIL. Example: read_file({\"path\": \"notes.txt\"}).",
    parameters: {
      type: "object",
      properties: {
        path: {
          type: "string",
          description:
            "REQUIRED — Relative path within the scratch directory (e.g. \"notes.txt\", \"output/scan.txt\"). THIS IS MANDATORY.",
        },
      },
      required: ["path"],
    },
  },
  {
    name: "write_file",
    description:
      "Write content to a file within the engagement scratch directory. CRITICAL: You MUST provide both 'path' AND 'content' arguments or the tool WILL FAIL. Requires human approval. Example: write_file({\"path\": \"results.txt\", \"content\": \"Scan complete. Found 3 open ports.\"}).",
    parameters: {
      type: "object",
      properties: {
        path: {
          type: "string",
          description:
            "REQUIRED — Relative path within the scratch directory (e.g. \"results.txt\"). THIS IS MANDATORY.",
        },
        content: {
          type: "string",
          description:
            "REQUIRED — Content to write to the file. THIS IS MANDATORY — calling write_file without content fails.",
        },
      },
      required: ["path", "content"],
    },
  },
  {
    name: "edit_file",
    description:
      "Edit a file by replacing the first occurrence of old_string with new_string. CRITICAL: You MUST provide all three arguments (path, old_string, new_string) or the tool WILL FAIL. Requires human approval. Example: edit_file({\"path\": \"config.txt\", \"old_string\": \"port=80\", \"new_string\": \"port=443\"}).",
    parameters: {
      type: "object",
      properties: {
        path: {
          type: "string",
          description:
            "REQUIRED — Relative path within the scratch directory. THIS IS MANDATORY.",
        },
        old_string: {
          type: "string",
          description:
            "REQUIRED — The exact string to replace (first occurrence only). THIS IS MANDATORY.",
        },
        new_string: {
          type: "string",
          description:
            "REQUIRED — The replacement string. THIS IS MANDATORY.",
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
