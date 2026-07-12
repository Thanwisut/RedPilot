/**
 * SetupWizard.test.tsx — GAP 2: VERIFY PROVIDER CONFIG FLOW END TO END
 *
 * Tests the full wizard flow for all providers:
 *   OpenCode, OpenRouter, Google (Gemini)
 *
 * The mock server is started programmatically on an ephemeral port
 * within the test file (beforeAll / afterAll), and global.fetch is
 * mocked to return canned responses for each provider's real API.
 *
 * Each provider test:
 *   1. Renders SetupWizard
 *   2. Presses Enter at welcome screen
 *   3. Selects provider (arrow keys + Enter)
 *   4. Types API key (including special characters) and submits
 *   5. Asserts model table renders with correct provider-specific models
 *   6. Confirms selection
 *   7. Asserts config was saved
 */

import { describe, it, expect, vi, beforeAll, afterAll, beforeEach } from "vitest";
import { render } from "ink-testing-library";
import { SetupWizard } from "./SetupWizard";
import { startTestServer, type TestServer } from "./setupTestServer";

// ---------------------------------------------------------------------------
// Test server lifecycle
// ---------------------------------------------------------------------------

let testServer: TestServer;

/**
 * Canned OpenRouter API response for tests (subset of real models).
 * Pricing values are STRINGS to match the actual API wire format!
 */
const OPENROUTER_CANNED_RESPONSE = {
  data: [
    { id: "openai/gpt-5.6-luna-pro", name: "OpenAI: GPT-5.6 Luna Pro", context_length: 1_050_000, pricing: { prompt: "0.000001", completion: "0.000006" }, architecture: { modality: "text+image+file->text", tokenizer: "GPT" }, supported_parameters: ["max_tokens", "tools", "reasoning"] },
    { id: "anthropic/claude-sonnet-5", name: "Anthropic: Claude Sonnet 5", context_length: 1_000_000, pricing: { prompt: "0.000002", completion: "0.00001" }, architecture: { modality: "text->text", tokenizer: "Anthropic" }, supported_parameters: ["max_tokens", "tools"] },
    { id: "google/gemini-3.1-flash-lite-image", name: "Google: Gemini 3.1 Flash Lite (image)", context_length: 65_536, pricing: { prompt: "0.00000025", completion: "0.0000015" }, architecture: { modality: "text+image->text", tokenizer: "Gemini" }, supported_parameters: ["max_tokens"] },
    { id: "mistralai/mistral-nemo", name: "Mistral: Mistral Nemo", context_length: 131_072, pricing: { prompt: "0.00000002", completion: "0.00000003" }, architecture: { modality: "text->text", tokenizer: "Mistral" }, supported_parameters: ["max_tokens", "tools"] },
    { id: "openai/gpt-4o-mini", name: "OpenAI: GPT-4o-mini", context_length: 128_000, pricing: { prompt: "0.00000015", completion: "0.0000006" }, architecture: { modality: "text+image->text", tokenizer: "GPT" }, supported_parameters: ["max_tokens", "tools"] },
    { id: "openai/gpt-4o", name: "OpenAI: GPT-4o", context_length: 128_000, pricing: { prompt: "0.0000025", completion: "0.00001" }, architecture: { modality: "text+image->text", tokenizer: "GPT" }, supported_parameters: ["max_tokens", "tools", "reasoning"] },
  ],
};

/** Canned OpenCode API response for tests (real model IDs from the live API) */
const OPENCODE_CANNED_RESPONSE = {
  object: "list",
  data: [
    { id: "claude-sonnet-5", object: "model", created: 1783836552, owned_by: "opencode" },
    { id: "gpt-5.6-luna", object: "model", created: 1783836552, owned_by: "opencode" },
    { id: "deepseek-v4-flash", object: "model", created: 1783836552, owned_by: "opencode" },
  ],
};

/** Canned Google Gemini API response for tests */
const GOOGLE_CANNED_RESPONSE = {
  models: [
    { name: "models/gemini-2.0-flash", displayName: "Gemini 2.0 Flash", inputTokenLimit: 1_000_000, outputTokenLimit: 8192, supportedGenerationMethods: ["generateContent", "countTokens"] },
    { name: "models/gemini-2.0-pro", displayName: "Gemini 2.0 Pro", inputTokenLimit: 2_000_000, outputTokenLimit: 8192, supportedGenerationMethods: ["generateContent", "countTokens"] },
    { name: "models/gemini-2.0-flash-lite", displayName: "Gemini 2.0 Flash Lite", inputTokenLimit: 256_000, outputTokenLimit: 8192, supportedGenerationMethods: ["generateContent"] },
  ],
};



beforeAll(async () => {
  testServer = await startTestServer();
  // Save original fetch before mocking to avoid infinite recursion
  const originalFetch = globalThis.fetch;
  // Mock fetch to return canned responses for live provider APIs
  vi.spyOn(globalThis, "fetch").mockImplementation(
    async (input: string | URL | Request, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : (input as Request).url;

      // Intercept OpenRouter API calls with canned response
      if (url.includes("openrouter.ai/api/v1/models")) {
        return new Response(JSON.stringify(OPENROUTER_CANNED_RESPONSE), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }

      // Intercept OpenCode API calls with canned response
      if (url.includes("opencode.ai/zen/v1/models")) {
        return new Response(JSON.stringify(OPENCODE_CANNED_RESPONSE), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }

      // Intercept Google Gemini API calls with canned response
      if (url.includes("generativelanguage.googleapis.com/v1beta/models")) {
        return new Response(JSON.stringify(GOOGLE_CANNED_RESPONSE), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }

      // Rewrite mock server URLs to use ephemeral port
      const testUrl = url.replace("http://localhost:8080", `http://localhost:${testServer.port}`);
      return originalFetch(testUrl, init);
    },
  );
});

afterAll(async () => {
  vi.restoreAllMocks();
  await testServer.close();
});

// ---------------------------------------------------------------------------
// Helper: interact with the wizard by writing to stdin
// ---------------------------------------------------------------------------

function pressEnter(stdin: { write: (data: string) => void }) {
  stdin.write("\r");
}

function pressDown(stdin: { write: (data: string) => void }) {
  stdin.write("\x1b[B");
}

function typeText(stdin: { write: (data: string) => void }, text: string) {
  for (const char of text) {
    stdin.write(char);
  }
}

/** Wait for React state updates (Ink's reconciler flushes on microtasks) */
function tick(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

/**
 * Wait for lastFrame() to contain a specific substring.
 * Polls every 20ms with a 3s timeout. Necessary for async operations
 * like validateProvider (fetch → model select) and saveConfig.
 */
async function waitForFrame(
  lastFrame: () => string | undefined,
  expected: string,
  timeout = 3000,
): Promise<string> {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const frame = lastFrame() ?? "";
    if (frame.includes(expected)) {
      return frame;
    }
    await new Promise((resolve) => setTimeout(resolve, 20));
  }
  throw new Error(
    `waitForFrame: did not see "${expected}" within ${timeout}ms. Last frame: ${JSON.stringify(lastFrame() ?? "")}`,
  );
}

// ---------------------------------------------------------------------------
// Provider configs to test
// ---------------------------------------------------------------------------

interface ProviderTestCase {
  id: string;
  label: string;
  /** Index in the PROVIDERS array (0-based) */
  providerIndex: number;
  apiKey: string;
  /** Model names expected in the rendered table */
  expectedModelNames: string[];
}

const PROVIDER_TESTS: ProviderTestCase[] = [
  {
    id: "opencode",
    label: "OpenCode",
    providerIndex: 0,
    apiKey: "oc-sk-test-key-abcdef-12345",
    expectedModelNames: ["claude-sonnet-5", "gpt-5.6-luna", "deepseek-v4-flash"],
  },
  {
    id: "openrouter",
    label: "OpenRouter",
    providerIndex: 1,
    apiKey: "or-sk-test-key-with_special_chars-ABC_123",
    expectedModelNames: ["OpenAI: GPT-5.6 Luna Pro", "Anthropic: Claude Sonnet 5", "Mistral: Mistral Nemo", "OpenAI: GPT-4o-mini", "OpenAI: GPT-4o"],
  },
  {
    id: "google",
    label: "Google (Gemini)",
    providerIndex: 2,
    apiKey: "AIzaSyD-test-key-with-dashes_and_underscores_12345",
    expectedModelNames: ["Gemini 2.0 Flash", "Gemini 2.0 Pro", "Gemini 2.0 Flash Lite"],
  },
];

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("GAP 2 — Provider config flow", () => {
  beforeEach(() => {
    // Clear all fetch mock calls between tests
    vi.clearAllMocks();
  });

  for (const provider of PROVIDER_TESTS) {
    describe(`${provider.label} (${provider.id})`, () => {
      it("completes full config flow", async () => {
        const onComplete = vi.fn();
        const { lastFrame, stdin } = render(
          <SetupWizard onComplete={onComplete} />,
        );

        // Let React's useEffect fire (ink's useInput attaches stdin readable listener)
        await tick();

        // ---- Step 1: Welcome screen ----
        let frame = lastFrame();
        expect(frame).toContain("WELCOME TO REDPILOT");
        expect(frame).toContain("Press [Enter] to begin setup");

        // ---- Step 2: Navigate to provider selection ----
        pressEnter(stdin);
        await tick();
        frame = lastFrame();
        expect(frame).toContain("Select LLM Provider");
        expect(frame).toContain("OpenCode");
        expect(frame).toContain("OpenRouter");
        expect(frame).toContain("Google (Gemini)");
        expect(frame).toContain("[↑↓] navigate  [Enter] select");

        // ---- Step 3: Select the right provider ----
        // OpenCode is at index 0 (default), so if providerIndex > 0, press Down
        if (provider.providerIndex > 0) {
          for (let i = 0; i < provider.providerIndex; i++) {
            pressDown(stdin);
            await tick();
          }
        }
        pressEnter(stdin);
        await tick();
        frame = lastFrame();
        expect(frame).toContain("Enter API Key");
        expect(frame).toContain(provider.label);

        // ---- Step 4: Type API key (with special characters) ----
        typeText(stdin, provider.apiKey);
        await tick();
        frame = lastFrame();
        // Verify key was captured (last 4 chars should be visible in the masked display)
        const last4 = provider.apiKey.slice(-4);
        expect(frame).toContain(last4);

        // Submit key — validation is async, so wait for the model table to appear
        pressEnter(stdin);
        frame = await waitForFrame(lastFrame, "Select Model");
        expect(frame).toContain("Model");
        expect(frame).toContain("Context");
        expect(frame).toContain("Input/1k");
        expect(frame).toContain("Output/1k");

        // Assert ALL expected model names are in the rendered output
        for (const modelName of provider.expectedModelNames) {
          expect(frame).toContain(modelName);
        }

        // ---- Step 5: Select default model (first one) ----
        pressEnter(stdin);
        await tick();
        frame = lastFrame();
        expect(frame).toContain("Configuration summary");
        expect(frame).toContain(`Provider: ${provider.label}`);
        expect(frame).toContain(provider.expectedModelNames[0]);

        // ---- Step 6: Confirm — saves config and transitions to console ----
        pressEnter(stdin);
        // saveConfig calls onComplete() synchronously
        await vi.waitFor(() => expect(onComplete).toHaveBeenCalledTimes(1), { timeout: 2000 });
      });
    });
  }
});

// ---------------------------------------------------------------------------
// Special character key-input test
// ---------------------------------------------------------------------------

describe("GAP 2 — Special character key-input handling", () => {
  it("captures API key with special characters correctly", async () => {
    const onComplete = vi.fn();
    const { lastFrame, stdin } = render(
      <SetupWizard onComplete={onComplete} />,
    );

    // Let React's useEffect fire (ink's useInput attaches stdin readable listener)
    await tick();

    // Navigate to key entry for first provider (OpenCode, index 0)
    pressEnter(stdin);
    await tick();
    pressEnter(stdin);
    await tick();

    const complexKey = "sk-ant-v3_test-key-with--dashes__underscores-abc123XYZ";
    typeText(stdin, complexKey);
    await tick();

    const frame = lastFrame();
    // The last 4 chars should be visible in the masked display
    const last4 = complexKey.slice(-4);
    expect(frame).toContain(last4);

    // Submit the key — wait for validation to complete
    pressEnter(stdin);
    await waitForFrame(lastFrame, "Select Model");
    // Key was not truncated — model table rendered
  });
});
