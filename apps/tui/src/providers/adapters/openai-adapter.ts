/** OpenAI-compatible provider adapter — covers OpenAI, OpenRouter, and any OpenAI-compatible API. */

import type { ProviderAdapter, ChatOptions, ToolDefinition, StreamChunk } from "../types.js";
import { streamFromFetch } from "../types.js";
import { debugLog } from "../debug.js";

function convertTools(tools: ToolDefinition[] | undefined): unknown[] | undefined {
  if (!tools || tools.length === 0) return undefined;
  return tools.map((t) => ({
    type: "function",
    function: {
      name: t.name,
      description: t.description,
      parameters: t.parameters,
    },
  }));
}

async function* openaiStreamChat(options: ChatOptions, baseUrl: string): AsyncGenerator<StreamChunk> {
  const url = `${baseUrl}/v1/chat/completions`;
  const body: Record<string, unknown> = {
    model: options.model,
    messages: options.messages.map((m) => ({ role: m.role, content: m.content })),
    stream: true,
  };
  const tools = convertTools(options.tools);
  if (tools) body.tools = tools;

  debugLog("[openai] Request body:", JSON.stringify(body, null, 2));

  const res = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${options.apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
    signal: options.signal,
  });

  yield* streamFromFetch(res, (data) => {
    try {
      const parsed = JSON.parse(data);
      const delta = parsed.choices?.[0]?.delta;
      if (delta?.content) {
        return { type: "text" as const, text: delta.content };
      }
      if (delta?.tool_calls) {
        const tc = delta.tool_calls[0];
        if (tc?.function?.name) {
          let args: Record<string, unknown> = {};
          try {
            args = JSON.parse(tc.function.arguments ?? "{}");
          } catch {
            args = {};
          }
          return {
            type: "tool_call" as const,
            toolCall: {
              id: tc.id ?? `call_${Date.now()}`,
              name: tc.function.name,
              arguments: args,
            },
          };
        }
      }
    } catch {
      // skip parse errors
    }
    return null;
  });
}

export const openaiAdapter: ProviderAdapter = {
  id: "openai",
  name: "OpenAI",
  supportsStreaming: true,

  async validate(apiKey: string, baseUrl?: string) {
    const url = `${baseUrl ?? "https://api.openai.com"}/v1/models`;
    try {
      const res = await fetch(url, {
        headers: { Authorization: `Bearer ${apiKey}` },
      });
      return res.ok;
    } catch {
      return false;
    }
  },

  async listModels(apiKey: string, baseUrl?: string) {
    const url = `${baseUrl ?? "https://api.openai.com"}/v1/models`;
    debugLog(`[openai] Fetching models from ${url}`);
    try {
      const res = await fetch(url, {
        headers: { Authorization: `Bearer ${apiKey}` },
      });
      debugLog(`[openai] HTTP ${res.status}`);
      if (!res.ok) return [];
      const data = (await res.json()) as { data: Array<{ id: string }> };
      const models = (data.data ?? []).map((item) => ({
        id: item.id,
        name: item.id,
      })).filter((m) => m.id);
      debugLog(`[openai] Mapped ${models.length} models`);
      return models;
    } catch (err) {
      debugLog(`[openai] Fetch error: ${err}`);
      return [];
    }
  },

  async *streamChat(options: ChatOptions) {
    yield* openaiStreamChat(options, options.baseUrl ?? "https://api.openai.com");
  },
};

export const openrouterAdapter: ProviderAdapter = {
  ...openaiAdapter,
  id: "openrouter",
  name: "OpenRouter",

  async listModels(apiKey: string, baseUrl?: string) {
    const url = `${baseUrl ?? "https://openrouter.ai"}/api/v1/models`;
    debugLog(`[openrouter] Fetching models from ${url}`);
    try {
      const res = await fetch(url, {
        headers: { Authorization: `Bearer ${apiKey}` },
      });
      debugLog(`[openrouter] HTTP ${res.status}`);
      if (!res.ok) return [];
      const data = (await res.json()) as { data: Array<{ id: string; name?: string }> };
      const models = (data.data ?? []).map((item) => ({
        id: item.id,
        name: item.name ?? item.id,
      })).filter((m) => m.id);
      debugLog(`[openrouter] Mapped ${models.length} models`);
      return models;
    } catch (err) {
      debugLog(`[openrouter] Fetch error: ${err}`);
      return [];
    }
  },

  async *streamChat(options: ChatOptions) {
    const baseUrl = options.baseUrl ?? "https://openrouter.ai";
    const url = `${baseUrl}/api/v1/chat/completions`;
    const body: Record<string, unknown> = {
      model: options.model,
      messages: options.messages.map((m) => ({ role: m.role, content: m.content })),
      stream: true,
    };
    const tools = convertTools(options.tools);
    if (tools) body.tools = tools;

    debugLog("[openrouter] Request body:", JSON.stringify(body, null, 2));

    const res = await fetch(url, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${options.apiKey}`,
        "Content-Type": "application/json",
        "HTTP-Referer": "https://redpilot.ai",
        "X-Title": "REDPILOT",
      },
      body: JSON.stringify(body),
      signal: options.signal,
    });

    yield* streamFromFetch(res, (data) => {
      try {
        const parsed = JSON.parse(data);
        const delta = parsed.choices?.[0]?.delta;
        if (delta?.content) {
          return { type: "text" as const, text: delta.content };
        }
        if (delta?.tool_calls) {
          const tc = delta.tool_calls[0];
          if (tc?.function?.name) {
            let args: Record<string, unknown> = {};
            try {
              args = JSON.parse(tc.function.arguments ?? "{}");
            } catch {
              args = {};
            }
            return {
              type: "tool_call" as const,
              toolCall: {
                id: tc.id ?? `call_${Date.now()}`,
                name: tc.function.name,
                arguments: args,
              },
            };
          }
        }
      } catch {
        // skip
      }
      return null;
    });
  },
};
