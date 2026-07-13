/** ExecutionScreen — display-only tool execution view.
 *
 * Mounted when a tool is executing. Shows a running spinner,
 * then auto-dismisses after receiving the result.
 * Does NOT execute the tool itself — that's MainConsole's job.
 */

import { useEffect, useState } from "react";
import { useInput } from "ink";
import { Box, Text } from "../components/Ink.js";
import { palette } from "../theming/colors.js";
import type { ToolCall, ToolDefinition } from "../providers/types.js";
import type { ExecutionResult } from "../services/ExecutionManager.js";

const SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];

interface ExecutionScreenProps {
  toolCall: ToolCall;
  toolDef?: ToolDefinition;
  onDone: (result: ExecutionResult | null) => void;
  /** Result provided by MainConsole after execution. Null while running. */
  result?: ExecutionResult | null;
}

export function ExecutionScreen({ toolCall, toolDef, onDone, result }: ExecutionScreenProps) {
  const [spinnerIdx, setSpinnerIdx] = useState(0);
  const targetStr = String(toolCall.arguments.target ?? "?");

  const phase = result === undefined || result === null ? "running" : result.status === "success" ? "done" : "error";

  // Spinner
  useEffect(() => {
    const interval = setInterval(() => {
      setSpinnerIdx((i) => (i + 1) % SPINNER_FRAMES.length);
    }, 80);
    return () => clearInterval(interval);
  }, []);

  // Auto-dismiss after success, or wait for Enter on error
  useEffect(() => {
    if (phase === "done") {
      const timer = setTimeout(() => onDone(result ?? null), 400);
      return () => clearTimeout(timer);
    }
  }, [phase, result, onDone]);

  // Enter also dismisses (for error or impatient users)
  useInput((_input, key) => {
    if (key.return && (phase === "done" || phase === "error")) {
      onDone(result ?? null);
    }
  });

  return (
    <Box flexDirection="column" paddingX={2} paddingY={1}>
      {/* Tool header */}
      <Box
        flexDirection="column"
        paddingX={1}
        paddingY={1}
        borderStyle="round"
        borderColor={palette.cyan}
      >
        <Box justifyContent="space-between">
          <Text bold color={palette.cyan}>
            {toolDef?.name ?? toolCall.name}
          </Text>
          <Text color={palette.grayMid}>
            {phase === "running" ? SPINNER_FRAMES[spinnerIdx] : phase === "done" ? "\u2713" : "\u2717"}
          </Text>
        </Box>

        <Box marginTop={1}>
          <Text color={palette.amber}>
            Target:{" "}
            <Text color={palette.white} bold>
              {targetStr}
            </Text>
          </Text>
        </Box>

        {phase === "running" && (
          <Box marginTop={1}>
            <Text color={palette.grayLight}>Running...</Text>
          </Box>
        )}

        {phase === "done" && result && (
          <>
            <Box marginTop={1}>
              <Text color={palette.statusCompleted} bold>Completed</Text>
            </Box>
            <Box marginTop={1}>
              <Text color={palette.white}>{result.summary}</Text>
            </Box>
            {result.details && (
              <Box marginTop={1}>
                <Text color={palette.grayLight}>{result.details}</Text>
              </Box>
            )}
            <Box marginTop={1}>
              <Text color={palette.grayMid}>
                Duration: {(result.durationMs / 1000).toFixed(1)}s
              </Text>
            </Box>
          </>
        )}

        {phase === "error" && result && (
          <>
            <Box marginTop={1}>
              <Text color={palette.statusFailed} bold>Failed</Text>
            </Box>
            <Box marginTop={1}>
              <Text color={palette.statusFailed}>{result.summary}</Text>
            </Box>
          </>
        )}
      </Box>
    </Box>
  );
}
