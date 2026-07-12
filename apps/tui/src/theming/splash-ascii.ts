/** REDPILOT ASCII wordmark — used by SetupWizard and MainConsole.
 *
 * The full art requires at least 69 columns. Below 70, the NARROW variant
 * (same art) is used.
 *
 * Each character row is a separate string so gradient coloring
 * can be applied per-row if desired.
 */

/** Full-sized art — requires ≥69 cols (max line width = 69 chars) */
export const SPLASH_ART_WIDE: string[] = [
  "   (`-')  (`-')  _ _(`-')    _  (`-')  _                        (`-')      ",
  "<-.(OO )  ( OO).-/( (OO ).-> \\-.(OO ) (_)      <-.        .->   ( OO).->   ",
  ",------,)(,------. \\    .'_  _.'    \\ ,-(`-'),--. )  (`-')----. /    '._   ",
  "|   /`. ' |  .---' '`'-..__)(_...--'' | ( OO)|  (`-')( OO).-.  '|'--...__) ",
  "|  |_.' |(|  '--.  |  |  ' ||  |_.' | |  |  )|  |OO )( _) | |  |`--.  .--' ",
  "|  .   .' |  .--'  |  |  / :|  .___.'(|  |_/(|  '__ | \\|  |)|  |   |  |    ",
  "|  |\\  \\  |  `---. |  '-'  /|  |      |  |'->|     |'  '  '-'  '   |  |    ",
  "`--' '--' `------' `------' `--'      `--'   `-----'    `-----'    `--'    ",
];

/** Narrow art — fits any terminal (same design, no overflow risk) */
export const SPLASH_ART_NARROW: string[] = [
  "   (`-')  (`-')  _ _(`-')    _  (`-')  _                        (`-')      ",
  "<-.(OO )  ( OO).-/( (OO ).-> \\-.(OO ) (_)      <-.        .->   ( OO).->   ",
  ",------,)(,------. \\    .'_  _.'    \\ ,-(`-'),--. )  (`-')----. /    '._   ",
  "|   /`. ' |  .---' '`'-..__)(_...--'' | ( OO)|  (`-')( OO).-.  '|'--...__) ",
  "|  |_.' |(|  '--.  |  |  ' ||  |_.' | |  |  )|  |OO )( _) | |  |`--.  .--' ",
  "|  .   .' |  .--'  |  |  / :|  .___.'(|  |_/(|  '__ | \\|  |)|  |   |  |    ",
  "|  |\\  \\  |  `---. |  '-'  /|  |      |  |'->|     |'  '  '-'  '   |  |    ",
  "`--' '--' `------' `------' `--'      `--'   `-----'    `-----'    `--'    ",
];

/** Select the appropriate art variant based on terminal width.
 * Art is 69 chars wide; at ≥70 cols it has breathing room.
 */
export function getSplashArt(columns: number): string[] {
  return columns >= 70 ? SPLASH_ART_WIDE : SPLASH_ART_NARROW;
}

/** Tagline shown below the wordmark */
export const TAGLINE = "autonomous penetration testing framework";

/** Full-width secondary header lines — fits in ≥60 cols */
export const SECONDARY_WIDE: string[] = [
  "  ╔══════════════════════════════════════════════════════════╗",
  "  ║     task manager  •  tool execution layer  •  sandbox   ║",
  "  ║     agent dispatcher  •  evidence collector  •  audit    ║",
  "  ╚══════════════════════════════════════════════════════════╝",
];

/** Medium-width secondary header lines — fits in ≥44 cols (alongside NARROW art) */
export const SECONDARY_MEDIUM: string[] = [
  "  ╔══════════════════════════════════════╗",
  "  ║  task manager → tool exec → sandbox  ║",
  "  ║  agent dispatch → evidence → audit    ║",
  "  ╚══════════════════════════════════════╝",
];

/** Narrow secondary header lines — fits in any terminal */
export const SECONDARY_NARROW: string[] = [
  "  task mgr  •  tool exec  •  sandbox",
  "  agent dispatch  •  audit",
];

/** Select secondary art based on terminal width. */
export function getSecondaryArt(columns: number): string[] {
  if (columns >= 60) return SECONDARY_WIDE;
  if (columns >= 44) return SECONDARY_MEDIUM;
  return SECONDARY_NARROW;
}

/** Alias for backward-compat */
export const SECONDARY = SECONDARY_WIDE;
