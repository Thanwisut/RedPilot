import { describe, it, expect } from "vitest";
import { AVAILABLE_TOOLS, getToolDefinition, formatToolCall } from "../tool-registry.js";

describe("AVAILABLE_TOOLS", () => {
  it("has 11 tools defined (4 original + 7 new)", () => {
    expect(AVAILABLE_TOOLS.length).toBe(11);
  });

  it("has recon_agent", () => {
    const tool = AVAILABLE_TOOLS.find((t) => t.name === "recon_agent");
    expect(tool).toBeDefined();
    expect(tool?.description).toContain("subdomain");
    expect(tool?.parameters.required).toContain("target");
  });

  it("has port_scan_agent", () => {
    const tool = AVAILABLE_TOOLS.find((t) => t.name === "port_scan_agent");
    expect(tool).toBeDefined();
    expect(tool?.description).toContain("ports");
  });

  it("has web_scan_agent", () => {
    const tool = AVAILABLE_TOOLS.find((t) => t.name === "web_scan_agent");
    expect(tool).toBeDefined();
    expect(tool?.description).toContain("vulnerability");
  });

  it("has vulnerability_agent", () => {
    const tool = AVAILABLE_TOOLS.find((t) => t.name === "vulnerability_agent");
    expect(tool).toBeDefined();
    expect(tool?.description).toContain("vulnerability");
  });

  it("each tool has required name, description, and parameters", () => {
    for (const tool of AVAILABLE_TOOLS) {
      expect(tool.name).toBeTruthy();
      expect(tool.description).toBeTruthy();
      expect(tool.parameters.type).toBe("object");
      expect(tool.parameters.required?.length ?? 0).toBeGreaterThan(0);
    }
  });
});

describe("getToolDefinition", () => {
  it("returns the correct tool by name", () => {
    const def = getToolDefinition("recon_agent");
    expect(def).toBeDefined();
    expect(def?.name).toBe("recon_agent");
  });

  it("returns undefined for unknown tool", () => {
    const def = getToolDefinition("nonexistent_tool");
    expect(def).toBeUndefined();
  });
});

describe("formatToolCall", () => {
  it("formats a tool call with known tool", () => {
    const result = formatToolCall({
      id: "call_1",
      name: "recon_agent",
      arguments: { target: "example.com" },
    });
    expect(result).toContain("recon_agent");
    expect(result).toContain("subdomain");
    expect(result).toContain("example.com");
  });

  it("formats a tool call with unknown tool", () => {
    const result = formatToolCall({
      id: "call_2",
      name: "unknown_tool",
      arguments: { target: "test.com" },
    });
    expect(result).toContain("unknown_tool");
    expect(result).toContain("test.com");
  });
});
