/** StreamingOutput — renders token.delta events as live text per agent.
 *
 * Pure display — appends incoming text deltas to a buffer per agent_id.
 */

import { Box, Text } from "./Ink.js";
import { palette } from "../theming/colors.js";

interface StreamingOutputProps {
  /** Text buffer for each agent_id */
  buffers: Record<string, string>;
  /** Which agents to show (empty = show all with content) */
  agentIds?: string[];
  /** Max lines to display per agent */
  maxLines?: number;
}

export function StreamingOutput({
  buffers,
  agentIds,
  maxLines = 10,
}: StreamingOutputProps) {
  const keys = agentIds ?? Object.keys(buffers);
  const visible = keys.filter(
    (id) => (buffers[id]?.length ?? 0) > 0,
  );

  if (visible.length === 0) {
    return (
      <Box flexDirection="column" paddingX={1}>
        <Text color={palette.grayMid}>streaming output idle...</Text>
      </Box>
    );
  }

  return (
    <Box flexDirection="column" paddingX={1}>
      <Text bold color={palette.white}>
        ── Streaming Output ───────────────────────────
      </Text>
      {visible.map((agentId) => {
        const text = buffers[agentId] ?? "";
        const lines = text.split("\n").filter(Boolean);
        const truncated = lines.slice(-maxLines);

        return (
          <Box key={agentId} flexDirection="column" marginTop={1}>
            <Text bold color={palette.amber}>
              {agentId}:
            </Text>
            <Box
              borderStyle="single"
              borderColor={palette.grayDark}
              paddingX={1}
              marginTop={1}
            >
              <Text color={palette.grayLight} wrap="wrap">
                {truncated.join("\n")}
              </Text>
            </Box>
          </Box>
        );
      })}
    </Box>
  );
}
