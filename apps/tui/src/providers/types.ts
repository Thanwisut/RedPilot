/** Provider adapter types — common interface for all LLM providers. */

export interface ChatMessage {
  role: "user" | "assistant" | "system";
  content: string;
}

export interface ToolDefinition {
  name: string;
  description: string;
  parameters: {
    type: "object";
    properties: Record<string, unknown>;
    required?: string[];
  };
}

export interface ToolCall {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
}

export interface StreamChunk {
  type: "text" | "tool_call" | "error" | "done";
  text?: string;
  toolCall?: ToolCall;
  error?: string;
}

export interface ChatOptions {
  messages: ChatMessage[];
  model: string;
  apiKey: string;
  baseUrl?: string;
  signal?: AbortSignal;
  tools?: ToolDefinition[];
}

export interface ProviderAdapter {
  id: string;
  name: string;
  supportsStreaming: boolean;
  validate(apiKey: string, baseUrl?: string): Promise<boolean>;
  listModels(apiKey: string, baseUrl?: string): Promise<{ id: string; name: string }[]>;
  streamChat(options: ChatOptions): AsyncGenerator<StreamChunk>;
}

export async function* streamFromFetch(
  response: Response,
  parser: (line: string) => StreamChunk | null,
): AsyncGenerator<StreamChunk> {
  if (!response.ok) {
    const body = await response.text().catch(() => "");
    yield { type: "error", error: `HTTP ${response.status}: ${response.statusText} — ${body.slice(0, 200)}` };
    return;
  }
  if (!response.body) {
    yield { type: "error", error: "Response has no body" };
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
        if (!trimmed || !trimmed.startsWith("data: ")) continue;

        const data = trimmed.slice(6);
        if (data === "[DONE]") {
          yield { type: "done" };
          return;
        }

        const chunk = parser(data);
        if (chunk) yield chunk;
      }
    }
  } finally {
    reader.releaseLock();
  }
}
