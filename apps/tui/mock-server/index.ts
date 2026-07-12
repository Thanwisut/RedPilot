/** REDPILOT mock backend — WS + REST server for TUI development.
 *
 * This mock does NOT auto-spawn agents or auto-execute any timeline.
 * It sits idle until the TUI sends a `tool.execute` message, then
 * emits events only for the requested tool.
 *
 * Run: `npx tsx mock-server/index.ts`
 *
 * The real FastAPI backend must implement the same WS event contract.
 */

import { createServer, IncomingMessage, ServerResponse } from "node:http";
import { WebSocketServer, WebSocket } from "ws";

const WS_PORT = 8080;
const sessionId = "mock-session-001";

let configStatus = { configured: false };
let savedConfig: Record<string, unknown> = {};

function buildMsg(type: string, payload: unknown) {
  return JSON.stringify({
    type,
    session_id: sessionId,
    payload,
    ts: new Date().toISOString(),
  });
}

function send(ws: WebSocket, type: string, payload: unknown) {
  if (ws.readyState === WebSocket.OPEN) {
    ws.send(buildMsg(type, payload));
  }
}

// ---------------------------------------------------------------------------
// Per-tool execution timelines
// These run ONLY when the LLM decides to call a tool.
// ---------------------------------------------------------------------------

interface TimelineEvent {
  delay: number;
  type: string;
  payload: unknown;
}

function getReconTimeline(target: string): TimelineEvent[] {
  return [
    {
      delay: 200,
      type: "agent.spawned",
      payload: {
        agent_id: "recon_agent",
        cluster: "recon",
        task_node_id: "NODE-001",
      },
    },
    {
      delay: 100,
      type: "agent.status",
      payload: { agent_id: "recon_agent", status: "Ready" },
    },
    {
      delay: 100,
      type: "agent.status",
      payload: { agent_id: "recon_agent", status: "Dispatched" },
    },
    {
      delay: 150,
      type: "agent.status",
      payload: { agent_id: "recon_agent", status: "Executing" },
    },
    {
      delay: 200,
      type: "tool.invoked",
      payload: {
        agent_id: "recon_agent",
        tool_name: "subfinder",
        target,
        args: { sources: "all", domain: target },
      },
    },
    {
      delay: 2000,
      type: "tool.result",
      payload: {
        agent_id: "recon_agent",
        tool_name: "subfinder",
        status: "success",
        summary: `Found 14 subdomains (7 active): mail, www, api, dev, admin, blog, cdn`,
      },
    },
    {
      delay: 150,
      type: "agent.status",
      payload: { agent_id: "recon_agent", status: "Completed" },
    },
    {
      delay: 100,
      type: "plan.updated",
      payload: {
        task_graph_snapshot: {
          nodes: [
            { id: "NODE-001", agent_id: "recon_agent", status: "Completed", dependencies: [] },
          ],
        },
      },
    },
    {
      delay: 200,
      type: "report.ready",
      payload: { report_path: "/tmp/redpilot/report-recon.md" },
    },
  ];
}

function getPortScanTimeline(target: string): TimelineEvent[] {
  return [
    {
      delay: 200,
      type: "agent.spawned",
      payload: {
        agent_id: "port_scan_agent",
        cluster: "recon",
        task_node_id: "NODE-002",
      },
    },
    {
      delay: 100,
      type: "agent.status",
      payload: { agent_id: "port_scan_agent", status: "Ready" },
    },
    {
      delay: 100,
      type: "agent.status",
      payload: { agent_id: "port_scan_agent", status: "Dispatched" },
    },
    {
      delay: 150,
      type: "agent.status",
      payload: { agent_id: "port_scan_agent", status: "Executing" },
    },
    {
      delay: 200,
      type: "tool.invoked",
      payload: {
        agent_id: "port_scan_agent",
        tool_name: "nmap",
        target,
        args: { ports: "22,80,443,8080", scan_type: "syn", timing_template: "T4" },
      },
    },
    {
      delay: 2500,
      type: "tool.result",
      payload: {
        agent_id: "port_scan_agent",
        tool_name: "nmap",
        status: "success",
        summary: `3 open ports: 22/tcp (SSH), 80/tcp (HTTP), 443/tcp (HTTPS)`,
      },
    },
    {
      delay: 150,
      type: "agent.status",
      payload: { agent_id: "port_scan_agent", status: "Completed" },
    },
    {
      delay: 100,
      type: "plan.updated",
      payload: {
        task_graph_snapshot: {
          nodes: [
            { id: "NODE-002", agent_id: "port_scan_agent", status: "Completed", dependencies: [] },
          ],
        },
      },
    },
    {
      delay: 200,
      type: "report.ready",
      payload: { report_path: "/tmp/redpilot/report-portscan.md" },
    },
  ];
}

function getWebScanTimeline(target: string): TimelineEvent[] {
  return [
    {
      delay: 200,
      type: "agent.spawned",
      payload: {
        agent_id: "web_scan_agent",
        cluster: "recon",
        task_node_id: "NODE-003",
      },
    },
    {
      delay: 100,
      type: "agent.status",
      payload: { agent_id: "web_scan_agent", status: "Ready" },
    },
    {
      delay: 100,
      type: "agent.status",
      payload: { agent_id: "web_scan_agent", status: "Dispatched" },
    },
    {
      delay: 150,
      type: "agent.status",
      payload: { agent_id: "web_scan_agent", status: "Executing" },
    },
    {
      delay: 200,
      type: "tool.invoked",
      payload: {
        agent_id: "web_scan_agent",
        tool_name: "nuclei",
        target,
        args: { templates: "technologies", severity: "medium" },
      },
    },
    {
      delay: 2000,
      type: "tool.result",
      payload: {
        agent_id: "web_scan_agent",
        tool_name: "nuclei",
        status: "success",
        summary: "3 findings: jQuery 3.5.1 (CVE-2020-11022), Express.js fingerprint, missing HSTS",
      },
    },
    {
      delay: 150,
      type: "agent.status",
      payload: { agent_id: "web_scan_agent", status: "Completed" },
    },
    {
      delay: 100,
      type: "plan.updated",
      payload: {
        task_graph_snapshot: {
          nodes: [
            { id: "NODE-003", agent_id: "web_scan_agent", status: "Completed", dependencies: [] },
          ],
        },
      },
    },
    {
      delay: 200,
      type: "report.ready",
      payload: { report_path: "/tmp/redpilot/report-webscan.md" },
    },
  ];
}

function getVulnerabilityTimeline(target: string): TimelineEvent[] {
  return [
    {
      delay: 200,
      type: "agent.spawned",
      payload: {
        agent_id: "vulnerability_agent",
        cluster: "recon",
        task_node_id: "NODE-004",
      },
    },
    {
      delay: 100,
      type: "agent.status",
      payload: { agent_id: "vulnerability_agent", status: "Ready" },
    },
    {
      delay: 100,
      type: "agent.status",
      payload: { agent_id: "vulnerability_agent", status: "Dispatched" },
    },
    {
      delay: 150,
      type: "agent.status",
      payload: { agent_id: "vulnerability_agent", status: "Executing" },
    },
    {
      delay: 200,
      type: "tool.invoked",
      payload: {
        agent_id: "vulnerability_agent",
        tool_name: "nuclei",
        target,
        args: { templates: "cves", severity: "low" },
      },
    },
    {
      delay: 3000,
      type: "tool.result",
      payload: {
        agent_id: "vulnerability_agent",
        tool_name: "nuclei",
        status: "success",
        summary: "2 CVEs found: CVE-2024-1234 (High), CVE-2023-5678 (Medium)",
      },
    },
    {
      delay: 150,
      type: "agent.status",
      payload: { agent_id: "vulnerability_agent", status: "Completed" },
    },
    {
      delay: 100,
      type: "plan.updated",
      payload: {
        task_graph_snapshot: {
          nodes: [
            { id: "NODE-004", agent_id: "vulnerability_agent", status: "Completed", dependencies: [] },
          ],
        },
      },
    },
    {
      delay: 200,
      type: "report.ready",
      payload: { report_path: "/tmp/redpilot/report-vuln.md" },
    },
  ];
}

// ---------------------------------------------------------------------------
// HTTP server + WebSocket
// ---------------------------------------------------------------------------

const server = createServer((req: IncomingMessage, res: ServerResponse) => {
  res.setHeader("Content-Type", "application/json");
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");

  if (req.method === "OPTIONS") {
    res.writeHead(204);
    res.end();
    return;
  }

  const url = new URL(req.url ?? "/", `http://${req.headers.host ?? "localhost"}`);

  if (req.method === "GET" && url.pathname === "/config/status") {
    res.writeHead(200);
    res.end(JSON.stringify(configStatus));
    return;
  }

  if (req.method === "POST" && url.pathname === "/providers/validate") {
    let body = "";
    req.on("data", (chunk: string) => (body += chunk));
    req.on("end", () => {
      const parsed = safeJson(body);
      const apiKey = parsed?.api_key as string | undefined;
      const valid = typeof apiKey === "string" && apiKey.length > 0;
      res.writeHead(200);
      res.end(JSON.stringify({ valid, models: [] }));
    });
    return;
  }

  if (req.method === "GET" && url.pathname === "/config") {
    res.writeHead(200);
    res.end(JSON.stringify(savedConfig));
    return;
  }

  if (req.method === "POST" && url.pathname === "/config/save") {
    let body = "";
    req.on("data", (chunk: string) => (body += chunk));
    req.on("end", () => {
      const parsed = safeJson(body);
      savedConfig = parsed ?? {};
      configStatus = { configured: true };
      res.writeHead(200);
      res.end(JSON.stringify({ configured: true }));
    });
    return;
  }

  if (req.method === "POST" && url.pathname === "/approval/resolve") {
    let body = "";
    req.on("data", (chunk: string) => (body += chunk));
    req.on("end", () => {
      const parsed = safeJson(body);
      const requestId = parsed?.request_id as string | undefined;
      const approved = parsed?.approved === true;
      const msg = buildMsg("approval.resolved", {
        request_id: requestId ?? "REQ-001",
        approved,
      });
      for (const client of wss.clients) {
        if (client.readyState === WebSocket.OPEN) {
          client.send(msg);
        }
      }
      res.writeHead(200);
      res.end(JSON.stringify({ ok: true }));
    });
    return;
  }

  res.writeHead(404);
  res.end(JSON.stringify({ error: "not found" }));
});

const wss = new WebSocketServer({ server });

wss.on("connection", (ws: WebSocket) => {
  console.log("[mock] WS client connected — idle, awaiting tool.execute");

  // Listen for tool.execute messages from the TUI
  ws.on("message", (data: Buffer) => {
    try {
      const msg = JSON.parse(data.toString());
      if (msg.type === "tool.execute" && msg.payload) {
        const toolName = msg.payload.name as string;
        const args = msg.payload.arguments as Record<string, unknown> || {};
        const target = (args.target as string) ?? "unknown";

        console.log(`[mock] tool.execute received: ${toolName} (target: ${target})`);

        // Select the appropriate timeline
        let timeline: TimelineEvent[];
        switch (toolName) {
          case "recon_agent":
            timeline = getReconTimeline(target);
            break;
          case "port_scan_agent":
            timeline = getPortScanTimeline(target);
            break;
          case "web_scan_agent":
            timeline = getWebScanTimeline(target);
            break;
          case "vulnerability_agent":
            timeline = getVulnerabilityTimeline(target);
            break;
          default:
            console.log(`[mock] Unknown tool: ${toolName}`);
            send(ws, "tool.result", {
              agent_id: toolName,
              tool_name: toolName,
              status: "failed",
              summary: `Unknown tool: ${toolName}`,
            });
            return;
        }

        // Play the timeline
        let totalDelay = 0;
        for (const event of timeline) {
          totalDelay += event.delay;
          setTimeout(() => {
            if (ws.readyState === WebSocket.OPEN) {
              send(ws, event.type, event.payload);
            }
          }, totalDelay);
        }
      }
    } catch {
      // Ignore malformed messages
    }
  });

  ws.on("close", () => {
    console.log("[mock] WS client disconnected");
  });
});

server.listen(WS_PORT, () => {
  console.log(`[mock] REDPILOT mock server running on ws://localhost:${WS_PORT}`);
  console.log(`[mock] Does NOT auto-spawn agents. Waits for tool.execute.`);
});

function safeJson(raw: string): Record<string, unknown> | null {
  try {
    return JSON.parse(raw) as Record<string, unknown>;
  } catch {
    return null;
  }
}
