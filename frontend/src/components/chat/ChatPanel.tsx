"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import type { ChatMessage, ContextInfo } from "@/types/chat";
import { Sparkle, AiChatIcon, CloseIcon, NewChatIcon } from "../common/Icons";
import ChatMessages from "./ChatMessages";
import ChatComposer from "./ChatComposer";

interface ChatPanelProps {
  open: boolean;
  onToggle: () => void;
  onClose: () => void;
  messages: ChatMessage[];
  draft: string;
  onChangeDraft: (text: string) => void;
  onSend: (text?: string) => void;
  onNewConversation?: () => void;
  contextInfo?: ContextInfo;
  isGenerating?: boolean;
  selectedModel?: string;
  onSelectModel?: (model: string) => void;
  language?: "en" | "vi";
  onSelectLanguage?: (lang: "en" | "vi") => void;
  forecastState?: import("@/types/forecast").ForecastState;
  onRunForecast?: () => void;
  onStopGeneration?: () => void;
  onClarificationAction?: (actionType: string, payload?: string, clarification?: import("@/types/chat").ClarificationPrompt) => void;
  selectedItem?: import("@/types/forecast").ForecastedItem | null;
}

export default function ChatPanel({
  open,
  onToggle,
  onClose,
  messages,
  draft,
  onChangeDraft,
  onSend,
  onNewConversation,
  contextInfo,
  isGenerating = false,
  selectedModel,
  onSelectModel,
  language = "en",
  onSelectLanguage,
  forecastState,
  onRunForecast,
  onStopGeneration,
  onClarificationAction,
  selectedItem,
}: ChatPanelProps) {
  const panelRef = useRef<HTMLElement>(null);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const [panelWidth, setPanelWidth] = useState<number>(340);
  const [isResizing, setIsResizing] = useState<boolean>(false);

  const handleClose = useCallback(() => {
    onClose();
    toggleRef.current?.focus();
  }, [onClose]);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    setIsResizing(true);
    document.body.classList.add("is-resizing");

    const onMouseMove = (moveEvent: MouseEvent) => {
      const maxW = Math.max(340, Math.floor(window.innerWidth * 0.35));
      const minW = 340;
      const computedW = Math.min(maxW, Math.max(minW, window.innerWidth - moveEvent.clientX));
      setPanelWidth(computedW);
      document.documentElement.style.setProperty("--chat-panel-width", `${computedW}px`);
    };

    const onMouseUp = () => {
      setIsResizing(false);
      document.body.classList.remove("is-resizing");
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
    };

    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
  }, []);

  const prevOpenRef = useRef(open);
  useEffect(() => {
    if (open && !prevOpenRef.current) {
      inputRef.current?.focus({ preventScroll: true });
    }
    prevOpenRef.current = open;
  }, [open]);

  useEffect(() => {
    if (!open) return;

    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        handleClose();
      }

      if (
        event.key === "Tab" &&
        window.matchMedia("(max-width: 767px)").matches
      ) {
        const controls = panelRef.current?.querySelectorAll<HTMLElement>(
          "button:not(:disabled), textarea, a[href]"
        );
        if (!controls?.length) return;
        const first = controls[0];
        const last = controls[controls.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    }

    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, handleClose]);

  return (
    <>
      {open && (
        <div
          className="chat-backdrop"
          onClick={handleClose}
          aria-hidden="true"
        />
      )}

      <div className="chat-slot">
        {/* Scalable Width Drag Handle & Indicator */}
        {open && (
          <div
            className={`chat-resize-handle ${isResizing ? "is-active" : ""}`}
            onMouseDown={handleMouseDown}
            title="Drag left to expand chat (Min 340px, Max 35vw)"
            aria-label="Scale chat width"
            role="separator"
            aria-orientation="vertical"
          >
            <div className="chat-resize-indicator" />
            <div className="chat-scale-badge">
              <span>◀ Scale out</span>
              <span style={{ color: "#93c5fd" }}>({panelWidth}px / Max 25vw)</span>
            </div>
          </div>
        )}

        <button
          ref={toggleRef}
          type="button"
          className={`chat-toggle ${open ? "is-open" : ""}`}
          onClick={onToggle}
          aria-expanded={open}
          aria-controls="demand-chat"
          aria-label={open ? "Collapse AI Assistant" : "Open DemandAI Assistant"}
          title={open ? "Collapse AI Assistant" : "Open DemandAI Assistant"}
        >
          {open ? (
            <CloseIcon size={18} />
          ) : (
            <>
              <AiChatIcon size={24} />
              <span className="chat-toggle-pulse" aria-hidden="true" />
            </>
          )}
        </button>

        <aside
          ref={panelRef}
          id="demand-chat"
          className="chat-panel"
          inert={!open}
          aria-hidden={!open}
          aria-label="DemandAI assistant"
        >
          <div className="chat-header">
            <span className="assistant-symbol">
              <Sparkle size={16} />
            </span>
            <div className="chat-header-title">
              <h2>DemandAI assistant</h2>
            </div>
            <div className="chat-header-actions">
              {/* <button
                type="button"
                className="chat-lang-toggle-btn"
                onClick={() => onSelectLanguage?.(language === "en" ? "vi" : "en")}
                title={language === "vi" ? "Đổi ngôn ngữ phản hồi của Trợ lý AI (Hiện tại: Tiếng Việt)" : "Switch Assistant response language (Current: English)"}
                aria-label={`Toggle Assistant response language: ${language.toUpperCase()}`}
              >
                <span className={`chat-lang-opt ${language === "en" ? "is-active" : ""}`}>EN</span>
                <span className="chat-lang-divider">/</span>
                <span className={`chat-lang-opt ${language === "vi" ? "is-active" : ""}`}>VI</span>
              </button> */}
              {onNewConversation && (
                <button
                  type="button"
                  className="chat-header-btn"
                  onClick={onNewConversation}
                  title="New conversation"
                  aria-label="New conversation"
                >
                  <NewChatIcon size={15} />
                </button>
              )}
            </div>
          </div>

          <ChatMessages
            messages={messages}
            open={open}
            language={language}
            isGenerating={isGenerating}
            onSelectSuggestion={(text) => onSend(text)}
            onClarificationAction={onClarificationAction}
          />

          <ChatComposer
            inputRef={inputRef}
            draft={draft}
            onChangeDraft={onChangeDraft}
            onSend={onSend}
            contextInfo={contextInfo}
            isGenerating={isGenerating}
            selectedModel={selectedModel}
            onSelectModel={onSelectModel}
            language={language}
            onSelectLanguage={onSelectLanguage}
            forecastState={forecastState}
            onRunForecast={onRunForecast}
            onStopGeneration={onStopGeneration}
            selectedItem={selectedItem}
            messages={messages}
          />
        </aside>
      </div>
    </>
  );
}
