/** ModelTable — shared model list renderer.
 *
 * Used by SetupWizard (with selection + search) and MainConsole /models
 * (read-only overlay). Both screens render the same header and row format
 * — this eliminates the duplication flagged by the requirement to
 * "reuse the existing model table component already used by the wizard."
 */

import { Box, Text } from "./Ink.js";
import { palette } from "../theming/colors.js";
import type { ModelInfo } from "../services/model-types.js";

export const CAP_LABELS: Record<string, string> = {
  vision: "👁",
  function_calling: "⚙",
  thinking: "🧠",
  streaming: "▶",
  tool_use: "🔧",
};

interface ModelTableProps {
  models: ModelInfo[];
  /** Optional: index of the selected row (for interactive mode). Renders ▸  */
  selectedIndex?: number;
  /** Optional: called for each row to override the default column rendering */
  renderSuffix?: (m: ModelInfo) => React.ReactNode;
}

export function ModelTable({
  models,
  selectedIndex,
  renderSuffix,
}: ModelTableProps) {
  return (
    <Box flexDirection="column">
      {/* Header row */}
      <Box gap={2}>
        <Text bold color={palette.grayMid} minWidth={22}>
          Model
        </Text>
        <Text bold color={palette.grayMid} minWidth={8}>
          Context
        </Text>
        <Text bold color={palette.grayMid} minWidth={8}>
          Input/1k
        </Text>
        <Text bold color={palette.grayMid} minWidth={8}>
          Output/1k
        </Text>
        <Text bold color={palette.grayMid}>
          Caps
        </Text>
      </Box>

      {/* Data rows */}
      {models.map((m, i) => (
        <Box key={m.id} gap={2} marginTop={1}>
          <Text
            color={
              selectedIndex !== undefined && i === selectedIndex
                ? palette.amber
                : palette.grayLight
            }
            bold={selectedIndex !== undefined && i === selectedIndex}
            minWidth={22}
            wrap="truncate-end"
          >
            {selectedIndex !== undefined
              ? i === selectedIndex
                ? "▸ "
                : "  "
              : ""}
            {m.name}
            {m.free ? (
              <Text color={palette.statusCompleted}> FREE</Text>
            ) : null}
          </Text>
          <Text color={palette.grayMid} minWidth={8}>
            {m.context_window >= 1000
              ? `${(m.context_window / 1000).toFixed(0)}k`
              : String(m.context_window)}
          </Text>
          <Text color={palette.grayMid} minWidth={8}>
            ${m.cost_per_1k_input.toFixed(4)}
          </Text>
          <Text color={palette.grayMid} minWidth={8}>
            ${m.cost_per_1k_output.toFixed(4)}
          </Text>
          <Text color={palette.grayLight}>
            {m.capabilities
              .map((c) => CAP_LABELS[c] ?? c.slice(0, 2))
              .join(" ")}
          </Text>
          {renderSuffix?.(m)}
        </Box>
      ))}
    </Box>
  );
}
