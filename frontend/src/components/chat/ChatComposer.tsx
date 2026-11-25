"use client";

import React, { useState, useRef, useEffect } from "react";
import {
  SendIcon,
  PlusIcon,
  FileTextIcon,
  AlertTriangleIcon,
  AlertOctagonIcon,
  TrendingUpIcon,
  TrendingDownIcon,
  CommandIcon,
  PackageIcon,
  GlobeIcon,
  RocketIcon,
  ClockIcon,
  PlayIcon,
  Sparkle,
} from "../common/Icons";
import type { ContextInfo, ChatMessage } from "@/types/chat";
import type { ForecastState, ForecastedItem } from "@/types/forecast";
import { fetchAvailableModels, type ModelInfo } from "@/lib/chatApi";
import AssistantInquiryCard from "./AssistantInquiryCard";

interface ChatComposerProps {
  inputRef: React.RefObject<HTMLTextAreaElement | null>;
  draft: string;
  onChangeDraft: (text: string) => void;
  onSend: (text?: string) => void;
  contextInfo?: ContextInfo;
  isGenerating?: boolean;
  selectedModel?: string;
  onSelectModel?: (model: string) => void;
  language?: "en" | "vi";
  onSelectLanguage?: (lang: "en" | "vi") => void;
  forecastState?: ForecastState;
  onRunForecast?: () => void;
  onStopGeneration?: () => void;
  selectedItem?: ForecastedItem | null;
  messages?: ChatMessage[];
}

interface SlashCommand {
  cmd: string;
  label: string;
  desc: string;
  argsHint?: string;
}

interface WarehouseOption {
  id: string;
  name: string;
}

export interface PdfReportMode {
  id: "overview" | "critical" | "deadstock" | "best_seller";
  label: string;
  icon: React.ReactNode;
  focusTitle: string;
}

export const PDF_REPORT_MODES: PdfReportMode[] = [
  {
    id: "overview",
    label: "Full Overview",
    icon: <GlobeIcon size={13} />,
    focusTitle: "Full Overview",
  },
];

const SYSTEM_WAREHOUSES: WarehouseOption[] = [
  { id: "all", name: "All Warehouses" },
  { id: "brno_1", name: "Brno_1" },
  { id: "budapest_1", name: "Budapest_1" },
  { id: "frankfurt_1", name: "Frankfurt_1" },
  { id: "munich_1", name: "Munich_1" },
  { id: "prague_1", name: "Prague_1" },
  { id: "prague_2", name: "Prague_2" },
  { id: "prague_3", name: "Prague_3" },
];

const PROMPT_OPTIONS = [
  {
    label: "Executive report",
    prompt: "Draft an executive 14-day demand forecast report with replenishment guidance",
    desc: "Structured summary of demand trends, peak days, drivers, and PO actions",
    icon: FileTextIcon,
  },
  {
    label: "Stockout risks",
    prompt: "Analyze items with critical stockout risks and days of supply",
    desc: "Identify items with urgent stockout alerts or depleted safety buffers",
    icon: AlertTriangleIcon,
  },
  {
    label: "Peak velocity trends",
    prompt: "Analyze day-of-week demand velocity and upcoming peak days",
    desc: "Inspect temporal patterns, Tuesday spikes, and weekend dynamics",
    icon: TrendingUpIcon,
  },
  {
    label: "Price elasticity simulation",
    prompt: "Simulate demand shift and revenue elasticity under price changes (+15% or -20%)",
    desc: "Predict 14-day demand, revenue delta, and deadstock clearance feasibility",
    icon: TrendingUpIcon,
  },
  {
    label: "Warehouse report & CSV",
    prompt: "/warehouse Prague_1 generate Full Overview PDF report",
    desc: "Export Full Overview PDF report or replenishment CSV for a specific warehouse",
    icon: PackageIcon,
  },
];

const COMMAND_OPTIONS: SlashCommand[] = [
  {
    cmd: "/warehouse",
    label: "Warehouse Search & Export",
    desc: "Search warehouse to generate executive PDF reports or export replenishment CSV",
    argsHint: "<warehouse>",
  },
  {
    cmd: "/overview",
    label: "Portfolio Overview",
    desc: "Portfolio health status, 14d forecast demand, and critical alerts",
  },
  {
    cmd: "/reorder",
    label: "Reorder & ROP Analysis",
    desc: "Stockout risk, Days of Supply, and recommended PO order quantity",
    argsHint: "<sku>",
  },
  {
    cmd: "/timeline",
    label: "Daily Timeline & Peaks",
    desc: "Day-of-week breakdown (Tuesday spike, weekend) and daily depletion date",
    argsHint: "<sku>",
  },
  {
    cmd: "/drivers",
    label: "TreeSHAP Drivers",
    desc: "Feature engineering weights, pricing discounts, and drag factors",
    argsHint: "<sku>",
  },
  {
    cmd: "/report",
    label: "Executive 14d Report",
    desc: "Structured 14-day forecast report with concrete PO replenishment guidance",
    argsHint: "<sku>",
  },
  {
    cmd: "/risks",
    label: "Stockout & Deadstock Risks",
    desc: "Emergency triage for items facing stockouts or excess capital sinks",
  },
  {
    cmd: "/simulate",
    label: "What-If Price Simulation",
    desc: "Simulate demand & revenue elasticity under discount (-20%) or price hike (+15%)",
    argsHint: "<sku> <+/-pct>",
  },
  {
    cmd: "/peers",
    label: "Compare Peers",
    desc: "Category peer rankings, demand share, and substitute items",
    argsHint: "<category>",
  },
  {
    cmd: "/item",
    label: "Item 360 Analysis",
    desc: "Deep forecast metrics, bounds, on-hand stock, and ROP parameters",
    argsHint: "<sku>",
  },
  {
    cmd: "/help",
    label: "Help & Skills",
    desc: "List all assistant tools, capabilities, and slash commands",
  },
];

export default function ChatComposer({
  inputRef,
  draft,
  onChangeDraft,
  onSend,
  contextInfo,
  isGenerating = false,
  selectedModel = "gpt-6-luna",
  onSelectModel,
  language = "en",
  onSelectLanguage,
  forecastState,
  onRunForecast,
  onStopGeneration,
  selectedItem,
  messages,
}: ChatComposerProps) {
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [dismissedLang, setDismissedLang] = useState<string | null>(null);
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const [menuTab, setMenuTab] = useState<"prompts" | "commands">("prompts");
  const [suggestIdx, setSuggestIdx] = useState(0);
  const [expandedPdfWhId, setExpandedPdfWhId] = useState<string | null>(null);
  const [isSuggestDismissed, setIsSuggestDismissed] = useState(false);
  const [isOffline, setIsOffline] = useState(false);
  const [retryTrigger, setRetryTrigger] = useState(0);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let isMounted = true;
    let lastBootId: string | undefined;
    let failCount = 0;

    const checkModels = async () => {
      const res = await fetchAvailableModels();
      if (!isMounted) return;
      if (res.models.length > 0) {
        setModels(res.models);
        setIsOffline(false);
        const resetDetected = lastBootId !== undefined && res.bootId !== lastBootId;
        lastBootId = res.bootId;
        const isValid = res.models.some((m) => m.name === selectedModel);
        if (!isValid || resetDetected || (!selectedModel && res.defaultModel)) {
          onSelectModel?.(res.defaultModel || res.models[0].name);
        }
      } else {
        failCount++;
        if (failCount >= 3) {
          setIsOffline(true);
        }
      }
    };

    checkModels();
    // Do not poll repeatedly; check only on window focus or reconnection to avoid spamming backend
    const onFocus = () => checkModels();
    window.addEventListener("focus", onFocus);
    window.addEventListener("online", onFocus);

    return () => {
      isMounted = false;
      window.removeEventListener("focus", onFocus);
      window.removeEventListener("online", onFocus);
    };
  }, [retryTrigger]);

  // Warehouse command and search detection
  const isWarehouseMode = (draft === "/warehouse" || draft.startsWith("/warehouse ")) && !draft.includes("\n") && !isSuggestDismissed;
  const whSearchQuery = isWarehouseMode
    ? draft.slice("/warehouse".length).trim().toLowerCase()
    : "";
  const filteredWarehouses = isWarehouseMode
    ? SYSTEM_WAREHOUSES.filter((w) =>
        w.name.toLowerCase().includes(whSearchQuery)
      )
    : [];

  // General slash command typing
  const isTypingSlash = !isWarehouseMode && draft.startsWith("/") && !draft.includes("\n") && !isSuggestDismissed;
  const slashQuery = isTypingSlash ? draft.slice(1).toLowerCase().trim() : "";
  const filteredCommands = isTypingSlash
    ? COMMAND_OPTIONS.filter(
        (c) =>
          c.cmd.slice(1).toLowerCase().includes(slashQuery) ||
          c.label.toLowerCase().includes(slashQuery)
      )
    : [];

  const showSlashSuggest = isWarehouseMode
    ? filteredWarehouses.length > 0
    : isTypingSlash && filteredCommands.length > 0;

  const currentSuggestCount = isWarehouseMode ? filteredWarehouses.length : filteredCommands.length;
  const activeSuggestIdx = Math.min(suggestIdx, Math.max(0, currentSuggestCount - 1));

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setIsMenuOpen(false);
      }
    }
    if (isMenuOpen) {
      document.addEventListener("mousedown", handleClickOutside);
    }
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [isMenuOpen]);

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (isGenerating) return;
    onSend(draft);
  }

  function handleSelectWarehouse(wh: WarehouseOption, action: "insert" | "csv" = "insert") {
    setIsSuggestDismissed(true);
    setIsMenuOpen(false);
    setExpandedPdfWhId(null);
    const target = wh.name;
    if (action === "csv") {
      onChangeDraft(`Export replenishment CSV recommendation for warehouse ${target}`);
    } else {
      onChangeDraft(`/warehouse ${target} `);
    }
    inputRef.current?.focus();
  }

  function handleSelectWarehousePdfMode(wh: WarehouseOption, mode: PdfReportMode) {
    setIsSuggestDismissed(true);
    setIsMenuOpen(false);
    setExpandedPdfWhId(null);
    onChangeDraft(`Generate PDF executive report on ${mode.focusTitle} for warehouse ${wh.name}`);
    inputRef.current?.focus();
  }

  function handleSelectCommand(cmd: SlashCommand) {
    setIsMenuOpen(false);
    if (cmd.cmd === "/warehouse") {
      setIsSuggestDismissed(false);
      onChangeDraft("/warehouse ");
      setSuggestIdx(0);
    } else {
      setIsSuggestDismissed(true);
      if (cmd.argsHint) {
        onChangeDraft(`${cmd.cmd} `);
      } else {
        onChangeDraft(cmd.cmd);
      }
    }
    inputRef.current?.focus();
  }

  function handleSelectOption(prompt: string) {
    setIsMenuOpen(false);
    if (!isGenerating) {
      onSend(prompt);
    }
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (showSlashSuggest) {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        setSuggestIdx((prev) => (prev + 1) % currentSuggestCount);
        return;
      }
      if (event.key === "ArrowUp") {
        event.preventDefault();
        setSuggestIdx((prev) => (prev - 1 + currentSuggestCount) % currentSuggestCount);
        return;
      }
      if (event.key === "Enter" || event.key === "Tab") {
        event.preventDefault();
        if (isWarehouseMode) {
          const chosenWh = filteredWarehouses[activeSuggestIdx];
          if (chosenWh) {
            handleSelectWarehouse(chosenWh, "insert");
            return;
          }
        } else {
          const chosen = filteredCommands[activeSuggestIdx];
          if (chosen) {
            handleSelectCommand(chosen);
            return;
          }
        }
      }
      if (event.key === "Escape") {
        event.preventDefault();
        setIsSuggestDismissed(true);
        return;
      }
    }

    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (!isGenerating && draft.trim()) {
        onSend(draft);
      }
    }
  }

  function handleDraftChange(val: string) {
    setIsSuggestDismissed(false);
    setSuggestIdx(0);
    onChangeDraft(val);
  }

  const [ignoreLangMismatch, setIgnoreLangMismatch] = useState<boolean>(false);

  const hasViMarkers =
    /[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]/i.test(draft) ||
    /\b(không|sản phẩm|món|hàng|tồn|dự báo|đứt|nhu cầu|tại sao|nguyên nhân|kho|bao nhiêu|thứ|ngày)\b/i.test(draft);

  const isEnDraft =
    /^[a-zA-Z0-9\s.,?!'":;/\-_]+$/.test(draft.trim()) &&
    draft.trim().split(/\s+/).length >= 3 &&
    /\b(what|why|how|when|is|are|the|this|that|stock|inventory|forecast|demand|item|reorder)\b/i.test(draft);

  const showSwitchToVi = !ignoreLangMismatch && language === "en" && hasViMarkers && dismissedLang !== "vi";
  const showSwitchToEn = !ignoreLangMismatch && language === "vi" && isEnDraft && dismissedLang !== "en";

  const isNewSession = !messages || !messages.some((m) => m.role === "user");
  const isVi = language === "vi";

  const suggestionBubbles = selectedItem
    ? [
        {
          label: isVi
            ? `Phân tích toàn diện ${selectedItem.name} (${selectedItem.sku}): sức khỏe tồn kho, đề xuất đặt hàng (ROP).`
            : `Analyze ${selectedItem.name} (${selectedItem.sku}): inventory health, replenishment urgency (ROP).`,
          prompt: isVi
            ? `Phân tích toàn diện ${selectedItem.name} (${selectedItem.sku}): sức khỏe tồn kho, đề xuất đặt hàng (ROP).`
            : `Analyze ${selectedItem.name} (${selectedItem.sku}): inventory health, replenishment urgency (ROP).`,
          isPrimary: true,
        },
        {
          label: isVi
            ? `Giải thích TreeSHAP và biến động cho ${selectedItem.sku}`
            : `Explain TreeSHAP drivers for ${selectedItem.sku}`,
          prompt: isVi
            ? `Tính toán và giải thích TreeSHAP drivers cho SKU ${selectedItem.sku}`
            : `Explain TreeSHAP feature drivers and impact factors for ${selectedItem.sku}`,
          isPrimary: false,
        },
      ]
    : [
        {
          label: isVi
            ? "Lập báo cáo dự báo nhu cầu 14 ngày kèm hướng dẫn nhập hàng"
            : "Draft an executive 14-day demand forecast report with replenishment guidance",
          prompt: isVi
            ? "Lập báo cáo dự báo nhu cầu 14 ngày kèm hướng dẫn nhập hàng"
            : "Draft an executive 14-day demand forecast report with replenishment guidance",
          isPrimary: true,
        },
        {
          label: isVi
            ? "Phân tích các mặt hàng có nguy cơ đứt hàng và số ngày tồn kho"
            : "Analyze items with critical stockout risks and days of supply",
          prompt: isVi
            ? "Phân tích các mặt hàng có nguy cơ đứt hàng và số ngày tồn kho"
            : "Analyze items with critical stockout risks and days of supply",
          isPrimary: false,
        },
      ];

  return (
    <div className="chat-composer-wrapper">
      {/* {showSwitchToVi && (
        <AssistantInquiryCard
          type="language_suggest"
          title="Ngôn ngữ phản hồi"
          description="Phát hiện câu hỏi bằng Tiếng Việt. Bạn muốn đổi ngôn ngữ trả lời sang Tiếng Việt hay giữ nguyên Tiếng Anh?"
          actions={[
            {
              label: "Đổi sang Tiếng Việt",
              variant: "primary",
              onClick: () => {
                onSelectLanguage?.("vi");
                setDismissedLang("vi");
              },
            },
            {
              label: "Giữ EN & Không nhắc lại",
              variant: "secondary",
              onClick: () => {
                setIgnoreLangMismatch(true);
                setDismissedLang("vi");
              },
            },
          ]}
          onDismiss={() => setDismissedLang("vi")}
        />
      )}
      {showSwitchToEn && (
        <AssistantInquiryCard
          type="language_suggest"
          title="Response Language"
          description="Detected English question. Would you like the assistant to respond in English or keep Vietnamese?"
          actions={[
            {
              label: "Switch to English",
              variant: "primary",
              onClick: () => {
                onSelectLanguage?.("en");
                setDismissedLang("en");
              },
            },
            {
              label: "Keep VI & Don't ask again",
              variant: "secondary",
              onClick: () => {
                setIgnoreLangMismatch(true);
                setDismissedLang("en");
              },
            },
          ]}
          onDismiss={() => setDismissedLang("en")}
        />
      )} */}
      {forecastState && forecastState !== "completed" && forecastState !== "loading" && (
        <AssistantInquiryCard
          type="run_forecast"
          title={language === "vi" ? "Chưa có dữ liệu dự báo" : "Forecast Required"}
          description={
            language === "vi"
              ? "Hệ thống chưa chạy phiên dự báo nào. Khởi chạy dự báo ngay để trợ lý có đầy đủ số liệu phân tích SKU và rủi ro tồn kho."
              : "No demand forecast run has been executed yet. Run a forecast to generate demand numbers and risk insights."
          }
          actions={[
            {
              label: language === "vi" ? "Khởi chạy Dự báo ngay (Run Forecast)" : "Run Forecast Now",
              icon: <PlayIcon size={12} />,
              variant: "primary",
              onClick: () => onRunForecast?.(),
            },
          ]}
        />
      )}
      {forecastState === "loading" && (
        <AssistantInquiryCard
          type="run_forecast"
          icon={<ClockIcon size={18} />}
          title={language === "vi" ? "Đang xử lý dự báo nhu cầu..." : "Forecast In Progress..."}
          description={
            language === "vi"
              ? "Hệ thống đang tính toán dự báo 14 ngày cho toàn bộ danh mục sản phẩm. Quá trình này sẽ hoàn tất trong giây lát."
              : "14-day demand forecast is currently processing across all portfolio items. This will complete shortly."
          }
          actions={[]}
        />
      )}

      {isNewSession && !isGenerating && !showSlashSuggest && suggestionBubbles.length > 0 && (
        <div className="chat-composer-suggestions">
          <div className="chat-suggestions-header">
            <Sparkle size={12} className="chat-suggestions-sparkle" />
            <span>{isVi ? "Gợi ý nhanh" : "Suggested inquiries"}</span>
          </div>
          <div className="chat-suggestions-bubbles">
            {suggestionBubbles.map((item, idx) => (
              <button
                key={idx}
                type="button"
                className={`chat-suggestion-bubble ${item.isPrimary ? "is-primary" : ""}`}
                onClick={() => {
                  if (!isGenerating) {
                    onSend(item.prompt);
                  }
                }}
                title={item.prompt}
              >
                <span className="chat-suggestion-text">{item.label}</span>
                <span className="chat-suggestion-arrow" aria-hidden="true">↗</span>
              </button>
            ))}
          </div>
        </div>
      )}

      <form onSubmit={handleSubmit} className="chat-composer">
        {/* Slash Command / Warehouse Autocomplete Suggestion Popup */}
        {showSlashSuggest && (
          <div className="slash-suggest-popup" role="listbox" aria-label="Command suggestions">
            <div className="slash-suggest-header">
              {isWarehouseMode ? (
                <>
                  <PackageIcon size={13} />
                  <span>Warehouses</span>
                </>
              ) : (
                <>
                  <CommandIcon size={12} />
                  <span>Available Commands</span>
                </>
              )}
            </div>
            <div className="slash-suggest-list">
              {isWarehouseMode ? (
                filteredWarehouses.map((wh, idx) => {
                  const isPdfExpanded = expandedPdfWhId === wh.id;
                  return (
                    <div
                      key={wh.id}
                      role="option"
                      aria-selected={activeSuggestIdx === idx}
                      className={`slash-suggest-item is-warehouse ${activeSuggestIdx === idx ? "is-active" : ""} ${isPdfExpanded ? "is-expanded" : ""}`}
                      onClick={() => handleSelectWarehouse(wh, "insert")}
                      onMouseEnter={() => setSuggestIdx(idx)}
                    >
                      <div className="wh-row-main">
                        <span className="slash-suggest-cmd">{wh.name}</span>
                        <div className="wh-quick-actions" onClick={(e) => e.stopPropagation()}>
                          <button
                            type="button"
                            className={`wh-quick-btn is-pdf ${isPdfExpanded ? "is-active" : ""}`}
                            title={`Choose PDF report focus mode for ${wh.name}`}
                            onClick={(e) => {
                              e.stopPropagation();
                              setExpandedPdfWhId(isPdfExpanded ? null : wh.id);
                            }}
                          >
                            <span style={{ display: "inline-flex", alignItems: "center", gap: 3 }}>
                              <FileTextIcon size={12} /> PDF
                            </span>
                            <span className="wh-pdf-caret">{isPdfExpanded ? "▴" : "▾"}</span>
                          </button>
                          <button
                            type="button"
                            className="wh-quick-btn is-csv"
                            title={`Generate CSV replenishment export prompt for ${wh.name}`}
                            onClick={(e) => {
                              e.stopPropagation();
                              handleSelectWarehouse(wh, "csv");
                            }}
                          >
                            <span style={{ display: "inline-flex", alignItems: "center", gap: 3 }}>
                              <PackageIcon size={12} /> CSV
                            </span>
                          </button>
                        </div>
                      </div>

                      {/* Expandable Multi-Mode PDF Drawer */}
                      {isPdfExpanded && (
                        <div className="wh-pdf-modes-drawer" onClick={(e) => e.stopPropagation()}>
                          <div className="wh-pdf-drawer-header">
                            <span className="wh-pdf-drawer-title">Choose Report Focus:</span>
                            <span className="wh-pdf-drawer-target">{wh.name}</span>
                          </div>
                          <div className="wh-pdf-drawer-grid">
                            {PDF_REPORT_MODES.map((mode) => (
                              <button
                                key={mode.id}
                                type="button"
                                className={`wh-pdf-mode-pill is-${mode.id}`}
                                title={`Generate PDF report on ${mode.label} for ${wh.name}`}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleSelectWarehousePdfMode(wh, mode);
                                }}
                              >
                                <span className="wh-pdf-pill-icon">{mode.icon}</span>
                                <span className="wh-pdf-pill-label">{mode.label}</span>
                              </button>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })
              ) : (
                filteredCommands.map((cmd, idx) => (
                  <button
                    key={cmd.cmd}
                    type="button"
                    role="option"
                    aria-selected={activeSuggestIdx === idx}
                    className={`slash-suggest-item ${activeSuggestIdx === idx ? "is-active" : ""}`}
                    onClick={() => handleSelectCommand(cmd)}
                    onMouseEnter={() => setSuggestIdx(idx)}
                  >
                    <span className="slash-suggest-cmd">{cmd.cmd}</span>
                    <div className="slash-suggest-text">
                      <span className="slash-suggest-label">
                        {cmd.label}
                        {cmd.argsHint && <span className="slash-suggest-hint"> {cmd.argsHint}</span>}
                      </span>
                      <span className="slash-suggest-desc">{cmd.desc}</span>
                    </div>
                  </button>
                ))
              )}
            </div>
          </div>
        )}

        <label htmlFor="chat-input" className="sr-only">
          Ask about your forecast
        </label>
        <textarea
          ref={inputRef}
          id="chat-input"
          rows={2}
          maxLength={4000}
          placeholder={isGenerating ? "Thinking..." : "Ask about your forecast or type / for commands…"}
          value={draft}
          onChange={(e) => handleDraftChange(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={isGenerating}
        />
        <div className="composer-actions">
          <div className="composer-actions-left" ref={menuRef}>
            <button
              type="button"
              className={`composer-plus-btn ${isMenuOpen ? "is-active" : ""}`}
              onClick={() => setIsMenuOpen((prev) => !prev)}
              aria-label="Prompt and command options"
              title="Prompt and command options"
              aria-expanded={isMenuOpen}
              disabled={isGenerating}
            >
              <PlusIcon size={15} />
            </button>
            {isMenuOpen && (
              <div className="composer-menu" role="menu">
                <div className="composer-menu-tabs">
                  <button
                    type="button"
                    className={`composer-menu-tab-btn ${menuTab === "prompts" ? "is-active" : ""}`}
                    onClick={() => setMenuTab("prompts")}
                  >
                    Prompts
                  </button>
                  <button
                    type="button"
                    className={`composer-menu-tab-btn ${menuTab === "commands" ? "is-active" : ""}`}
                    onClick={() => setMenuTab("commands")}
                  >
                    Commands
                  </button>
                </div>

                {menuTab === "prompts" ? (
                  <div className="composer-menu-list">
                    {PROMPT_OPTIONS.map((opt) => {
                      const Icon = opt.icon;
                      return (
                        <button
                          key={opt.label}
                          type="button"
                          role="menuitem"
                          className="composer-menu-item"
                          onClick={() => handleSelectOption(opt.prompt)}
                        >
                          <span className="composer-menu-icon" aria-hidden="true">
                            <Icon size={15} />
                          </span>
                          <div className="composer-menu-item-text">
                            <span className="composer-menu-label">{opt.label}</span>
                            <span className="composer-menu-desc">{opt.desc}</span>
                          </div>
                        </button>
                      );
                    })}
                  </div>
                ) : (
                  <div className="composer-menu-list">
                    {COMMAND_OPTIONS.map((cmd) => (
                      <button
                        key={cmd.cmd}
                        type="button"
                        role="menuitem"
                        className="composer-menu-item composer-menu-cmd-item"
                        onClick={() => handleSelectCommand(cmd)}
                      >
                        <span className="composer-cmd-badge">{cmd.cmd}</span>
                        <div className="composer-menu-item-text">
                          <span className="composer-menu-label">
                            {cmd.label}
                            {cmd.argsHint && <span className="composer-cmd-hint"> {cmd.argsHint}</span>}
                          </span>
                          <span className="composer-menu-desc">{cmd.desc}</span>
                        </div>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}



            {isOffline && (
              <button
                type="button"
                className="composer-reconnect-btn"
                onClick={() => {
                  setIsOffline(false);
                  setRetryTrigger((prev) => prev + 1);
                }}
                title="Backend offline after 5 attempts. Click to reconnect"
              >
                Reconnect ↻
              </button>
            )}
          </div>

          <div className="composer-actions-right">


            {isGenerating ? (
              <button
                type="button"
                className="chat-stop-btn"
                onClick={onStopGeneration}
                aria-label="Stop response"
                title="Stop response"
              >
                <span className="stop-square" />
              </button>
            ) : (
              <button
                type="submit"
                id="chat-send-btn"
                className="chat-send-btn"
                disabled={!draft.trim()}
                aria-label="Send message"
                suppressHydrationWarning
              >
                <SendIcon size={16} />
              </button>
            )}
          </div>
        </div>
      </form>
    </div>
  );
}
