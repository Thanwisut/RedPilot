/** ToolActivityLog — scrollable log rendering tool.invoked and tool.result events.
 *
 * Pure display — stores events in a ring buffer and renders them chronologically.
 * No business logic (no retry counting, no status transitions).
 */

import { Box, Text } from "./Ink.js";
import { palette } from "../theming/colors.js";

export interface ToolLogEntry {
  type: "invoked" | "result";
  agentId: string;
  toolName: string;
  target?: string;
  status?: string;
  summary?: string;
  ts: string;
}

interface ToolActivityLogProps {
  entries: ToolLogEntry[];
  maxVisible?: number;
}

export function ToolActivityLog({
  entries,
  maxVisible = 12,
}: ToolActivityLogProps) {
  if (entries.length === 0) {
    return (
      <Box flexDirection="column" paddingX={1}>
        <Text color={palette.grayMid}>tool activity log idle...</Text>
      </Box>
    );
  }

  const visible = entries.slice(-maxVisible);

  return (
    <Box flexDirection="column" paddingX={1}>
      <Text bold color={palette.white}>
        ── Tool Activity Log ──────────────────────────
      </Text>
      {visible.map((entry, i) => (
        <Box key={`${entry.ts}-${i}`} marginTop={1} gap={1}>
          {/* Icon */}
          <Text
            color={
              entry.type === "invoked"
                ? palette.amber
                : entry.status === "success"
                  ? palette.statusCompleted
                  : palette.statusFailed
            }
          >
            {entry.type === "invoked" ? "→" : "✓"}
          </Text>
          {/* Agent */}
          <Text color={palette.grayLight} bold>
            {entry.agentId}
          </Text>
          {/* Tool name */}
          <Text color={palette.white}>{entry.toolName}</Text>
          {/* Target or summary */}
          {entry.type === "invoked" && entry.target && (
            <Text color={palette.grayMid} wrap="truncate-end">
              {entry.target}
            </Text>
          )}
          {entry.type === "result" && entry.summary && (
            <Text color={palette.grayLight} wrap="truncate-end">
              {entry.summary}
            </Text>
          )}
        </Box>
      ))}
    </Box>
  );
}
