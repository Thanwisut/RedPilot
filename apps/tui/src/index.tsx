/** REDPILOT TUI — entry point.
 *
 * Screen routing:
 *   Startup → check ~/.redpilot/config.json
 *             ├─ configured → MainConsole (terminal-style chat)
 *             └─ not configured → SetupWizard → saves config → MainConsole
 *
 * /logout in MainConsole calls clearConfig() and returns to the SetupWizard.
 *
 * Supports:
 *   --debug          Enable debug log file (.debug/session-<ts>.log)
 *   REDPILOT_WS_URL  env var   Override the WebSocket URL
 */

import { useEffect, useState, useRef, useCallback } from "react";
import { render } from "ink";
import { Text } from "./components/Ink.js";
import { SetupWizard } from "./screens/SetupWizard.js";
import { MainConsole } from "./screens/MainConsole.js";
import { palette } from "./theming/colors.js";
import { getLogger } from "./debug/debug-logger.js";
import { isConfigured, clearConfig } from "./services/config-store.js";

if (process.argv.includes("--debug")) {
  import("./debug/debug-logger.js").then((m) => m.enableDebug());
}

type Screen = "loading" | "wizard" | "console";

function App() {
  const [screen, setScreen] = useState<Screen>("loading");
  const prevScreenRef = useRef<Screen | null>(null);

  useEffect(() => {
    const prev = prevScreenRef.current;
    if (prev !== null && prev !== screen) {
      const logger = getLogger();
      logger.logScreenTransition({ from: prev, to: screen });
      logger.logTerminalDimensions({
        columns: process.stdout.columns ?? 80,
        rows: process.stdout.rows ?? 24,
      });
    }
    prevScreenRef.current = screen;
  }, [screen]);

  // On mount: check if config file exists and is complete
  // Stale/incomplete configs are cleared to force the wizard.
  useEffect(() => {
    try {
      if (isConfigured()) {
        setScreen("console");
      } else {
        // Clear any stale/incomplete config so the wizard always starts fresh
        clearConfig();
        setScreen("wizard");
      }
    } catch {
      setScreen("wizard");
    }
  }, []);

  const goToConsole = useCallback(() => setScreen("console"), []);

  const handleLogout = useCallback(() => {
    clearConfig();
    setScreen("wizard");
  }, []);

  if (screen === "loading") {
    return <Text color={palette.grayMid}>loading...</Text>;
  }

  if (screen === "wizard") {
    return <SetupWizard onComplete={goToConsole} />;
  }

  return (
    <MainConsole
      onLogout={handleLogout}
    />
  );
}

const isDirectEntry =
  process.argv[1]?.endsWith("index.") ||
  process.argv[1]?.endsWith("index.ts") ||
  process.argv[1]?.endsWith("index.tsx");

if (isDirectEntry) {
  render(<App />);
}

export { App };
