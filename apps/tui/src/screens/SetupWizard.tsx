/** SetupWizard — provider selection, API key entry, model table, and save.
 *
 * Fetches model catalogs through the ModelCatalog service, never directly.
 * Every registered provider has a live API fetcher — zero hardcoded models.
 *
 * Flow:
 *   1. Provider select -> key entry -> ModelCatalog.getModels()
 *   2. Render returned model table with FREE badges and capability columns
 *   3. Confirm -> POST /config/save -> transition to MainConsole (idle prompt)
 */

import { useState } from "react";
import { useInput, useStdout } from "ink";
import { Box, Text } from "../components/Ink.js";
import { palette } from "../theming/colors.js";
import { getSplashArt } from "../theming/splash-ascii.js";
import { ModelCatalog } from "../services/ModelCatalog.js";
import type { ModelInfo } from "../services/model-types.js";
import { setConfig } from "../services/config-store.js";
import { ModelTable } from "../components/ModelTable.js";

interface Provider {
  id: string;
  label: string;
  /** Extended info shown in the provider description line */
  description?: string;
}

/**
 * Active providers for this phase.
 * The abstraction supports adding more later (just push to this array),
 * keeping the provider-agnostic architecture intact.
 */
const PROVIDERS: Provider[] = [
  {
    id: "opencode",
    label: "OpenCode",
    description: "opencode.ai — OpenAI-compatible model gateway",
  },
  {
    id: "openrouter",
    label: "OpenRouter",
    description: "openrouter.ai — unified API gateway",
  },
  {
    id: "google",
    label: "Google (Gemini)",
    description: "Google AI Studio — Gemini models",
  },
];

interface SetupWizardProps {
  onComplete: () => void;
}

type WizardStep = "welcome" | "provider" | "key_entry" | "validating" | "model_select" | "confirm" | "saving" | "done";

export function SetupWizard({ onComplete }: SetupWizardProps) {
  const { stdout } = useStdout();
  const columns = stdout.columns ?? 80;
  const logo = getSplashArt(columns);
  const [step, setStep] = useState<WizardStep>("welcome");
  const [selectedProvider, setSelectedProvider] = useState(0);
  const [apiKey, setApiKey] = useState("");
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedFilteredIndex, setSelectedFilteredIndex] = useState(0);
  const [error, setError] = useState<string | null>(null);

  // Compute filtered model list based on search query
  const filteredModels = searchQuery
    ? models.filter((m) => {
        const q = searchQuery.toLowerCase();
        return (
          m.id.toLowerCase().includes(q) ||
          m.name.toLowerCase().includes(q)
        );
      })
    : models;

  // Clamp selected index when filtered list shrinks
  const safeFilteredIndex = Math.min(
    selectedFilteredIndex,
    Math.max(0, filteredModels.length - 1),
  );

  /** Get the actual ModelInfo at the filtered index */
  function selectedModelInfo(): ModelInfo | undefined {
    return filteredModels[safeFilteredIndex];
  }

  useInput((input, key) => {
    setError(null);

    if (step === "welcome") {
      if (key.return) setStep("provider");
      return;
    }

    if (step === "provider") {
      if (key.upArrow) {
        setSelectedProvider((p) => Math.max(0, p - 1));
        return;
      }
      if (key.downArrow) {
        setSelectedProvider((p) => Math.min(PROVIDERS.length - 1, p + 1));
        return;
      }
      if (key.return) setStep("key_entry");
      return;
    }

    if (step === "key_entry") {
      if (key.escape) {
        setStep("provider");
        return;
      }
      if (key.backspace) {
        setApiKey((k) => k.slice(0, -1));
        return;
      }
      if (key.return && apiKey.length > 0) {
        setStep("validating");
        validateProvider(selectedProvider, apiKey);
        return;
      }
      // Typed or pasted printable characters add to the key
      // Accept any length (single chars from typing, multi-char from paste)
      if (input.length > 0 && /^[ -~]+$/.test(input)) {
        setApiKey((k) => k + input);
        return;
      }
      return;
    }

    if (step === "model_select") {
      if (key.escape) {
        // Clear search if active, otherwise go back
        if (searchQuery.length > 0) {
          setSearchQuery("");
          setSelectedFilteredIndex(0);
          return;
        }
        setStep("key_entry");
        return;
      }
      if (key.backspace) {
        if (searchQuery.length > 0) {
          setSearchQuery((q) => q.slice(0, -1));
          setSelectedFilteredIndex(0);
          return;
        }
        return;
      }
      if (key.upArrow) {
        setSelectedFilteredIndex((i) => Math.max(0, i - 1));
        return;
      }
      if (key.downArrow) {
        setSelectedFilteredIndex((i) =>
          Math.min(filteredModels.length - 1, i + 1),
        );
        return;
      }
      if (key.return && filteredModels.length > 0) {
        setStep("confirm");
        return;
      }
      // Printable characters add to search query
      if (input.length > 0 && /^[ -~]+$/.test(input)) {
        setSearchQuery((q) => q + input);
        setSelectedFilteredIndex(0);
        return;
      }
      return;
    }

    if (step === "confirm") {
      if (key.return) {
        setStep("saving");
        saveConfig();
        return;
      }
      if (input === "b" || input === "B") {
        setStep("model_select");
        return;
      }
      return;
    }
  });



  async function validateProvider(providerIdx: number, key: string) {
    const provider = PROVIDERS[providerIdx];
    if (!provider) return;

    try {
      const result = await ModelCatalog.getModels(provider.id, key);

      if (result.error && result.models.length === 0) {
        // No data at all — show the error
        setError(result.error);
        setStep("key_entry");
        return;
      }

      if (result.error && result.models.length > 0) {
        // Got stale cache with a refresh warning — still usable
        setModels(result.models);
        setSearchQuery("");
        setSelectedFilteredIndex(0);
        setStep("model_select");
        setError(result.error); // Show as warning, user can still select
        return;
      }

      // Success
      setModels(result.models);
      setSearchQuery("");
      setSelectedFilteredIndex(0);
      setStep("model_select");
    } catch (err) {
      setError(String(err));
      setStep("key_entry");
    }
  }

  function saveConfig() {
    const provider = PROVIDERS[selectedProvider];
    const model = selectedModelInfo();

    setConfig({
      provider: provider?.id ?? "",
      apiKey,
      model: model?.id,
    });

    onComplete();
  }

  // ---- Render ----

  return (
    <Box flexDirection="column" paddingX={2} paddingY={1}>
      {/* Header — full responsive ASCII logo */}
      <Box flexDirection="column">
        {logo.map((line, i) => (
          <Text key={i} color={palette.red}>
            {line || " "}
          </Text>
        ))}
        <Text bold color={palette.white}>
          WELCOME TO REDPILOT — Setup Wizard
        </Text>
        <Text color={palette.grayMid}>
          Configure your LLM provider to get started.
        </Text>
      </Box>

      {error && (
        <Box marginTop={1}>
          <Text color={palette.statusFailed}>⚠ {error}</Text>
        </Box>
      )}

      {/* Step: Welcome */}
      {step === "welcome" && (
        <Box marginTop={2}>
          <Text color={palette.grayLight}>
            Press [Enter] to begin setup
          </Text>
        </Box>
      )}

      {/* Step: Provider selection */}
      {step === "provider" && (
        <Box flexDirection="column" marginTop={2}>
          <Text bold color={palette.white}>
            Select LLM Provider:
          </Text>
          {PROVIDERS.map((p, i) => (
            <Box key={p.id} marginTop={1} gap={1}>
              <Text color={i === selectedProvider ? palette.amber : palette.grayDark}>
                {i === selectedProvider ? "▸" : " "}
              </Text>
              <Text
                bold
                color={i === selectedProvider ? palette.white : palette.grayMid}
              >
                {p.label}
              </Text>
            </Box>
          ))}
          <Text color={palette.grayMid} marginTop={1}>
            [↑↓] navigate  [Enter] select
          </Text>
        </Box>
      )}

      {/* Step: API key entry */}
      {step === "key_entry" && (
        <Box flexDirection="column" marginTop={2}>
          <Text bold color={palette.white}>
            Enter API Key for {PROVIDERS[selectedProvider]?.label ?? "provider"}:
          </Text>
          <Box marginTop={1}>
            <Text color={palette.amber}>▸ </Text>
            <Text color={palette.grayLight}>
              {"●".repeat(Math.max(0, apiKey.length - 4))}
              {apiKey.slice(-4)}
            </Text>
          </Box>
          <Text color={palette.grayMid} marginTop={1}>
            Type to enter key  [Enter] validate  [Esc] back
          </Text>
        </Box>
      )}

      {/* Step: Validating */}
      {step === "validating" && (
        <Box marginTop={2}>
          <Text color={palette.amber}>⏳ Validating API key...</Text>
        </Box>
      )}

      {/* Step: Model selection */}
      {step === "model_select" && (
        <Box flexDirection="column" marginTop={2}>
          <Text bold color={palette.white}>
            Select Model:
          </Text>

          {/* Search bar */}
          <Box marginTop={1}>
            <Text color={palette.amber}>🔍 </Text>
            <Text color={searchQuery ? palette.white : palette.grayDark}>
              {searchQuery || "type to filter..."}
            </Text>
            <Text color={palette.grayMid}>
              {"  "}({filteredModels.length}/{models.length})
            </Text>
          </Box>

          {/* Model table */}
          <Box marginTop={1}>
            {filteredModels.length === 0 ? (
              <Text color={palette.grayMid}>
                No models match "{searchQuery}"
              </Text>
            ) : (
              <ModelTable
                models={filteredModels}
                selectedIndex={safeFilteredIndex}
              />
            )}
          </Box>
          <Text color={palette.grayMid} marginTop={1}>
            Type to filter  [Esc] clear/back  [↑↓] navigate  [Enter] select
          </Text>
        </Box>
      )}

      {/* Step: Confirm */}
      {step === "confirm" && (
        <Box flexDirection="column" marginTop={2}>
          <Text bold color={palette.statusCompleted}>✓ Configuration summary:</Text>
          <Text color={palette.grayLight} marginTop={1}>
            Provider: {PROVIDERS[selectedProvider]?.label ?? "?"}
          </Text>
          <Text color={palette.grayLight}>
            Model: {selectedModelInfo()?.name ?? "?"}
          </Text>
          <Box marginTop={2} gap={2}>
            <Text bold color={palette.statusCompleted}>
              [Enter] Confirm & start
            </Text>
            <Text bold color={palette.grayMid}>
              [b] Back to model selection
            </Text>
          </Box>
        </Box>
      )}

      {/* Step: Saving */}
      {step === "saving" && (
        <Box marginTop={2}>
          <Text color={palette.amber}>⏳ Saving configuration...</Text>
        </Box>
      )}


    </Box>
  );
}
