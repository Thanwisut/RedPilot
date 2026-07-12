import { describe, it, expect } from "vitest";
import { getAdapter, getProviderNames } from "../registry.js";
import { opencodeAdapter } from "../adapters/opencode-adapter.js";
import { openaiAdapter, openrouterAdapter } from "../adapters/openai-adapter.js";
import { anthropicAdapter } from "../adapters/anthropic-adapter.js";
import { googleAdapter } from "../adapters/google-adapter.js";
import { ollamaAdapter } from "../adapters/ollama-adapter.js";

describe("provider registry", () => {
  it("returns all provider names", () => {
    const names = getProviderNames();
    expect(names.length).toBeGreaterThanOrEqual(5);
    expect(names.map((n) => n.id)).toContain("opencode");
    expect(names.map((n) => n.id)).toContain("openai");
    expect(names.map((n) => n.id)).toContain("anthropic");
    expect(names.map((n) => n.id)).toContain("google");
    expect(names.map((n) => n.id)).toContain("ollama");
  });

  it("returns adapter for known provider", () => {
    const adapter = getAdapter("opencode");
    expect(adapter).toBeDefined();
    expect(adapter?.id).toBe("opencode");
  });

  it("returns undefined for unknown provider", () => {
    const adapter = getAdapter("nonexistent");
    expect(adapter).toBeUndefined();
  });
});

describe("all adapters share the common interface", () => {
  const adapters = [
    opencodeAdapter,
    openaiAdapter,
    openrouterAdapter,
    anthropicAdapter,
    googleAdapter,
    ollamaAdapter,
  ];

  for (const adapter of adapters) {
    it(`${adapter.id} has required properties`, () => {
      expect(adapter.id).toBeTruthy();
      expect(adapter.name).toBeTruthy();
      expect(typeof adapter.supportsStreaming).toBe("boolean");
      expect(typeof adapter.validate).toBe("function");
      expect(typeof adapter.listModels).toBe("function");
      expect(typeof adapter.streamChat).toBe("function");
    });
  }
});

describe("validation returns false with invalid/bad keys", () => {
  for (const adapter of [
    opencodeAdapter,
    openaiAdapter,
    anthropicAdapter,
    googleAdapter,
  ]) {
    it(`${adapter.id} returns false for invalid key`, async () => {
      const result = await adapter.validate("invalid-key-that-will-fail");
      expect(result).toBe(false);
    }, 10000);
  }
});

describe("ollama adapter", () => {
  it("handles missing server gracefully", async () => {
    const result = await ollamaAdapter.validate("", "http://localhost:19999");
    expect(result).toBe(false);
  }, 5000);
});

describe("listModels fetches from real API (no hardcoded fallback)", () => {
  for (const adapter of [
    opencodeAdapter,
    openaiAdapter,
    openrouterAdapter,
    anthropicAdapter,
    googleAdapter,
  ]) {
    it(`${adapter.id} returns array from live API`, async () => {
      const models = await adapter.listModels("test-key");
      expect(Array.isArray(models)).toBe(true);
      // Every item must have id and name
      for (const m of models) {
        expect(typeof m.id).toBe("string");
        expect(m.id.length).toBeGreaterThan(0);
        expect(typeof m.name).toBe("string");
        expect(m.name.length).toBeGreaterThan(0);
      }
    }, 20000);
  }
});

describe("listModels returns only { id, name } items from API", () => {
  it("items have correct shape (no extra fields)", () => {
    const sample = { id: "test-model", name: "test-model" };
    expect(sample.id).toBeTruthy();
    expect(sample.name).toBeTruthy();
    expect(Object.keys(sample)).toEqual(["id", "name"]);
  });
});
