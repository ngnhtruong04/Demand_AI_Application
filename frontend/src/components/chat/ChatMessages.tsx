"use client";

const TOOL_NAME_MAP: Record<string, { en: string; vi: string }> = {
  get_sku_core_info:             { en: "Get SKU info",       vi: "Thông tin SKU" },
  get_sku_inventory_and_forecast:{ en: "Get inventory data",  vi: "Tồn kho & Dự báo" },
  get_sku_shap_drivers:          { en: "Calculate treeSHAP",        vi: "Tính treeSHAP" },
  compare_sku_peers:             { en: "Compare peers",           vi: "So sánh ngành hàng" },
  get_daily_forecast_series:     { en: "Get forecast",      vi: "Dự báo từng ngày" },
  get_portfolio_overview:        { en: "Get portfolio overview",  vi: "Tổng quan kho" },
  query_inventory_wiki:          { en: "Query wiki",              vi: "Tra cứu Wiki" },
  show_clarification_card:       { en: "Ask user", vi: "Hỏi người dùng" },
  export_replenishment_csv:      { en: "Export CSV",   vi: "Xuất file CSV nhập hàng" },
  generate_pdf_report:           { en: "Export PDF",    vi: "Tạo báo cáo PDF" },
};

function formatFriendlyToolName(toolName: string, lang: "en" | "vi" = "en"): string {
  return TOOL_NAME_MAP[toolName]?.[lang] ?? toolName;
}

import { useEffect, useRef, useState } from "react";
import katex from "katex";
import type { ChatMessage } from "@/types/chat";
import { getApiBaseUrl } from "@/lib/api";
import { Sparkle } from "../common/Icons";

function renderKatex(tex: string, displayMode: boolean, key?: React.Key): React.ReactNode {
  const clean = tex.trim();
  if (!clean) return null;
  try {
    const html = katex.renderToString(clean, {
      displayMode,
      throwOnError: false,
      output: "htmlAndMathml",
    });
    if (displayMode) {
      return (
        <div
          key={key}
          className="msg-math-block"
          dangerouslySetInnerHTML={{ __html: html }}
        />
      );
    }
    return (
      <span
        key={key}
        className="msg-math-inline"
        dangerouslySetInnerHTML={{ __html: html }}
      />
    );
  } catch {
    return <code key={key} className="msg-inline-code">{clean}</code>;
  }
}

interface ToolExecutionDropdownProps {
  steps?: import("@/types/chat").AgentStep[];
  toolsUsed?: string[];
  activeTool?: string;
  isThinking?: boolean;
  durationSeconds?: number;
  language?: "en" | "vi";
}

function ToolExecutionDropdown({
  steps = [],
  toolsUsed = [],
  activeTool,
  isThinking,
  durationSeconds,
  language = "en",
}: ToolExecutionDropdownProps) {
  const [isTopOpen, setIsTopOpen] = useState<boolean>(Boolean(isThinking));
  const wasThinkingRef = useRef<boolean>(Boolean(isThinking));

  useEffect(() => {
    if (wasThinkingRef.current && !isThinking) {
      setIsTopOpen(false);
    } else if (!wasThinkingRef.current && isThinking) {
      setIsTopOpen(true);
    }
    wasThinkingRef.current = Boolean(isThinking);
  }, [isThinking]);

  const [expandedThinks, setExpandedThinks] = useState<Record<number, boolean>>({});

  const duration = durationSeconds ?? Math.max(1, (steps.length || toolsUsed.length) * 2);
  const headline = isThinking
    ? (language === "vi" ? "Đang xử lý..." : "Working...")
    : (language === "vi" ? `Đã xử lý trong ${duration}s` : `Worked for ${duration}s`);

  // Synthesize steps if steps array is empty but toolsUsed exists
  const effectiveSteps: import("@/types/chat").AgentStep[] = steps.length > 0
    ? steps
    : toolsUsed.map((t) => ({ type: "tool" as const, toolName: t }));

  const toggleThink = (idx: number) => {
    setExpandedThinks((prev) => ({ ...prev, [idx]: !prev[idx] }));
  };

  return (
    <div className="tool-dropdown-container">
      {/* Top bar: "Worked for Xs ˅" */}
      <button
        type="button"
        className="tool-dropdown-top"
        onClick={() => setIsTopOpen((prev) => !prev)}
        aria-expanded={isTopOpen}
      >
        <span>{headline}</span>
        <span className={`tool-dropdown-chevron ${isTopOpen ? "is-open" : ""}`}>
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="6 9 12 15 18 9" />
          </svg>
        </span>
      </button>

      {/* Sequential list of each step */}
      {isTopOpen && (
        <div className="tool-step-list">
          {effectiveSteps.map((step, idx) => {
            if (step.type === "think") {
              const isExpanded = expandedThinks[idx] ?? (isThinking && idx === effectiveSteps.length - 1);
              return (
                <div className="tool-step-think-wrap" key={idx}>
                  <button
                    type="button"
                    className="tool-step-think-btn"
                    onClick={() => toggleThink(idx)}
                    aria-expanded={isExpanded}
                  >
                    <span>{language === "vi" ? "Suy nghĩ" : "Think"}</span>
                    <span className={`tool-dropdown-sub-chevron ${isExpanded ? "is-open" : ""}`}>
                      <svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                        <polyline points="9 18 15 12 9 6" />
                      </svg>
                    </span>
                  </button>
                  {isExpanded && step.content && (
                    <div className="tool-step-think-body">
                      {step.content}
                    </div>
                  )}
                </div>
              );
            }

            // Flat row for tool invocation: "Use tool <tool_name>" - no dropdown
            const friendlyName = formatFriendlyToolName(step.toolName || "", language);
            const useToolLabel = language === "vi" ? "Gọi tool" : "Use tool";
            return (
              <div className="tool-step-tool-row" key={idx}>
                <span className={`tool-dropdown-item-dot ${activeTool === step.toolName ? "is-active" : ""}`} />
                <span className="tool-step-tool-label">{useToolLabel} {friendlyName}</span>
                {step.toolName && <span className="tool-dropdown-item-code">{step.toolName}</span>}
              </div>
            );
          })}

          {/* If still actively thinking and no think step yet created */}
          {isThinking && effectiveSteps.length === 0 && (
            <div className="tool-step-tool-row">
              <span className="tool-dropdown-item-dot is-active" />
              <span className="tool-step-tool-label">{language === "vi" ? "Đang phân tích..." : "Analyzing demand data..."}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

import AssistantInquiryCard from "./AssistantInquiryCard";

// Smooth sequential character streaming animation — no parallel overlap
const CHAR_MS = 10;

function StreamingText({ text, isStreaming }: { text: string; isStreaming: boolean }) {
  const [hasStreamed, setHasStreamed] = useState(isStreaming);
  const [displayedLen, setDisplayedLen] = useState(0);
  const lenRef = useRef(0);
  const textRef = useRef(text);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (isStreaming) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setHasStreamed(true);
    }
  }, [isStreaming]);

  useEffect(() => {
    lenRef.current = displayedLen;
  }, [displayedLen]);

  useEffect(() => {
    textRef.current = text;
  }, [text]);

  useEffect(() => {
    if (!isStreaming && !hasStreamed) return;

    function tick() {
      const cur = lenRef.current;
      const target = textRef.current.length;

      if (cur < target) {
        const backlog = target - cur;
        const step = backlog > 80 ? 4 : backlog > 40 ? 2 : 1;
        const next = Math.min(target, cur + step);
        lenRef.current = next;
        setDisplayedLen(next);

        const delay = backlog > 50 ? 10 : CHAR_MS;
        timerRef.current = setTimeout(tick, delay);
      } else {
        timerRef.current = null;
      }
    }

    if (!timerRef.current && lenRef.current < text.length) {
      timerRef.current = setTimeout(tick, lenRef.current === 0 ? 0 : CHAR_MS);
    }
  }, [text.length, isStreaming, hasStreamed]);

  useEffect(() => {
    return () => {
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
  }, []);

  if (!isStreaming && !hasStreamed) {
    return <>{renderSimpleMarkdown(text)}</>;
  }

  if (!isStreaming && displayedLen >= text.length) {
    return <>{renderSimpleMarkdown(text)}</>;
  }

  const current = text.slice(0, displayedLen);
  const hasStructuredMarkdown = /\|.+\||```|^#{1,4}\s|\$\$|\\\[/m.test(current);

  if (hasStructuredMarkdown) {
    // Snap to last complete line — table rows only appear once their newline lands
    const lastNewline = current.lastIndexOf("\n");
    const completedLines = lastNewline >= 0 ? current.slice(0, lastNewline + 1) : "";
    return (
      <>
        {renderSimpleMarkdown(completedLines)}
        {isStreaming && <span className="streaming-cursor" aria-hidden="true" />}
      </>
    );
  }

  return (
    <span className="stream-text-wrap">
      {current.split("").map((ch, idx) => (
        <span
          key={idx}
          className={/\s/.test(ch) ? undefined : "magic-char"}
        >
          {ch}
        </span>
      ))}
      {isStreaming && <span className="streaming-cursor" aria-hidden="true" />}
    </span>
  );
}

interface ChatMessagesProps {
  messages: ChatMessage[];
  open: boolean;
  language?: "en" | "vi";
  isGenerating?: boolean;
  onSelectSuggestion: (text: string) => void;
  onClarificationAction?: (actionType: string, payload?: string, clarification?: import("@/types/chat").ClarificationPrompt) => void;
}

function sanitizeMessageText(rawText: string): string {
  if (!rawText) return "";
  let text = rawText;

  // 1. Normalize any malformed download URLs anywhere in the text (e.g. http://api//v1..., //api//v1..., api//v1..., http://localhost:8000/..., etc.)
  text = text.replace(
    /(?:https?:\/\/)?(?:\/\/)?(?:api|localhost(?::\d+)?|127\.0\.0\.1(?::\d+)?)?(?:\/|\/\/)+(?:v1(?:\/|\/\/)+)?forecast(?:\/|\/\/)+export(?:\/|\/\/)+download(?:\/|\/\/)+([a-zA-Z0-9_.\-]+)/gi,
    "/api/v1/forecast/export/download/$1"
  );

  // 2. Collapse any leftover multiple slashes in export download paths
  text = text.replace(/\/+api\/+v1\/+forecast\/+export\/+download\/+/gi, "/api/v1/forecast/export/download/");

  // 3. If a bare download URL exists in plain text (not already inside markdown link [label](url)), convert it to a clickable markdown link
  text = text.replace(
    /(^|[^\(\]])(\/api\/v1\/forecast\/export\/download\/([a-zA-Z0-9_.\-]+))/g,
    (_match, prefix, url, filename) => {
      const icon = filename.endsWith(".pdf") ? "📊" : "📥";
      const label = filename.endsWith(".pdf") ? "Tải báo cáo PDF" : "Tải file CSV";
      return `${prefix}[${icon} ${label} (${filename})](${url})`;
    }
  );

  // 4. Unwrap any bold-wrapped markdown links like **[label](url)** or 👉 **[label](url)**
  text = text.replace(/(👉\s*)?\*\*(\[[^\]]+\]\([^\)]+\))\*\*/g, "$1$2");

  return text;
}

function resolveDownloadUrl(rawUrl: string): string {
  let clean = rawUrl.trim();
  // Strip any accidental markdown formatting or surrounding brackets/parens/quotes/spaces
  clean = clean.replace(/^[<(\s"']+|[>) \s"']+$/g, "");

  // Strip host prefix if it points to api, localhost, or 127.0.0.1
  clean = clean.replace(/^(https?:\/\/)?(?:\/\/)?(?:api|localhost(?::\d+)?|127\.0\.0\.1(?::\d+)?)(?:\/|\/\/)+/i, "/");

  // Normalize consecutive slashes
  clean = clean.replace(/\/+/g, "/");
  if (!clean.startsWith("/")) {
    clean = "/" + clean;
  }

  // Ensure /api/v1 prefix if it starts with /v1/ or /forecast/
  if (clean.startsWith("/v1/")) {
    clean = "/api" + clean;
  } else if (clean.startsWith("/forecast/")) {
    clean = "/api/v1" + clean;
  }

  // If already an absolute http(s) URL pointing elsewhere, return clean
  if (clean.startsWith("http://") || clean.startsWith("https://")) {
    return clean;
  }

  // Route to real backend API base (e.g. http://127.0.0.1:8000)
  if (clean.startsWith("/api/")) {
    const base = getApiBaseUrl().replace(/\/+$/, "");
    return `${base}${clean}`;
  }

  return clean;
}

function renderInlineMarkdown(text: string): React.ReactNode {
  const parts = text.split(
    /(\$\$[\s\S]+?\$\$|\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\)|\$(?!\s)(?:\\\$|[^\$\n])+?(?<!\s)\$|\[[^\]]+\]\([^\)]+\)|`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*)/g
  );
  return parts.map((part, idx) => {
    if (!part) return null;
    // 1. Display math: $$...$$ or \[...\]
    if (part.startsWith("$$") && part.endsWith("$$") && part.length >= 4) {
      return renderKatex(part.slice(2, -2), true, idx);
    }
    if (part.startsWith("\\[") && part.endsWith("\\]") && part.length >= 4) {
      return renderKatex(part.slice(2, -2), true, idx);
    }
    // 2. Inline math: \(...\) or $...$
    if (part.startsWith("\\(") && part.endsWith("\\)") && part.length >= 4) {
      return renderKatex(part.slice(2, -2), false, idx);
    }
    if (part.startsWith("$") && part.endsWith("$") && part.length >= 2) {
      return renderKatex(part.slice(1, -1), false, idx);
    }
    // 3. Links
    if (part.startsWith("[") && part.includes("](") && part.endsWith(")")) {
      const closeBracket = part.indexOf("](");
      const rawLabel = part.slice(1, closeBracket).trim();
      const rawUrl = part.slice(closeBracket + 2, -1);
      const url = resolveDownloadUrl(rawUrl);
      const isDownload = url.includes("/export/download/") || url.endsWith(".csv") || url.endsWith(".pdf");
      const cleanLabel = rawLabel.replace(/\*\*/g, "").replace(/^\*+|\*+$/g, "").trim();
      return (
        <a
          key={idx}
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          className="msg-inline-link"
          download={isDownload ? true : undefined}
        >
          {cleanLabel}
        </a>
      );
    }
    // 4. Code
    if (part.startsWith("`") && part.endsWith("`")) {
      return (
        <code key={idx} className="msg-inline-code">
          {part.slice(1, -1)}
        </code>
      );
    }
    // 5. Bold & Italic
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={idx}>{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("*") && part.endsWith("*")) {
      return <em key={idx}>{part.slice(1, -1)}</em>;
    }
    return part;
  });
}

function parseMarkdownLines(text: string): React.ReactNode[] {
  const lines = text.split("\n");
  const nodes: React.ReactNode[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();

    // 1. Empty lines
    if (!trimmed) {
      nodes.push(<div key={`br-${i}`} className="msg-spacer" />);
      i++;
      continue;
    }

    // 2. Horizontal rule ('---', '***', '___')
    if (/^(\-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
      nodes.push(<hr key={`hr-${i}`} className="msg-divider" />);
      i++;
      continue;
    }

    // 3. Headings (# H1, ## H2, ### H3, #### H4)
    const headingMatch = line.match(/^(#{1,4})\s+(.+)$/);
    if (headingMatch) {
      const level = headingMatch[1].length;
      const headingText = headingMatch[2];
      nodes.push(
        <div key={`h-${i}`} className={`msg-h${level}`}>
          {renderInlineMarkdown(headingText)}
        </div>
      );
      i++;
      continue;
    }

    // 4. Markdown Table
    if (
      trimmed.startsWith("|") &&
      trimmed.endsWith("|") &&
      i + 1 < lines.length &&
      /^\|(\s*:?-+:?\s*\|)+$/.test(lines[i + 1].trim())
    ) {
      const headerRow = trimmed
        .split("|")
        .slice(1, -1)
        .map((cell) => cell.trim());
      i += 2; // skip header line and separator line

      const rows: string[][] = [];
      while (i < lines.length && lines[i].trim().startsWith("|") && lines[i].trim().endsWith("|")) {
        const rowCells = lines[i]
          .trim()
          .split("|")
          .slice(1, -1)
          .map((cell) => cell.trim());
        rows.push(rowCells);
        i++;
      }

      nodes.push(
        <div key={`table-${i}`} className="msg-table-wrap">
          <table className="msg-table">
            <thead>
              <tr>
                {headerRow.map((h, hIdx) => (
                  <th key={hIdx}>{renderInlineMarkdown(h)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, rIdx) => (
                <tr key={rIdx}>
                  {row.map((cell, cIdx) => (
                    <td key={cIdx}>{renderInlineMarkdown(cell)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
      continue;
    }

    // 5. Blockquote (> quote)
    if (trimmed.startsWith(">")) {
      const quoteText = trimmed.replace(/^>\s*/, "");
      nodes.push(
        <blockquote key={`quote-${i}`} className="msg-blockquote">
          {renderInlineMarkdown(quoteText)}
        </blockquote>
      );
      i++;
      continue;
    }

    // 6. Bullet lists (- item, * item, • item)
    const bulletMatch = line.match(/^(\s*)[-*•]\s+(.*)$/);
    if (bulletMatch) {
      nodes.push(
        <div key={`bullet-${i}`} className="msg-list-item">
          <span className="msg-bullet">•</span>
          <span>{renderInlineMarkdown(bulletMatch[2])}</span>
        </div>
      );
      i++;
      continue;
    }

    // 7. Numbered lists (1. item)
    const numMatch = line.match(/^(\s*)(\d+)\.\s+(.*)$/);
    if (numMatch) {
      nodes.push(
        <div key={`num-${i}`} className="msg-list-item">
          <span className="msg-bullet">{numMatch[2]}.</span>
          <span>{renderInlineMarkdown(numMatch[3])}</span>
        </div>
      );
      i++;
      continue;
    }

    // 8. Regular paragraph text
    nodes.push(
      <div key={`text-${i}`} className="msg-paragraph">
        {renderInlineMarkdown(line)}
      </div>
    );
    i++;
  }

  return nodes;
}

function renderSimpleMarkdown(rawText: string): React.ReactNode {
  const sanitized = sanitizeMessageText(rawText);
  const text = sanitized.replace(/<tool_call>[\s\S]*?<\/tool_call>/gi, "").trim();
  const blocks = text.split(/(```[\s\S]*?```|\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\])/g);
  return blocks.map((block, blockIdx) => {
    if (block.startsWith("```") && block.endsWith("```")) {
      const code = block.slice(3, -3).replace(/^[a-zA-Z0-9_-]+\n/, "");
      return (
        <pre key={blockIdx} className="msg-code-block">
          <code>{code}</code>
        </pre>
      );
    }
    if (block.startsWith("$$") && block.endsWith("$$")) {
      return renderKatex(block.slice(2, -2), true, blockIdx);
    }
    if (block.startsWith("\\[") && block.endsWith("\\]")) {
      return renderKatex(block.slice(2, -2), true, blockIdx);
    }
    return <div key={blockIdx}>{parseMarkdownLines(block)}</div>;
  });
}

export default function ChatMessages({
  messages,
  open,
  language = "en",
  isGenerating = false,
  onSelectSuggestion,
  onClarificationAction,
}: ChatMessagesProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const isNearBottomRef = useRef<boolean>(true);
  const prevMessagesLengthRef = useRef<number>(messages.length);

  const handleScroll = () => {
    const el = containerRef.current;
    if (!el) return;
    const distanceToBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    // Allow user to scroll freely: only auto-stick if user is within 70px of bottom
    isNearBottomRef.current = distanceToBottom < 70;
  };

  useEffect(() => {
    if (!open || !containerRef.current) return;
    const el = containerRef.current;
    const isNewTurn = messages.length > prevMessagesLengthRef.current;
    prevMessagesLengthRef.current = messages.length;

    // Scroll to bottom on new message or if user is near bottom
    if (isNewTurn || isNearBottomRef.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [messages, open]);

  return (
    <div
      ref={containerRef}
      onScroll={handleScroll}
      className="chat-messages"
      role="log"
      aria-live="polite"
      aria-label="Conversation"
    >

      {messages.map((message, index) => {
        const isLatest = index === messages.length - 1;

        return (
          <div className={`chat-message ${message.role}`} key={index}>
            {message.role === "assistant" && (
              <span className="message-avatar">
                <Sparkle />
              </span>
            )}
            <div className="message-content-wrap">
              <span className="message-author">
                {message.role === "assistant" ? "DemandAI" : "You"}
              </span>

              {/* Stacked dropdown tool box - OUTSIDE the message bubble */}
              {message.role === "assistant" && (message.isThinking || (message.steps && message.steps.length > 0) || (message.toolsUsed && message.toolsUsed.length > 0)) && (
                <ToolExecutionDropdown
                  steps={message.steps}
                  toolsUsed={message.toolsUsed}
                  activeTool={message.activeTool}
                  isThinking={message.isThinking}
                  durationSeconds={message.durationSeconds}
                  language={language}
                />
              )}

              {/* Message bubble: shows Thinking... indicator when working, or markdown content when text is available */}
              {message.isThinking && !message.text ? (
                <div className={`message-bubble is-thinking ${isLatest ? "is-latest" : ""}`}>
                  <div className="thinking-indicator">
                    <span className="thinking-text">Thinking...</span>
                    <span className="thinking-dots">
                      <span className="thinking-dot" />
                      <span className="thinking-dot" />
                      <span className="thinking-dot" />
                    </span>
                  </div>
                </div>
              ) : (
                (message.text || !message.isThinking) && (
                  <div className={`message-bubble ${isLatest ? "is-latest" : ""}`}>
                    {isLatest && message.role === "assistant"
                      ? <StreamingText text={message.text} isStreaming={isGenerating ?? false} />
                      : renderSimpleMarkdown(message.text)
                    }

                  {message.role === "assistant" && (
                    <>
                      {/* 1. Explicit Clarification Prompt: only render on latest message until answered/superseded */}
                      {message.clarification && index === messages.length - 1 && !(
                        typeof message.text === "string" && message.text.includes("/api/v1/forecast/export/download/")
                      ) && (
                        <AssistantInquiryCard
                          type={message.clarification.type}
                          title={message.clarification.title}
                          description={message.clarification.description}
                          actions={message.clarification.options.map((opt: any) => ({
                            label: opt.label,
                            sublabel: opt.sublabel || opt.description,
                            badge: opt.badge,
                            variant: opt.primary ? "primary" : "secondary",
                            onClick: () => {
                              if (opt.actionType === "view_item_on_screen" && opt.payload) {
                                onClarificationAction?.("view_item_on_screen", opt.payload, message.clarification);
                              } else if (opt.actionType === "select_sku" && opt.payload) {
                                onClarificationAction?.("select_sku", opt.payload, message.clarification);
                              } else if (opt.actionType === "send_text" && opt.payload) {
                                onSelectSuggestion(opt.payload);
                              } else if (opt.actionType === "run_forecast") {
                                onClarificationAction?.("run_forecast");
                              } else if (
                                (opt.actionType === "run_shap" || /shap|tính.*toán/i.test(opt.label)) &&
                                opt.payload
                              ) {
                                if (onClarificationAction) onClarificationAction("run_shap", opt.payload, message.clarification);
                                else onSelectSuggestion(
                                  language === "vi"
                                    ? `Tính toán giải thích TreeSHAP cho ${opt.payload}`
                                    : `Calculate TreeSHAP explainability for ${opt.payload}`
                                );
                              } else if (onClarificationAction) {
                                onClarificationAction(opt.actionType, opt.payload, message.clarification);
                              }
                            },
                          }))}
                          allowTextInput={message.clarification.allowTextInput}
                          textPlaceholder={message.clarification.textPlaceholder}
                          onSubmitText={(val) => onSelectSuggestion(val)}
                        />
                      )}
                    </>
                  )}
                </div>
              )
            )}
          </div>
        </div>
        );
      })}
    </div>
  );
}
