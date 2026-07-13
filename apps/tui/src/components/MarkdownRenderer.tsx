/** MarkdownRenderer — lightweight markdown parser for Ink terminal rendering.
 *
 * Parses markdown text into styled Ink components. Handles bold, italic,
 * code, code blocks, headings, and lists.
 *
 * **Streaming behavior:** The component re-renders on each text update.
 * Partial/unclosed markdown tokens at the end of the text are rendered
 * as plain text — no crashes or garbled output.
 */

import { Fragment } from "react";
import { Box, Text } from "./Ink.js";

interface MarkdownRendererProps {
  text: string;
}

interface MarkdownSegment {
  type: "text" | "bold" | "italic" | "code" | "code_block" | "heading" | "list_item";
  content: string;
  language?: string;
}

/**
 * Parse markdown text into an array of segments with type annotations.
 *
 * Handles:
 *   **bold**       — double asterisks
 *   *italic*       — single asterisks
 *   `code`         — backtick inline code
 *   ```code block``` — fenced code blocks
 *   # Heading      — hash headings (level 1-3)
 *   - List item    — dash list items
 *
 * Partial/unclosed tokens at the end are rendered as plain text.
 */
function parseMarkdown(text: string): MarkdownSegment[] {
  const segments: MarkdownSegment[] = [];
  let remaining = text;

  while (remaining.length > 0) {
    // Code block ```...```
    const codeBlockMatch = remaining.match(/^```(\w*)\n?([\s\S]*?)```/);
    if (codeBlockMatch) {
      segments.push({
        type: "code_block",
        content: codeBlockMatch[2]?.trimEnd() ?? "",
        language: codeBlockMatch[1] || undefined,
      });
      remaining = remaining.slice(codeBlockMatch[0].length);
      continue;
    }

    // Check for line-level structures first
    const lineEnd = remaining.indexOf("\n");
    const line = lineEnd >= 0 ? remaining.slice(0, lineEnd) : remaining;

    // Heading ###
    const headingMatch = line.match(/^(#{1,3})\s+(.+)/);
    if (headingMatch) {
      const level = headingMatch[1]!.length;
      const content = headingMatch[2]!;
      segments.push({ type: "heading", content: renderInline(content, level) });
      remaining = remaining.slice(line.length + 1);
      continue;
    }

    // List item - or *
    const listMatch = line.match(/^[\-\*]\s+(.+)/);
    if (listMatch) {
      const content = listMatch[1]!;
      segments.push({ type: "list_item", content: renderInline(content) });
      remaining = remaining.slice(line.length + 1);
      continue;
    }

    // Empty line — just a newline
    if (line.trim() === "") {
      segments.push({ type: "text", content: "" });
      remaining = remaining.slice(Math.max(1, line.length + 1));
      continue;
    }

    // Regular text line — parse inline formatting
    segments.push({ type: "text", content: renderInline(line) });
    remaining = remaining.slice(line.length + 1);
  }

  return segments;
}

/**
 * Render inline markdown (bold, italic, code) within a line of text.
 * Returns the text with inline markers stripped (rendering hints
 * are applied at the component level via segment splits).
 *
 * This splits a line into sub-segments for bold/italic/code rendering.
 */
function renderInline(line: string, _headingLevel?: number): string {
  return line;
}

/**
 * Parse a single line into inline segments (bold, italic, code).
 * Returns array of { text, bold, italic, code } objects.
 */
function parseInline(line: string): Array<{
  text: string;
  bold?: boolean;
  italic?: boolean;
  code?: boolean;
}> {
  const segments: Array<{
    text: string;
    bold?: boolean;
    italic?: boolean;
    code?: boolean;
  }> = [];

  let remaining = line;

  while (remaining.length > 0) {
    // Inline code `...`
    const codeMatch = remaining.match(/^`([^`]+)`/);
    if (codeMatch) {
      segments.push({ text: codeMatch[1]!, code: true });
      remaining = remaining.slice(codeMatch[0].length);
      continue;
    }

    // Bold **...**
    const boldMatch = remaining.match(/^\*\*([^*]+)\*\*/);
    if (boldMatch) {
      segments.push({ text: boldMatch[1]!, bold: true });
      remaining = remaining.slice(boldMatch[0].length);
      continue;
    }

    // Italic *...* (but not **)
    const italicMatch = remaining.match(/^\*([^*]+)\*/);
    if (italicMatch) {
      segments.push({ text: italicMatch[1]!, italic: true });
      remaining = remaining.slice(italicMatch[0].length);
      continue;
    }

    // Plain character
    segments.push({ text: remaining[0]!, bold: false, italic: false, code: false });
    remaining = remaining.slice(1);
  }

  return segments;
}

/**
 * Render inline segments as Ink Text elements.
 */
function InlineRenderer({ line }: { line: string }) {
  const segments = parseInline(line);
  return (
    <Text>
      {segments.map((seg, i) => {
        if (seg.code) {
          return <Text key={i} backgroundColor="#333" color="#e6db74">{seg.text}</Text>;
        }
        if (seg.bold && seg.italic) {
          return <Text key={i} bold italic>{seg.text}</Text>;
        }
        if (seg.bold) {
          return <Text key={i} bold>{seg.text}</Text>;
        }
        if (seg.italic) {
          return <Text key={i} italic>{seg.text}</Text>;
        }
        return <Fragment key={i}>{seg.text}</Fragment>;
      })}
    </Text>
  );
}

/**
 * MarkdownRenderer — the main component.
 *
 * Accepts markdown text and renders it as styled Ink components.
 * Handles partial text gracefully (unclosed tokens render as plain text).
 */
export function MarkdownRenderer({ text }: MarkdownRendererProps) {
  if (!text || text.trim().length === 0) {
    return null;
  }

  const segments = parseMarkdown(text);

  return (
    <Box flexDirection="column">
      {segments.map((seg, i) => {
        switch (seg.type) {
          case "heading": {
            // Bold for headings (terminals don't have font sizes)
            return (
              <Text key={i} bold underline={seg.content.length > 0}>
                {seg.content}
              </Text>
            );
          }
          case "code_block": {
            const lines = seg.content.split("\n");
            return (
              <Box key={i} flexDirection="column" marginLeft={1}>
                {lines.map((line, j) => (
                  <Text key={j} backgroundColor="#333" color="#e6db74">
                    {"  "}{line}
                  </Text>
                ))}
              </Box>
            );
          }
          case "list_item": {
            return (
              <Box key={i} flexDirection="row">
                <Text color="#888">  • </Text>
                <InlineRenderer line={seg.content} />
              </Box>
            );
          }
          case "text": {
            if (seg.content === "") {
              return <Text key={i}>{"\n"}</Text>;
            }
            return (
              <Box key={i}>
                <InlineRenderer line={seg.content} />
              </Box>
            );
          }
          default:
            return <Text key={i}>{seg.content}</Text>;
        }
      })}
    </Box>
  );
}
