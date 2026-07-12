/** REDPILOT red-themed color palette — defined once, imported everywhere.
 *
 * No inline hex/ANSI codes in components. Add new colors here when needed.
 * The palette is deliberately warm/narrow: reds, oranges, grays, white.
 */

export const palette = {
  /** Base red — primary accent, headings, active indicators */
  red: "#ff0033",
  /** Deep red — borders, secondary accents */
  redDark: "#cc0029",
  /** Muted red — dimmed/past elements, inactive states */
  redMuted: "#661a33",
  /** Cyan — tool call info, assistant messages */
  cyan: "#00ccff",
  /** Orange-red — warnings, highlights, gradient midpoint */
  orange: "#ff5500",
  /** Amber — warm accent for loading/processing states */
  amber: "#ff8800",

  /** Bright white — primary text, high emphasis */
  white: "#ffffff",
  /** Light gray — secondary text, descriptions */
  grayLight: "#cccccc",
  /** Medium gray — metadata, muted text */
  grayMid: "#888888",
  /** Dark gray — borders, background accents */
  grayDark: "#444444",
  /** Near-black — primary background */
  black: "#0a0a0a",

  /** Status colors */
  statusPending: "#888888",
  statusReady: "#ff8800",
  statusDispatched: "#ff5500",
  statusExecuting: "#ff0033",
  statusCompleted: "#00cc66",
  statusFailed: "#cc0029",
  statusBlocked: "#661a33",

  /** Approval prompt */
  approvalBg: "#1a0a0a",
  approvalBorder: "#ff5500",
  approvalApprove: "#00cc66",
  approvalDeny: "#cc0029",
} as const;

/** Utility: wrap text in ANSI 24-bit foreground color.
 *  Ink's <Text color="..."> handles this internally for JSX,
 *  this is only needed for raw strings (e.g. ASCII art). */
export function colorize(text: string, hex: string): string {
  const [r, g, b] = [
    Number.parseInt(hex.slice(1, 3), 16),
    Number.parseInt(hex.slice(3, 5), 16),
    Number.parseInt(hex.slice(5, 7), 16),
  ];
  return `\x1b[38;2;${r};${g};${b}m${text}\x1b[0m`;
}

/** Apply multiple color values across lines (for gradient effects). */
export function gradientLines(
  lines: string[],
  colors: string[],
): string {
  return lines
    .map((line, i) => {
      const c = colors[i % colors.length];
      if (!c) return line;
      return colorize(line, c);
    })
    .join("\n");
}
