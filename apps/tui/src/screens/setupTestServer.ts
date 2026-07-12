/**
 * setupTestServer.ts — start a minimal mock REST server on an ephemeral port
 * for testing SetupWizard integration.
 *
 * The mock mirrors the real REST endpoints:
 *   GET  /config/status       → { configured: boolean }
 *   POST /providers/validate  → { valid, models }
 *   POST /config/save          → { configured: true }
 */

import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { type AddressInfo } from "node:net";

// NOTE: No hardcoded model data. Models are fetched live from each
// provider's real API through the ModelCatalog service.

export interface TestServer {
  server: ReturnType<typeof createServer>;
  port: number;
  close: () => Promise<void>;
}

export interface StartTestServerOptions {
  /** Initial configured state (default false) */
  configured?: boolean;
}

export function startTestServer(options?: StartTestServerOptions): Promise<TestServer> {
  return new Promise((resolve, reject) => {
    let configured = options?.configured ?? false;
    let savedConfig: Record<string, unknown> = {};

    const server = createServer((req: IncomingMessage, res: ServerResponse) => {
      res.setHeader("Content-Type", "application/json");
      res.setHeader("Access-Control-Allow-Origin", "*");

      const url = new URL(req.url ?? "/", `http://${req.headers.host ?? "localhost"}`);

      // GET /config/status
      if (req.method === "GET" && url.pathname === "/config/status") {
        res.writeHead(200);
        res.end(JSON.stringify({ configured }));
        return;
      }

      // GET /config — retrieve saved configuration
      if (req.method === "GET" && url.pathname === "/config") {
        res.writeHead(200);
        res.end(JSON.stringify(savedConfig));
        return;
      }

      // POST /providers/validate — kept for backward compat.
      // ModelCatalog no longer uses this; returns empty models array.
      if (req.method === "POST" && url.pathname === "/providers/validate") {
        let body = "";
        req.on("data", (chunk: string) => (body += chunk));
        req.on("end", () => {
          try {
            const parsed = JSON.parse(body);
            const apiKey = parsed.api_key as string | undefined;
            const valid = typeof apiKey === "string" && apiKey.length > 0;
            // Models are fetched live from provider APIs now
            res.writeHead(200);
            res.end(JSON.stringify({ valid, models: [] }));
          } catch {
            res.writeHead(400);
            res.end(JSON.stringify({ valid: false, models: [] }));
          }
        });
        return;
      }

      // POST /config/save
      if (req.method === "POST" && url.pathname === "/config/save") {
        let body = "";
        req.on("data", (chunk: string) => (body += chunk));
        req.on("end", () => {
          try {
            savedConfig = JSON.parse(body);
          } catch {
            savedConfig = {};
          }
          configured = true;
          res.writeHead(200);
          res.end(JSON.stringify({ configured: true }));
        });
        return;
      }

      res.writeHead(404);
      res.end(JSON.stringify({ error: "not found" }));
    });

    server.listen(0, () => {
      const address = server.address() as AddressInfo;
      resolve({
        server,
        port: address.port,
        close: () =>
          new Promise<void>((resolveClose) => server.close(() => resolveClose())),
      });
    });

    server.on("error", reject);
  });
}
