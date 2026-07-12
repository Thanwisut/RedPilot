/** ApprovalPrompt — modal/inline approval prompt for human-in-the-loop.
 *
 * Rendered when an `approval.requested` event arrives. User presses
 * `a` to approve or `d` to deny. The decision is sent back via
 * SessionClient.sendApproval() — no business logic in the TUI.
 */

import { useEffect, useState } from "react";
import { useInput } from "ink";
import { Box, Text } from "./Ink.js";
import { palette } from "../theming/colors.js";
import type { ApprovalRequestedPayload } from "../ws-client/SessionClient.js";

interface ApprovalPromptProps {
  request: ApprovalRequestedPayload | null;
  onResolve: (requestId: string, approved: boolean) => void;
}

type ResolveState = "waiting" | "approved" | "denied";

export function ApprovalPrompt({ request, onResolve }: ApprovalPromptProps) {
  const [state, setState] = useState<ResolveState>("waiting");

  // Reset state when a new request arrives
  useEffect(() => {
    if (request) {
      setState("waiting");
    }
  }, [request]);

  useInput(
    (_input, key) => {
      if (!request || state !== "waiting") return;
      if (key.return) {
        // Enter = approve (default safe action)
        setState("approved");
        onResolve(request.request_id, true);
      }
    },
    { isActive: state === "waiting" && request !== null },
  );

  if (!request) return null;

  const isDone = state !== "waiting";

  return (
    <Box
      flexDirection="column"
      borderStyle="round"
      borderColor={palette.approvalBorder}
      paddingX={2}
      paddingY={1}
      marginTop={1}
    >
      <Text bold color={palette.amber}>
        ⚠  APPROVAL REQUIRED
      </Text>
      <Box marginTop={1} flexDirection="column">
        <Text color={palette.grayLight}>
          Tool: <Text bold>{request.tool_name}</Text>
        </Text>
        <Text color={palette.grayLight}>
          Target: <Text bold>{request.target}</Text>
        </Text>
        <Text color={palette.grayMid} wrap="wrap" marginTop={1}>
          {request.rationale}
        </Text>
        <Text color={palette.redMuted} marginTop={1}>
          {request.requires_approval_reason}
        </Text>
      </Box>

      {isDone ? (
        <Text bold color={palette.statusCompleted} marginTop={1}>
          {state === "approved" ? "✓ APPROVED" : "✗ DENIED"}
        </Text>
      ) : (
        <Box marginTop={1} gap={2}>
          <Text bold color={palette.statusCompleted}>
            [a] Approve
          </Text>
          <Text bold color={palette.statusFailed}>
            [d] Deny
          </Text>
          <Text bold color={palette.grayMid}>
            [Enter] Approve (default)
          </Text>
        </Box>
      )}
    </Box>
  );
}

/** Process key input for approval — call from parent's useInput. */
export function handleApprovalInput(
  input: string,
  request: ApprovalRequestedPayload | null,
  state: "waiting" | "approved" | "denied",
  onResolve: (requestId: string, approved: boolean) => void,
  setState: (s: "waiting" | "approved" | "denied") => void,
): boolean {
  if (!request || state !== "waiting") return false;

  if (input === "a" || input === "A") {
    setState("approved");
    onResolve(request.request_id, true);
    return true;
  }
  if (input === "d" || input === "D") {
    setState("denied");
    onResolve(request.request_id, false);
    return true;
  }
  return false;
}
