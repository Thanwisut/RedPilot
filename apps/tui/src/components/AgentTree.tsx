/** AgentTree — live list of agents with their current status.
 *
 * Driven entirely by `agent.status` events. No state computation.
 * Status badge colors are drawn from the central palette.
 */

import { Box, Text } from "./Ink.js";
import { palette } from "../theming/colors.js";
import type { AgentStatusPayload } from "../ws-client/SessionClient.js";

interface AgentEntry {
  agentId: string;
  cluster: string;
  status: string;
}

interface AgentTreeProps {
  agents: AgentEntry[];
}

const STATUS_COLORS: Record<string, string> = {
  Pending: palette.statusPending,
  Ready: palette.statusReady,
  Dispatched: palette.statusDispatched,
  Executing: palette.statusExecuting,
  Completed: palette.statusCompleted,
  Failed: palette.statusFailed,
  Blocked: palette.statusBlocked,
};

function statusColor(status: string): string {
  return STATUS_COLORS[status] ?? palette.grayMid;
}

export function AgentTree({ agents }: AgentTreeProps) {
  if (agents.length === 0) {
    return (
      <Box flexDirection="column" paddingX={1}>
        <Text color={palette.grayMid}>awaiting agents...</Text>
      </Box>
    );
  }

  return (
    <Box flexDirection="column" paddingX={1}>
      <Text bold color={palette.white}>
        ── Agents ──────────────────────────────────
      </Text>
      {agents.map((a) => (
        <Box key={a.agentId} gap={1} marginTop={1}>
          {/* Status dot */}
          <Text color={statusColor(a.status)}>●</Text>
          {/* Agent ID */}
          <Text bold color={palette.white}>
            {a.agentId}
          </Text>
          {/* Cluster tag */}
          <Text color={palette.grayMid}>[{a.cluster}]</Text>
          {/* Status badge */}
          <Box
            borderStyle="round"
            borderColor={palette.grayDark}
            paddingX={1}
          >
            <Text color={statusColor(a.status)}>{a.status}</Text>
          </Box>
        </Box>
      ))}
    </Box>
  );
}

/** Reducer: process agent.status events into AgentEntry list. */
export function reduceAgentStatus(
  prev: AgentEntry[],
  payload: AgentStatusPayload & { cluster?: string },
): AgentEntry[] {
  const existing = prev.find((a) => a.agentId === payload.agent_id);
  if (existing) {
    return prev.map((a) =>
      a.agentId === payload.agent_id
        ? { ...a, status: payload.status }
        : a,
    );
  }
  return [
    ...prev,
    {
      agentId: payload.agent_id,
      cluster: payload.cluster ?? "unknown",
      status: payload.status,
    },
  ];
}
