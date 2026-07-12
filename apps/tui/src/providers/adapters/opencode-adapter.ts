/** OpenCode/Zen provider adapter — routes to per-family endpoints with tool support.
 *
 * Model discovery:       GET  /zen/v1/models
 * GPT family:            POST /zen/v1/responses       (OpenAI Responses API)
 * Claude / Qwen family:  POST /zen/v1/messages        (Anthropic Messages API)
 * Gemini family:         POST /zen/v1/models/{model}  (Google Generative Language API)
 * Everything else:       POST /zen/v1/chat/completions (OpenAI Chat Completions API)
 */

import type { ProviderAdapter, ChatOptions, ChatMessage, ToolDefinition, StreamChunk } from "../types.js";
import { debugLog } from "../debug.js";

const DEFAULT_BASE = "https://opencode.ai";

// ── Family detection ────────────────────────────────────────────────

type ModelFamily = "gpt" | "claude" | "qwen" | "gemini" | "chat";

function detectFamily(model: string): ModelFamily {
  const m = model.toLowerCase();
  if (m.startsWith("gpt-")) return "gpt";
  if (m.startsWith("claude-")) return "claude";
  if (m.startsWith("qwen")) return "qwen";
  if (m.startsWith("gemini-")) return "gemini";
  return "chat";
}

function endpointFor(family: ModelFamily, model: string, baseUrl: string): string {
  switch (family) {
    case "gpt":
      return `${baseUrl}/zen/v1/responses`;
    case "claude":
    case "qwen":
      return `${baseUrl}/zen/v1/messages`;
    case "gemini":
      return `${baseUrl}/zen/v1/models/${encodeURIComponent(model)}?alt=sse`;
    case "chat":
      return `${baseUrl}/zen/v1/chat/completions`;
  }
}

// ── Tool conversion ─────────────────────────────────────────────────

function convertToolsOpenAI(tools: ToolDefinition[] | undefined): unknown[] | undefined {
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

function convertToolsAnthropic(tools: ToolDefinition[] | undefined): unknown[] | undefined {
  if (!tools || tools.length === 0) return undefined;
  return tools.map((t) => ({
    name: t.name,
    description: t.description,
    input_schema: t.parameters,
  }));
}

function convertToolsGoogle(tools: ToolDefinition[] | undefined): unknown[] | undefined {
  if (!tools || tools.length === 0) return undefined;
  return [
    {
      functionDeclarations: tools.map((t) => ({
        name: t.name,
        description: t.description,
        parameters: t.parameters,
      })),
    },
  ];
}

// ── Request body builders ───────────────────────────────────────────

function buildBody(
  family: ModelFamily,
  model: string,
  messages: ChatMessage[],
  tools: ToolDefinition[] | undefined,
  stream: boolean,
): Record<string, unknown> {
  switch (family) {
    case "gpt":
      return {
        model,
        messages: messages.map(normalizeMessage),
        stream,
        max_tokens: 4096,
        ...(tools ? { tools: convertToolsOpenAI(tools) } : {}),
      };

    case "claude":
    case "qwen": {
      const sysMsg = messages.find((m) => m.role === "system");
      const chatMessages = messages
        .filter((m) => m.role !== "system")
        .map((m) => ({
          role: m.role === "assistant" ? "assistant" : "user",
          content: m.content,
        }));
      const body: Record<string, unknown> = {
        model,
        max_tokens: 4096,
        messages: chatMessages,
        stream,
      };
      if (sysMsg) body.system = sysMsg.content;
      if (tools) body.tools = convertToolsAnthropic(tools);
      return body;
    }

    case "gemini":
      return {
        contents: messages.map((m) => ({
          role: m.role === "assistant" ? "model" : "user",
          parts: [{ text: m.content }],
        })),
        generationConfig: { maxOutputTokens: 4096 },
        ...(tools ? { tools: convertToolsGoogle(tools) } : {}),
      };

    case "chat":
      return {
        model,
        messages: messages.map(normalizeMessage),
        stream,
        ...(tools ? { tools: convertToolsOpenAI(tools) } : {}),
      };
  }
}

// ── SSE parsing ─────────────────────────────────────────────────────

function parseNonStreamingResponse(family: ModelFamily, body: Record<string, unknown>): string {
  switch (family) {
    case "gpt":
    case "chat": {
      const choices = body.choices as Array<Record<string, unknown>> | undefined;
      return choices?.[0]?.message
        ? String((choices[0].message as Record<string, unknown>).content ?? "")
        : "";
    }
    case "claude":
    case "qwen": {
      const content = body.content as Array<Record<string, unknown>> | undefined;
      if (!content) return "";
      return content
        .filter((c) => c.type === "text")
        .map((c) => String(c.text ?? ""))
        .join("");
    }
    case "gemini": {
      const candidates = body.candidates as Array<Record<string, unknown>> | undefined;
      if (!candidates?.[0]) return "";
      const content = candidates[0].content as Record<string, unknown> | undefined;
      const parts = content?.parts as Array<Record<string, unknown>> | undefined;
      if (!parts) return "";
      return parts.map((p) => String(p.text ?? "")).join("");
    }
  }
}

// ── SSE streaming ───────────────────────────────────────────────────

async function* streamSSE(
  response: Response,
  parser: (parsed: Record<string, unknown>) => StreamChunk | null,
): AsyncGenerator<StreamChunk> {
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    yield { type: "error", error: `OpenCode API error (${response.status}): ${body.slice(0, 300)}` };
    return;
  }
  if (!response.body) {
    yield { type: "error", error: "No response body" };
    return;
  }

  const reader = response.body.getReader();
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

        if (trimmed === "data: [DONE]") {
          yield { type: "done" };
          return;
        }

        if (!trimmed.startsWith("data: ")) continue;

        const data = trimmed.slice(6).trim();
        if (!data || data === "[DONE]") {
          yield { type: "done" };
          return;
        }

        try {
          const parsed = JSON.parse(data);
          const chunk = parser(parsed);
          if (chunk) {
            if (chunk.type === "done") return;
            yield chunk;
          }
        } catch {
          // skip unparseable lines
        }
      }
    }
  } finally {
    reader.releaseLock();
  }

  yield { type: "done" };
}

function parseSSEEvent(family: ModelFamily): (parsed: Record<string, unknown>) => StreamChunk | null {
  return (parsed) => {
    switch (family) {
      case "gpt": {
        if (parsed.type === "response.output_text.delta" && typeof parsed.delta === "string") {
          return { type: "text", text: parsed.delta };
        }
        const choices = parsed.choices as Array<Record<string, unknown>> | undefined;
        const delta = (choices?.[0]?.delta ?? {}) as Record<string, unknown>;
        const toolCalls = delta.tool_calls as Array<Record<string, unknown>> | undefined;
        if (toolCalls?.[0]?.function) {
          const tc = toolCalls[0];
          const fn = tc.function as Record<string, unknown> | undefined;
          let args: Record<string, unknown> = {};
          try { args = JSON.parse(String(fn?.arguments ?? "{}")); } catch { /* noop */ }
          return { type: "tool_call", toolCall: { id: String(tc.id ?? `call_${Date.now()}`), name: String(fn?.name ?? ""), arguments: args } };
        }
        return null;
      }

      case "claude":
      case "qwen": {
        if (parsed.type === "content_block_delta") {
          const delta = parsed.delta as Record<string, unknown> | undefined;
          if (delta?.text) return { type: "text", text: String(delta.text) };
        }
        if (parsed.type === "content_block_start") {
          const block = parsed.content_block as Record<string, unknown> | undefined;
          if (block?.type === "tool_use") {
            return { type: "tool_call", toolCall: { id: String(block.id ?? `toolu_${Date.now()}`), name: String(block.name ?? ""), arguments: (block.input ?? {}) as Record<string, unknown> } };
          }
        }
        if (parsed.type === "message_stop") return { type: "done" };
        return null;
      }

      case "gemini": {
        const candidates = parsed.candidates as Array<Record<string, unknown>> | undefined;
        const parts = candidates?.[0]?.content as Record<string, unknown> | undefined;
        const textParts = parts?.parts as Array<Record<string, unknown>> | undefined;
        if (textParts?.[0]?.text) return { type: "text", text: String(textParts[0].text) };
        const functionCall = textParts?.[0]?.functionCall as Record<string, unknown> | undefined;
        if (functionCall?.name) {
          return { type: "tool_call", toolCall: { id: `fc_${Date.now()}`, name: String(functionCall.name), arguments: (functionCall.args ?? {}) as Record<string, unknown> } };
        }
        return null;
      }

      case "chat": {
        const delta = (parsed.choices as Array<Record<string, unknown>> | undefined)?.[0]?.delta as Record<string, unknown> | undefined;
        if (delta?.content) return { type: "text", text: String(delta.content) };
        const toolCalls = delta?.tool_calls as Array<Record<string, unknown>> | undefined;
        if (toolCalls?.[0]?.function) {
          const tc = toolCalls[0];
          const fn = tc.function as Record<string, unknown> | undefined;
          let args: Record<string, unknown> = {};
          try { args = JSON.parse(String(fn?.arguments ?? "{}")); } catch { /* noop */ }
          return { type: "tool_call", toolCall: { id: String(tc.id ?? `call_${Date.now()}`), name: String(fn?.name ?? ""), arguments: args } };
        }
        return null;
      }
    }
  };
}

// ── Adapter ─────────────────────────────────────────────────────────

export const opencodeAdapter: ProviderAdapter = {
  id: "opencode",
  name: "OpenCode",
  supportsStreaming: true,

  async validate(apiKey: string, baseUrl?: string) {
    const url = `${baseUrl ?? DEFAULT_BASE}/zen/v1/chat/completions`;
    try {
      const res = await fetch(url, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${apiKey}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          model: "deepseek-v4-flash-free",
          messages: [{ role: "user", content: "ping" }],
          max_tokens: 1,
        }),
      });
      return res.status !== 401 && res.status !== 403;
    } catch {
      return false;
    }
  },

  async listModels(apiKey: string, baseUrl?: string) {
    const url = `${baseUrl ?? DEFAULT_BASE}/zen/v1/models`;
    debugLog(`[opencode] Fetching models from ${url}`);
    try {
      const res = await fetch(url, {
        headers: apiKey ? { Authorization: `Bearer ${apiKey}` } : undefined,
      });
      debugLog(`[opencode] HTTP ${res.status}`);
      if (!res.ok) return [];
      const data = (await res.json()) as { data?: Array<{ id: string }> };
      const models = (data.data ?? []).map((item) => ({
        id: item.id,
        name: item.id,
      })).filter((m) => m.id);
      debugLog(`[opencode] Mapped ${models.length} models`);
      return models;
    } catch (err) {
      debugLog(`[opencode] Fetch error: ${err}`);
      return [];
    }
  },

  async *streamChat(options: ChatOptions) {
    const baseUrl = options.baseUrl ?? DEFAULT_BASE;
    const family = detectFamily(options.model);
    const endpoint = endpointFor(family, options.model, baseUrl);
    const isGemini = family === "gemini";
    const body = buildBody(family, options.model, options.messages, options.tools, !isGemini);

    debugLog(`[opencode] ${family} → POST ${endpoint}`);
    debugLog("[opencode] Request body:", JSON.stringify(body, null, 2));

    let response: Response;
    try {
      response = await fetch(endpoint, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${options.apiKey}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify(body),
        signal: options.signal,
      });
    } catch (err) {
      debugLog(`[opencode] Network error: ${err}`);
      yield { type: "error", error: `Network error: ${err}` };
      return;
    }

    debugLog(`[opencode] HTTP ${response.status}`);

    if (!response.ok) {
      const rawBody = await response.text().catch(() => "");
      yield { type: "error", error: `OpenCode API error (${response.status}): ${rawBody.slice(0, 300)}` };
      return;
    }

    if (!response.body) {
      yield { type: "error", error: "No response body" };
      return;
    }

    const contentType = response.headers.get("content-type") ?? "";
    const isStreamingContent = contentType.includes("text/event-stream") || contentType.includes("text/plain");

    if (isStreamingContent) {
      const parser = parseSSEEvent(family);
      yield* streamSSE(response, parser);
      return;
    }

    // Non-streaming fallback
    const rawText = await response.text();
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(rawText);
    } catch {
      yield { type: "error", error: "Invalid JSON in response" };
      return;
    }

    const text = parseNonStreamingResponse(family, parsed);
    if (text) yield { type: "text", text };
    yield { type: "done" };
  },
};

function normalizeMessage(msg: ChatMessage): ChatMessage {
  return {
    role: msg.role === "system" ? "system" : msg.role,
    content: msg.content,
  };
}
