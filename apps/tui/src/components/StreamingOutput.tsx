/** StreamingOutput — renders token.delta events as live text per agent.
 *
 * Pure display — appends incoming text deltas to a buffer per agent_id.
 * Now uses MarkdownText from @assistant-ui/react-ink-markdown for proper
 * markdown rendering (bold, italic, code blocks, lists) instead of raw text.
 *
 * **Streaming behavior:** MarkdownText re-renders the full text on each update.
 * This is fast enough for typical LLM output (microseconds) and avoids
 * the complexity of incremental streaming state. Partial markdown (e.g.
 * unclosed ** at the end of a chunk) renders as plain text until closed.
 */

import { MarkdownText } from "@assistant-ui/react-ink-markdown";
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
        const lines = text.split("\n");
        const truncated = lines.slice(-maxLines).join("\n");

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
              {/* MarkdownText handles bold, italic, code, lists, etc. */}
              <MarkdownText
                text={truncated}
                wrap={true}
                theme="dark"
              />
            </Box>
          </Box>
        );
      })}
    </Box>
  );
}
