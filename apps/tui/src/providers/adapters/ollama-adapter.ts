/** Ollama provider adapter — uses the Ollama API with tool support. */

import type { ProviderAdapter, ChatOptions, ToolDefinition } from "../types.js";

function convertTools(tools: ToolDefinition[] | undefined): unknown[] | undefined {
  if (!tools || tools.length === 0) return undefined;
  return tools.map((t) => ({
    function: {
      name: t.name,
      description: t.description,
      parameters: t.parameters,
    },
  }));
}

export const ollamaAdapter: ProviderAdapter = {
  id: "ollama",
  name: "Ollama",
  supportsStreaming: true,

  async validate(_apiKey: string, baseUrl?: string) {
    try {
      const url = `${baseUrl ?? "http://localhost:11434"}/api/tags`;
      const res = await fetch(url);
      return res.ok;
    } catch {
      return false;
    }
  },

  async listModels(_apiKey: string, baseUrl?: string) {
    try {
      const url = `${baseUrl ?? "http://localhost:11434"}/api/tags`;
      const res = await fetch(url);
      if (!res.ok) return [];
      const data = (await res.json()) as { models: Array<{ name: string }> };
      return data.models.map((m) => ({ id: m.name, name: m.name }));
    } catch {
      return [];
    }
  },

  async *streamChat(options: ChatOptions) {
    const url = `${options.baseUrl ?? "http://localhost:11434"}/api/chat`;
    const body: Record<string, unknown> = {
      model: options.model,
      messages: options.messages.map((m) => ({
        role: m.role === "system" ? "system" : m.role,
        content: m.content,
      })),
      stream: true,
    };

    const tools = convertTools(options.tools);
    if (tools) body.tools = tools;

    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: options.signal,
    });

    if (!res.ok) {
      const text = await res.text().catch(() => "");
      yield { type: "error", error: `Ollama API error (${res.status}): ${text.slice(0, 300)}` };
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
        if (done) {
          yield { type: "done" };
          return;
        }

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed) continue;

          try {
            const parsed = JSON.parse(trimmed);

            // Text content
            if (parsed.message?.content) {
              yield { type: "text", text: parsed.message.content };
            }

            // Tool calls
            if (parsed.message?.tool_calls) {
              const tc = parsed.message.tool_calls[0];
              if (tc?.function?.name) {
                yield {
                  type: "tool_call" as const,
                  toolCall: {
                    id: `ollama_${Date.now()}`,
                    name: tc.function.name,
                    arguments: tc.function.arguments ?? {},
                  },
                };
              }
            }

            if (parsed.done) {
              yield { type: "done" };
              return;
            }
          } catch {
            // skip parse errors
          }
        }
      }
    } finally {
      reader.releaseLock();
    }
  },
};
