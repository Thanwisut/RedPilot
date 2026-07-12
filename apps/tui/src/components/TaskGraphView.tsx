/** TaskGraphView — kanban-style view of task node states.
 *
 * Driven by `plan.updated` events. Renders nodes grouped by status column.
 * No business logic — purely presentational.
 */

import { Box, Text } from "./Ink.js";
import { palette } from "../theming/colors.js";
import type { PlanUpdatedPayload } from "../ws-client/SessionClient.js";

interface TaskGraphViewProps {
  snapshot: PlanUpdatedPayload["task_graph_snapshot"] | null;
}

const COLUMNS = [
  "Pending",
  "Ready",
  "Executing",
  "Completed",
  "Failed",
  "Blocked",
] as const;

const COLUMN_COLORS: Record<string, string> = {
  Pending: palette.grayDark,
  Ready: palette.amber,
  Executing: palette.red,
  Completed: palette.statusCompleted,
  Failed: palette.redDark,
  Blocked: palette.redMuted,
};

export function TaskGraphView({ snapshot }: TaskGraphViewProps) {
  if (!snapshot || snapshot.nodes.length === 0) {
    return (
      <Box flexDirection="column" paddingX={1}>
        <Text color={palette.grayMid}>awaiting plan...</Text>
      </Box>
    );
  }

  return (
    <Box flexDirection="column" paddingX={1}>
      <Text bold color={palette.white}>
        ── Task Graph ────────────────────────────────
      </Text>
      <Box gap={2} marginTop={1}>
        {COLUMNS.map((col) => {
          const nodes = snapshot.nodes.filter((n) => n.status === col);
          if (nodes.length === 0) return null;
          return (
            <Box key={col} flexDirection="column" minWidth={14}>
              <Text bold color={COLUMN_COLORS[col] ?? palette.grayMid}>
                {col} ({nodes.length})
              </Text>
              {nodes.map((n) => (
                <Box key={n.id} marginTop={1} flexDirection="column">
                  <Text color={palette.white}>{n.id}</Text>
                  <Text color={palette.grayMid} wrap="truncate-end">
                    {n.agent_id}
                  </Text>
                  {n.dependencies.length > 0 && (
                    <Text color={palette.grayDark}>
                      deps: {n.dependencies.join(",")}
                    </Text>
                  )}
                </Box>
              ))}
            </Box>
          );
        })}
      </Box>
    </Box>
  );
}
