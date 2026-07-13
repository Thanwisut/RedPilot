/** MainConsole — terminal-style conversation with REDPILOT.
 *
 * Flow:
 *   > user input
 *   REDPILOT
 *   streamed response...
 *
 *   > next input
 *
 * When the LLM calls a tool:
 *   1. confirmation dialog appears
 *   2. Enter → ExecutionScreen with progress
 *   3. result → LLM follow-up with analysis
 */

import { useState, useEffect, useRef, useCallback } from "react";
import { useInput, useStdout, useApp } from "ink";
import { MarkdownText } from "@assistant-ui/react-ink-markdown";
import { Box, Text } from "../components/Ink.js";
import { palette } from "../theming/colors.js";
import { getSplashArt } from "../theming/splash-ascii.js";
import { getConfig } from "../services/config-store.js";
import { streamChat, buildToolSystemMessage } from "../providers/registry.js";
import type { ChatMessage, ToolCall } from "../providers/types.js";
import { AVAILABLE_TOOLS, getToolDefinition } from "../llm/tool-registry.js";
import { executeTool, setAutoApprove, getWsStatus } from "../services/ExecutionManager.js";
import type { ExecutionResult } from "../services/ExecutionManager.js";

const SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];
const SPINNER_INTERVAL = 80;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface HistoryEntry {
  role: "user" | "assistant" | "system" | "error";
  content: string;
}

type Phase =
  | { type: "idle" }
  | { type: "thinking"; spinnerIdx: number }
  | { type: "streaming"; content: string; done: boolean }
  | { type: "error"; message: string }
  | { type: "tool_call"; toolCall: ToolCall };

interface CommandDef {
  command: string;
  description: string;
}

const AVAILABLE_COMMANDS: CommandDef[] = [
  { command: "/help", description: "Show this help message" },
  { command: "/clear", description: "Clear conversation history" },
  { command: "/auto", description: "Toggle auto mode (tool calls execute without confirmation)" },
  { command: "/logout", description: "Return to setup wizard" },
  { command: "/exit", description: "Exit REDPILOT" },
];

// ---------------------------------------------------------------------------
// MainConsole
// ---------------------------------------------------------------------------

interface MainConsoleProps {
  onLogout?: () => void;
}

export function MainConsole({ onLogout }: MainConsoleProps) {
  const { stdout } = useStdout();
  const { exit } = useApp();
  const columns = stdout.columns ?? 80;
  const art = getSplashArt(columns);
  const config = getConfig();

  // ---- State ----
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [phase, setPhase] = useState<Phase>({ type: "idle" });
  const [inputBuffer, setInputBuffer] = useState("");
  const [cursorPos, setCursorPos] = useState(0);
  const [autoMode, setAutoMode] = useState(false);

  // ---- Refs ----
  const abortRef = useRef<AbortController | null>(null);
  const spinnerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const historyRef = useRef(history);
  historyRef.current = history;

  /** Ref used to bridge the async gap between useInput (sync) and sendMessage (async generator).
   *  When sendMessage receives a tool_call, it awaits a promise whose resolve function
   *  is stored here. useInput resolves it when the user presses Enter/Esc. */
  const toolCallPendingRef = useRef<{
    resolve: (result: ExecutionResult | null) => void;
    toolCall: ToolCall;
  } | null>(null);

  // ---- Cleanup ----
  useEffect(() => {
    return () => {
      if (spinnerRef.current) clearInterval(spinnerRef.current);
      abortRef.current?.abort();
    };
  }, []);

  // ---- Spinner ----
  const startSpinner = useCallback(() => {
    let idx = 0;
    setPhase({ type: "thinking", spinnerIdx: idx });
    spinnerRef.current = setInterval(() => {
      idx = (idx + 1) % SPINNER_FRAMES.length;
      setPhase((p) => (p.type === "thinking" ? { type: "thinking", spinnerIdx: idx } : p));
    }, SPINNER_INTERVAL);
  }, []);

  const stopSpinner = useCallback(() => {
    if (spinnerRef.current) {
      clearInterval(spinnerRef.current);
      spinnerRef.current = null;
    }
  }, []);

  // ---- Build messages for LLM request ----
  function buildMessages(extraMessages?: HistoryEntry[]): ChatMessage[] {
    const toolSysMsg = buildToolSystemMessage(AVAILABLE_TOOLS);
    const messages: ChatMessage[] = [];
    if (toolSysMsg) messages.push({ role: "system", content: toolSysMsg });
    for (const h of historyRef.current) {
      if (h.role === "user" || h.role === "assistant") {
        messages.push({ role: h.role as "user" | "assistant", content: h.content });
      }
    }
    if (extraMessages) {
      for (const m of extraMessages) {
        if (m.role === "user" || m.role === "assistant" || m.role === "system") {
          messages.push({ role: m.role as "user" | "assistant" | "system", content: m.content });
        }
      }
    }
    return messages;
  }

  // ---- Stream response from LLM ----
  async function streamResponse(
    messages: ChatMessage[],
    onText: (text: string) => void,
    onToolCall: (tc: ToolCall) => void,
    onError: (err: string) => void,
    onDone: () => void,
  ) {
    const cfg = config;
    if (!cfg?.provider || !cfg?.model || !cfg?.apiKey) {
      stopSpinner();
      setPhase({ type: "idle" });
      return;
    }
    const abortController = new AbortController();
    abortRef.current = abortController;

    const stream = streamChat({
      provider: cfg.provider,
      messages,
      model: cfg.model,
      apiKey: cfg.apiKey,
      baseUrl: "baseUrl" in cfg ? (cfg as { baseUrl?: string }).baseUrl : undefined,
      signal: abortController.signal,
      tools: AVAILABLE_TOOLS,
    });

    for await (const chunk of stream) {
      switch (chunk.type) {
        case "text":
          stopSpinner();
          if (chunk.text) onText(chunk.text);
          break;
        case "tool_call":
          stopSpinner();
          onToolCall(chunk.toolCall!);
          return; // pause streaming — tool call needs user confirmation
        case "error":
          stopSpinner();
          onError(chunk.error ?? "Unknown error");
          return;
        case "done":
          stopSpinner();
          onDone();
          return;
      }
    }
    stopSpinner();
    onDone();
  }

  // ---- Send message + handle full tool call loop ----
  const sendMessage = useCallback(async (text: string) => {
    if (!config?.provider || !config?.model) {
      setPhase({ type: "error", message: "No provider configured. Type /logout to configure." });
      return;
    }

    // Add user message to history
    setHistory((prev) => [...prev, { role: "user", content: text }]);

    // Initial stream
    startSpinner();
    let fullContent = "";

    try {
      const messages = buildMessages();

      // Add user's message
      messages.push({ role: "user", content: text });

      await streamResponse(
        messages,
        (token) => {
          fullContent += token;
          setPhase({ type: "streaming", content: fullContent, done: false });
        },
        async (tc) => {
          /**
           * Continue with a tool result: add to history and start LLM follow-up.
           * Does NOT execute the tool — the result is already provided.
           */
          async function continueWithResult(
            tool: ToolCall,
            execResult: ExecutionResult,
          ): Promise<void> {
            const argsStr = Object.entries(tool.arguments)
              .map(([k, v]) => `${k}: ${v}`)
              .join(", ");

            if (!execResult) {
              setHistory((prev) => [...prev, { role: "system", content: `Tool call failed: ${tool.name}` }]);
              setPhase({ type: "idle" });
              return;
            }

            // Tool executed — add to history
            setHistory((prev) => [
              ...prev,
              { role: "assistant", content: `[Called tool: ${tool.name}(${argsStr})]` },
              { role: "system", content: `Tool "${tool.name}" result:\n${execResult.summary}\n\n${execResult.details}` },
            ]);

            // ── FOLLOW-UP: LLM continues with tool result ───
            startSpinner();
            fullContent = "";

            const followupMessages = buildMessages([
              { role: "assistant", content: `[Called tool: ${tool.name}(${argsStr})]` },
              { role: "system", content: `Tool "${tool.name}" result:\n${execResult.summary}\n\n${execResult.details}` },
            ]);

            const doNested = autoMode
              ? (nextTc: ToolCall) => executeAndContinue(nextTc)
              : (nextTc: ToolCall) => {
                  fullContent += `\n\n[Requested tool: ${nextTc.name}]`;
                  setPhase({ type: "tool_call", toolCall: nextTc });
                };

            await streamResponse(
              followupMessages,
              (token) => {
                fullContent += token;
                setPhase({ type: "streaming", content: fullContent, done: false });
              },
              doNested,
              (err) => {
                setPhase({ type: "error", message: err });
              },
              () => {
                setPhase({ type: "streaming", content: fullContent, done: true });
              },
            );
          }

          /** Execute a tool inline and continue with follow-up.
           *  Shows "using tool rn bro!" while executing, then
           *  continueWithResult adds the clean result entries. */
          async function executeAndContinue(tool: ToolCall): Promise<void> {
            const inlineArgs = Object.entries(tool.arguments)
              .map(([k, v]) => `${k}: ${v}`)
              .join(", ");
            setHistory((prev) => [...prev, {
              role: "system",
              content: `using ${tool.name}(${inlineArgs}) rn bro!`,
            }]);

            let execResult: ExecutionResult;
            try {
              execResult = await executeTool(tool);
            } catch (err: unknown) {
              // Replace "using..." with error on unexpected failure
              const errMsg = err instanceof Error ? err.message : String(err);
              setHistory((prev) => {
                const updated = [...prev];
                if (updated.length > 0) {
                  updated[updated.length - 1] = {
                    role: "error",
                    content: `Tool errored: ${tool.name} — ${errMsg}`,
                  };
                }
                return updated;
              });
              setPhase({ type: "idle" });
              return;
            }

            // Replace "using..." with failure if no result returned
            if (!execResult) {
              setHistory((prev) => {
                const updated = [...prev];
                if (updated.length > 0) {
                  updated[updated.length - 1] = { role: "error", content: `Tool call failed: ${tool.name}` };
                }
                return updated;
              });
              setPhase({ type: "idle" });
              return;
            }

            // continueWithResult adds clean [Called tool: ...] + result entries
            await continueWithResult(tool, execResult);
          }

          // ── AUTO MODE: execute immediately (inline "using... rn bro!" shown) ──
          if (autoMode) {
            await executeAndContinue(tc);
            return;
          }

          // ── MANUAL MODE: wait for user to confirm or cancel ─────
          setPhase({ type: "tool_call", toolCall: tc });

          const userResult = await new Promise<ExecutionResult | null>((resolve) => {
            toolCallPendingRef.current = { resolve, toolCall: tc };
          });

          toolCallPendingRef.current = null;

          if (!userResult) {
            // Cancelled
            setHistory((prev) => [...prev, { role: "system", content: `Tool call cancelled: ${tc.name}` }]);
            setPhase({ type: "idle" });
            return;
          }

          await continueWithResult(tc, userResult);
        },
        (err) => {
          setPhase({ type: "error", message: err });
        },
        () => {
          setPhase({ type: "streaming", content: fullContent, done: true });
        },
      );
    } catch (err: unknown) {
      stopSpinner();
      if ((err as Error)?.name === "AbortError") {
        setPhase({ type: "idle" });
        return;
      }
      setPhase({ type: "error", message: String(err) });
    }
  }, [config, startSpinner, stopSpinner, autoMode]);

  // ---- Handle streaming completion ----
  useEffect(() => {
    if (phase.type === "streaming" && phase.done && phase.content) {
      setHistory((prev) => [...prev, { role: "assistant", content: phase.content }]);
      setPhase({ type: "idle" });
    }
  }, [phase]);

  // ---- Handle errors ----
  useEffect(() => {
    if (phase.type === "error") {
      setHistory((prev) => [...prev, { role: "error", content: phase.message }]);
      setPhase({ type: "idle" });
    }
  }, [phase]);

  // ---- Input handling ----
  useInput((input, key) => {
    // Tool call confirmation
    if (phase.type === "tool_call") {        if (key.return) {
          const pending = toolCallPendingRef.current;
          if (!pending) return;
          // Clear tool_call phase and show execution indicator
          setPhase({ type: "idle" });
          setHistory((prev) => [...prev, {
            role: "system",
            content: `executing ${pending.toolCall.name}...`,
          }]);
          // Execute asynchronously (inline result via history)
          executeTool(pending.toolCall).then((result) => {
            pending.resolve(result);
          }).catch(() => {
            pending.resolve(null);
          });
        }
      if (key.escape) {
        toolCallPendingRef.current?.resolve(null);
        toolCallPendingRef.current = null;
        setPhase({ type: "idle" });
      }
      return;
    }

    // Abort streaming
    if (phase.type === "streaming" && !phase.done && key.escape) {
      abortRef.current?.abort();
      stopSpinner();
      setPhase({ type: "idle" });
      return;
    }

    // Submit input
    if (key.return) {
      const text = inputBuffer.trim();
      if (text.length === 0) return;
      if (text.startsWith("/")) {
        handleCommand(text);
      } else {
        sendMessage(text).catch((err) => {
          // Prevent unhandled AbortError crashes
          if ((err as Error)?.name !== "AbortError") {
            console.error("sendMessage error:", err);
          }
        });
      }
      setInputBuffer("");
      setCursorPos(0);
      return;
    }

    // Backspace at cursor
    if (key.backspace || key.delete) {
      if (cursorPos > 0) {
        const before = inputBuffer.slice(0, cursorPos - 1);
        const after = inputBuffer.slice(cursorPos);
        setInputBuffer(before + after);
        setCursorPos((p) => p - 1);
      }
      return;
    }

    // Arrow keys
    if (key.leftArrow) { setCursorPos((p) => Math.max(0, p - 1)); return; }
    if (key.rightArrow) { setCursorPos((p) => Math.min(inputBuffer.length, p + 1)); return; }

    // Clear input
    if (key.escape) { setInputBuffer(""); setCursorPos(0); return; }

    // Printable characters
    if (input.length > 0 && /^[ -~]+$/.test(input)) {
      const before = inputBuffer.slice(0, cursorPos);
      const after = inputBuffer.slice(cursorPos);
      setInputBuffer(before + input + after);
      setCursorPos((p) => p + input.length);
    }
  });

  // ---- Commands ----
  function handleCommand(cmd: string) {
    const lower = cmd.toLowerCase();
    switch (lower) {
      case "/logout": case "logout": onLogout?.(); break;
      case "/clear": case "clear": setHistory([]); break;
      case "/exit": case "quit": case "/quit": exit(); break;
      case "/auto": {
        const newVal = !autoMode;
        setAutoMode(newVal);
        // Sync with WS approval gate: when auto mode is on, auto-approve
        // approval.requested events from the backend so it doesn't stall.
        setAutoApprove(newVal);
        const wsStatus = getWsStatus();
        setHistory((prevH) => [...prevH, {
          role: "system",
          content: [
            `Auto mode: ${newVal ? "ON" : "OFF"}. Tool calls will ${newVal ? "execute automatically without confirmation" : "prompt for approval before executing"}.`,
            wsStatus.connected
              ? `Backend: connected (${wsStatus.url})`
              : wsStatus.connecting
                ? `Backend: connecting... (${wsStatus.url})`
                : `Backend: disconnected — local mode`,
            wsStatus.autoApprove ? "Auto-approve: active — approval requests auto-approved" : "Auto-approve: inactive — requires manual approval",
          ].join("\n"),
        }]);
        break;
      }
      case "/help": case "help":
        setHistory((prev) => [...prev, {
          role: "assistant",
          content: [
            "Available commands:",
            "  /help     — Show this message",
            "  /clear    — Clear conversation history",
            "  /auto     — Toggle auto mode (tool calls execute without confirmation)",
            "  /logout   — Return to setup wizard",
            "  /exit     — Exit REDPILOT",
            "",
            `Auto mode is currently: ${autoMode ? "ON \u2014 tools execute immediately" : "OFF \u2014 tools require approval"}`,
            "",
            "Or just type anything to chat with me.",
          ].join("\n"),
        }]);
        break;
      default:
        setHistory((prev) => [...prev, { role: "error", content: `Unknown command: "${cmd}". Type /help for available commands.` }]);
    }
  }

  // =====================================================================
  // RENDER
  // =====================================================================


  // ── Spinner ──
  const spinnerChar = phase.type === "thinking"
    ? SPINNER_FRAMES[phase.spinnerIdx] ?? SPINNER_FRAMES[0]
    : null;

  // ── WS status (for banner and commands) ──
  const wsStatus = history.length === 0 && phase.type === "idle" ? getWsStatus() : null;
  const backendLabel = wsStatus
    ? wsStatus.connected
      ? "\u2713 connected (WS)"
      : wsStatus.connecting
        ? "connecting..."
        : "\u2014 local mode"
    : "";

  function renderPromptLine() {
    const before = inputBuffer.slice(0, cursorPos);
    const at = inputBuffer[cursorPos] ?? " ";
    const after = inputBuffer.slice(cursorPos + 1);
    return (
      <Box marginTop={1}>
        <Text color={palette.amber} bold>{"> "}</Text>
        <Text color={palette.white}>{before}</Text>
        <Text color={palette.grayDark} underline>{at}</Text>
        <Text color={palette.white}>{after}</Text>
        {autoMode && <Text color={palette.amber}> (auto)</Text>}
      </Box>
    );
  }

  return (
    <Box flexDirection="column" paddingX={2} paddingY={1}>
      {/* Banner */}
      {history.length === 0 && phase.type === "idle" && (
        <Box flexDirection="column">
          {art.map((line, i) => (
            <Text key={i} color={palette.red}>{line || " "}</Text>
          ))}
          <Box flexDirection="column" marginTop={1}>
            <Box>
              <Text color={palette.grayLight}>
                Provider: <Text color={palette.white} bold>{config?.provider ?? "—"}</Text>
              </Text>
              {autoMode && <Text color={palette.amber} bold>  [AUTO MODE]</Text>}
            </Box>
            <Text color={palette.grayLight}>
              Model: <Text color={palette.white} bold>{config?.model ?? "—"}</Text>
            </Text>
            <Text color={palette.grayLight}>
              Backend: <Text color={palette.grayMid}>{backendLabel}</Text>
            </Text>
            <Box marginTop={1}>
              <Text color={autoMode ? palette.amber : palette.statusCompleted}>
                {autoMode ? "Auto mode — tools execute without confirmation. Type /auto to disable." : "Ready."}
              </Text>
            </Box>
          </Box>
          <Box marginTop={1}>
            <Text dimColor color={palette.grayDark}>Type a message or /help for commands.</Text>
          </Box>
          <Box marginTop={1}>
            <Text color={palette.grayDark}>{"\u2500".repeat(Math.min(45, columns - 4))}</Text>
          </Box>
        </Box>
      )}

      {/* Conversation history */}
      <Box flexDirection="column" flexGrow={1}>
        {history.map((entry, i) => (
          <Box key={i} flexDirection="column" marginTop={1}>
            {entry.role === "user" && (
              <Box><Text color={palette.amber} bold>{"> "}</Text><Text color={palette.white}>{entry.content}</Text></Box>
            )}
            {entry.role === "assistant" && (
              <Box flexDirection="column">
                <Text bold color={palette.red}>REDPILOT</Text>
                <MarkdownText
                  text={entry.content}
                />
              </Box>
            )}
            {entry.role === "error" && (
              <Box><Text color={palette.statusFailed}>⚠ {entry.content}</Text></Box>
            )}
            {entry.role === "system" && (
              <Box><Text color={palette.grayDark} dimColor>⚙ {entry.content}</Text></Box>
            )}
          </Box>
        ))}

        {/* Streaming — uses MarkdownText for proper bold/italic/code rendering */}
        {phase.type === "streaming" && (
          <Box flexDirection="column" marginTop={1}>
            <Text bold color={palette.red}>REDPILOT</Text>
            <MarkdownText
              text={phase.content}
            />
            {!phase.done && <Text color={palette.grayMid}>{"\u258C"}</Text>}
          </Box>
        )}

        {/* Spinner */}
        {phase.type === "thinking" && (
          <Box marginTop={1}><Text color={palette.cyan}>{spinnerChar} REDPILOT is thinking...</Text></Box>
        )}

        {/* Error */}
        {phase.type === "error" && (
          <Box marginTop={1}><Text color={palette.statusFailed}>⚠ {phase.message}</Text></Box>
        )}

        {/* Tool call confirmation */}
        {phase.type === "tool_call" && phase.toolCall && (
          <Box flexDirection="column" marginTop={1} paddingX={1} paddingY={1} borderStyle="round" borderColor={palette.cyan}>
            <Text bold color={palette.cyan}>
              {getToolDefinition(phase.toolCall.name)?.description ?? `Tool: ${phase.toolCall.name}`}
            </Text>
            {Object.entries(phase.toolCall.arguments).map(([k, v]) => (
              <Text key={k} color={palette.grayLight}>  {k}: {String(v)}</Text>
            ))}
            <Box marginTop={1}><Text color={palette.statusCompleted}>Enter  Execute</Text></Box>
            <Box><Text color={palette.grayMid}>Esc   Cancel</Text></Box>
          </Box>
        )}
      </Box>

      {/* Prompt */}
      {phase.type === "idle" && renderPromptLine()}

      {/* Command suggestions when typing / */}
      {phase.type === "idle" && inputBuffer.startsWith("/") && inputBuffer.length > 0 && (
        <Box flexDirection="column" marginTop={1} marginLeft={2}>
          {AVAILABLE_COMMANDS
            .filter((c) => c.command.startsWith(inputBuffer.toLowerCase()))
            .map((c) => (
              <Text key={c.command} color={palette.grayLight}>
                <Text color={palette.amber}>{c.command}</Text>{"  — "}{c.description}
              </Text>
            ))
          }
        </Box>
      )}
    </Box>
  );
}
