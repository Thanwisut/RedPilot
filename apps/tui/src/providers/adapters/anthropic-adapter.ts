/** Anthropic provider adapter — uses the Messages API with tool support. */

import type { ProviderAdapter, ChatOptions, ToolDefinition } from "../types.js";
import { debugLog } from "../debug.js";

const ANTHROPIC_VERSION = "2023-06-01";

function convertTools(tools: ToolDefinition[] | undefined): unknown[] | undefined {
  if (!tools || tools.length === 0) return undefined;
  return tools.map((t) => ({
    name: t.name,
    description: t.description,
    input_schema: t.parameters,
  }));
}

export const anthropicAdapter: ProviderAdapter = {
  id: "anthropic",
  name: "Anthropic",
  supportsStreaming: true,

  async validate(apiKey: string, _baseUrl?: string) {
    try {
      const res = await fetch("https://api.anthropic.com/v1/messages", {
        method: "POST",
        headers: {
          "x-api-key": apiKey,
          "anthropic-version": ANTHROPIC_VERSION,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          model: "claude-3-haiku-20240307",
          max_tokens: 1,
          messages: [{ role: "user", content: "ping" }],
        }),
      });
      return res.status !== 401 && res.status !== 403;
    } catch {
      return false;
    }
  },

  async listModels(apiKey: string, _baseUrl?: string) {
    const url = "https://api.anthropic.com/v1/models";
    debugLog(`[anthropic] Fetching models from ${url}`);
    try {
      const res = await fetch(url, {
        headers: {
          "x-api-key": apiKey,
          "anthropic-version": ANTHROPIC_VERSION,
        },
      });
      debugLog(`[anthropic] HTTP ${res.status}`);
      if (!res.ok) return [];
      const data = (await res.json()) as { data: Array<{ id: string; display_name?: string }> };
      const models = (data.data ?? []).map((item) => ({
        id: item.id,
        name: item.display_name ?? item.id,
      })).filter((m) => m.id);
      debugLog(`[anthropic] Mapped ${models.length} models`);
      return models;
    } catch (err) {
      debugLog(`[anthropic] Fetch error: ${err}`);
      return [];
    }
  },

  async *streamChat(options: ChatOptions) {
    const url = `${options.baseUrl ?? "https://api.anthropic.com"}/v1/messages`;

    // Separate system message from chat messages (Anthropic uses top-level system)
    const sysMsg = options.messages.find((m) => m.role === "system");
    const chatMessages = options.messages
      .filter((m) => m.role !== "system")
      .map((m) => ({
        role: m.role === "assistant" ? "assistant" : "user",
        content: m.content,
      }));

    const body: Record<string, unknown> = {
      model: options.model,
      max_tokens: 4096,
      messages: chatMessages,
      stream: true,
    };
    if (sysMsg) body.system = sysMsg.content;

    const tools = convertTools(options.tools);
    if (tools) body.tools = tools;

    debugLog("[anthropic] Request body:", JSON.stringify(body, null, 2));

    const res = await fetch(url, {
      method: "POST",
      headers: {
        "x-api-key": options.apiKey,
        "anthropic-version": ANTHROPIC_VERSION,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
      signal: options.signal,
    });

    if (!res.ok) {
      const text = await res.text().catch(() => "");
      debugLog(`[anthropic] Error ${res.status}: ${text.slice(0, 500)}`);
      yield { type: "error", error: `Anthropic API error (${res.status}): ${text.slice(0, 300)}` };
      return;
    }

    if (!res.body) {
      yield { type: "error", error: "No response body" };
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed) continue;

          if (trimmed.startsWith("data: ")) {
            const data = trimmed.slice(6);
            try {
              const parsed = JSON.parse(data);

              // Text delta
              if (parsed.type === "content_block_delta") {
                const delta = parsed.delta;
                if (delta?.text) {
                  yield { type: "text", text: delta.text };
                }
              }

              // Tool use (Anthropic sends tool_use as a content_block_start)
              if (parsed.type === "content_block_start") {
                const block = parsed.content_block;
                if (block?.type === "tool_use") {
                  yield {
                    type: "tool_call" as const,
                    toolCall: {
                      id: block.id ?? `toolu_${Date.now()}`,
                      name: block.name,
                      arguments: block.input ?? {},
                    },
                  };
                }
              }

              if (parsed.type === "message_stop") {
                yield { type: "done" };
                return;
              }

              if (parsed.type === "error") {
                yield { type: "error", error: parsed.error?.message ?? "Anthropic error" };
                return;
              }
            } catch {
              // skip parse errors
            }
          }
        }
      }
    } finally {
      reader.releaseLock();
    }

    yield { type: "done" };
  },
};
