/** Provider registry — maps provider IDs to their adapters. */

import type { ProviderAdapter, ChatOptions, StreamChunk, ToolDefinition } from "./types.js";
import { opencodeAdapter } from "./adapters/opencode-adapter.js";
import { openaiAdapter, openrouterAdapter } from "./adapters/openai-adapter.js";
import { anthropicAdapter } from "./adapters/anthropic-adapter.js";
import { googleAdapter } from "./adapters/google-adapter.js";
import { ollamaAdapter } from "./adapters/ollama-adapter.js";

const ADAPTERS: Record<string, ProviderAdapter> = {
  opencode: opencodeAdapter,
  openai: openaiAdapter,
  openrouter: openrouterAdapter,
  anthropic: anthropicAdapter,
  google: googleAdapter,
  ollama: ollamaAdapter,
};

export function getAdapter(providerId: string): ProviderAdapter | undefined {
  return ADAPTERS[providerId];
}

export function getAllAdapters(): ProviderAdapter[] {
  return Object.values(ADAPTERS);
}

export function getProviderNames(): { id: string; name: string }[] {
  return Object.values(ADAPTERS).map((a) => ({ id: a.id, name: a.name }));
}

export interface StreamChatOptions extends ChatOptions {
  provider: string;
}

export async function* streamChat(options: StreamChatOptions): AsyncGenerator<StreamChunk> {
  const adapter = getAdapter(options.provider);
  if (!adapter) {
    yield { type: "error", error: `Unknown provider: ${options.provider}` };
    return;
  }
  yield* adapter.streamChat(options);
}

/** Build a system message that describes available tools for the LLM. */
export function buildToolSystemMessage(tools: ToolDefinition[]): string {
  if (!tools || tools.length === 0) return "";
  const desc = tools
    .map((t) => {
      const params = Object.entries(t.parameters.properties || {})
        .map(([k, v]) => {
          const prop = v as { type?: string; description?: string };
          const required = t.parameters.required?.includes(k) ? " (required)" : "";
          return `    ${k}: ${prop.type ?? "string"} — ${prop.description ?? ""}${required}`;
        })
        .join("\n");
      return `- ${t.name}: ${t.description}\n  Parameters:\n${params}`;
    })
    .join("\n");

  return [
    "You have access to the following tools. When a user asks you to perform an action that matches one of these tools, call the tool by responding with the appropriate function call. Do NOT describe what you would do — actually call the tool.",
    "",
    desc,
    "",
    "IMPORTANT: Only call a tool when the user explicitly asks for something the tool does. If the user asks a general question or has a conversation, respond normally without calling tools.",
  ].join("\n");
}
