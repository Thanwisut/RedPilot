/** ExecutionScreen — minimal tool execution view.
 *
 * Mounted when the user confirms a tool call.
 * Shows progress during execution, then result summary.
 * Calls onDone(result) when finished.
 */

import { useEffect, useState, useRef } from "react";
import { useInput } from "ink";
import { Box, Text } from "../components/Ink.js";
import { palette } from "../theming/colors.js";
import { executeTool } from "../services/ExecutionManager.js";
import type { ToolCall, ToolDefinition } from "../providers/types.js";
import type { ExecutionResult } from "../services/ExecutionManager.js";

const SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];

interface ExecutionScreenProps {
  toolCall: ToolCall;
  toolDef?: ToolDefinition;
  onDone: (result: ExecutionResult | null) => void;
}

export function ExecutionScreen({ toolCall, toolDef, onDone }: ExecutionScreenProps) {
  const [phase, setPhase] = useState<"running" | "done" | "error">("running");
  const [result, setResult] = useState<ExecutionResult | null>(null);
  const [spinnerIdx, setSpinnerIdx] = useState(0);
  const executedRef = useRef(false);
  const targetStr = String(toolCall.arguments.target ?? toolCall.arguments.target ?? "?");

  // Spinner
  useEffect(() => {
    const interval = setInterval(() => {
      setSpinnerIdx((i) => (i + 1) % SPINNER_FRAMES.length);
    }, 80);
    return () => clearInterval(interval);
  }, []);

  // Execute tool on mount
  useEffect(() => {
    if (executedRef.current) return;
    executedRef.current = true;

    executeTool(toolCall).then((res) => {
      setResult(res);
      setPhase(res.status === "success" ? "done" : "error");
    });
  }, [toolCall]);

  // Enter dismisses done screen
  useInput((_input, key) => {
    if (key.return && (phase === "done" || phase === "error")) {
      onDone(result);
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
                Duration: {(result.durationMs / 1000).toFixed(1)}s  [Enter] continue
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
            <Box marginTop={1}>
              <Text color={palette.grayMid}>[Enter] continue</Text>
            </Box>
          </>
        )}
      </Box>
    </Box>
  );
}
