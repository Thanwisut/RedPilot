/** Google Gemini provider adapter — uses the Generative Language API with function calling. */

import type { ProviderAdapter, ChatOptions, ToolDefinition } from "../types.js";
import { debugLog } from "../debug.js";

function convertTools(tools: ToolDefinition[] | undefined): unknown[] | undefined {
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

export const googleAdapter: ProviderAdapter = {
  id: "google",
  name: "Google (Gemini)",
  supportsStreaming: true,

  async validate(apiKey: string, _baseUrl?: string) {
    try {
      const url = `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=${apiKey}`;
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          contents: [{ parts: [{ text: "ping" }] }],
          generationConfig: { maxOutputTokens: 1 },
        }),
      });
      return res.ok;
    } catch {
      return false;
    }
  },

  async listModels(apiKey: string, _baseUrl?: string) {
    const url = `https://generativelanguage.googleapis.com/v1beta/models?key=${encodeURIComponent(apiKey)}`;
    debugLog(`[google] Fetching models from ${url}`);
    try {
      const res = await fetch(url);
      debugLog(`[google] HTTP ${res.status}`);
      if (!res.ok) return [];
      const data = (await res.json()) as { models?: Array<{ name: string; displayName?: string }> };
      const models = (data.models ?? []).map((item) => {
        const id = item.name.replace(/^models\//, "");
        return { id, name: item.displayName ?? id };
      }).filter((m) => m.id);
      debugLog(`[google] Mapped ${models.length} models`);
      return models;
    } catch (err) {
      debugLog(`[google] Fetch error: ${err}`);
      return [];
    }
  },

  async *streamChat(options: ChatOptions) {
    const baseUrl = options.baseUrl ?? "https://generativelanguage.googleapis.com";
    const url = `${baseUrl}/v1beta/models/${options.model}:streamGenerateContent?alt=sse&key=${options.apiKey}`;

    const contents = options.messages
      .filter((m) => m.role !== "system")
      .map((m) => ({
        role: m.role === "assistant" ? "model" : "user",
        parts: [{ text: m.content }],
      }));

    const body: Record<string, unknown> = {
      contents,
      generationConfig: {
        temperature: 0.7,
        maxOutputTokens: 4096,
      },
    };

    const tools = convertTools(options.tools);
    if (tools) body.tools = tools;

    debugLog("[google] Request body:", JSON.stringify(body, null, 2));

    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: options.signal,
    });

    if (!res.ok) {
      const text = await res.text().catch(() => "");
      debugLog(`[google] Error ${res.status}: ${text.slice(0, 500)}`);
      yield { type: "error", error: `Gemini API error (${res.status}): ${text.slice(0, 300)}` };
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
          if (!trimmed || !trimmed.startsWith("data: ")) continue;

          const data = trimmed.slice(6);
          try {
            const parsed = JSON.parse(data);

            // Text content
            const text = parsed.candidates?.[0]?.content?.parts?.[0]?.text;
            if (text) {
              yield { type: "text", text };
            }

            // Function call
            const functionCall = parsed.candidates?.[0]?.content?.parts?.[0]?.functionCall;
            if (functionCall?.name) {
              yield {
                type: "tool_call" as const,
                toolCall: {
                  id: `fc_${Date.now()}`,
                  name: functionCall.name,
                  arguments: functionCall.args ?? {},
                },
              };
            }
          } catch {
            // skip parse errors
          }
        }
      }
    } finally {
      reader.releaseLock();
    }

    yield { type: "done" };
  },
};
