"use client";

import React, { useState, useRef } from "react";
import { TargetIcon, GlobeIcon, ZapIcon, BrainIcon, CloseIcon, CheckIcon } from "../common/Icons";

export interface InquiryAction {
  id?: string;
  label: string;
  sublabel?: string;
  badge?: string;
  description?: string;
  variant?: "primary" | "secondary" | "outline";
  icon?: React.ReactNode;
  actionType?: string;
  payload?: string;
  onClick: () => void;
}

export type ClarificationAction = InquiryAction;

export interface AssistantInquiryCardProps {
  type?: "language_suggest" | "run_forecast" | "clarify_intent" | "run_shap" | "custom";
  icon?: React.ReactNode;
  title?: React.ReactNode;
  description: React.ReactNode;
  actions?: InquiryAction[];
  allowTextInput?: boolean;
  textPlaceholder?: string;
  onSubmitText?: (text: string) => void;
  onDismiss?: () => void;
  className?: string;
}

export type AssistantClarificationCardProps = AssistantInquiryCardProps;

function renderInlineText(content: React.ReactNode): React.ReactNode {
  if (typeof content !== "string" || !content) return content;
  const parts = content.split(/(`[^`]+`|\*\*[^*]+\*\*|\*[^*]+\*|\[[^\]]+\]\([^\)]+\))/g);
  if (parts.length === 1) return content;

  return parts.map((part, idx) => {
    if (!part) return null;
    if (part.startsWith("**") && part.endsWith("**") && part.length >= 4) {
      return (
        <strong key={idx} className="clarification-bold">
          {part.slice(2, -2)}
        </strong>
      );
    }
    if (part.startsWith("*") && part.endsWith("*") && part.length >= 2) {
      return <em key={idx}>{part.slice(1, -1)}</em>;
    }
    if (part.startsWith("`") && part.endsWith("`") && part.length >= 2) {
      return (
        <code key={idx} className="clarification-code">
          {part.slice(1, -1)}
        </code>
      );
    }
    if (part.startsWith("[") && part.includes("](") && part.endsWith(")")) {
      const closeBracket = part.indexOf("](");
      const label = part.slice(1, closeBracket).trim();
      const rawUrl = part.slice(closeBracket + 2, -1);
      return (
        <a key={idx} href={rawUrl} target="_blank" rel="noopener noreferrer" className="clarification-link">
          {label}
        </a>
      );
    }
    return part;
  });
}

export default function AssistantInquiryCard({
  type = "custom",
  icon,
  title,
  description,
  actions = [],
  allowTextInput = false,
  textPlaceholder,
  onSubmitText,
  onDismiss,
  className = "",
}: AssistantInquiryCardProps) {
  const [customText, setCustomText] = useState("");
  const [clickedIdx, setClickedIdx] = useState<number | null>(null);
  const [isAnswered, setIsAnswered] = useState<boolean>(false);
  const [showInput, setShowInput] = useState<boolean>(allowTextInput);
  const inputRef = useRef<HTMLInputElement | null>(null);

  const defaultIcon =
    icon ||
    (type === "language_suggest" ? (
      <GlobeIcon size={18} />
    ) : type === "run_forecast" ? (
      <ZapIcon size={18} />
    ) : type === "run_shap" ? (
      <BrainIcon size={18} />
    ) : (
      <TargetIcon size={18} />
    ));

  function handleActionClick(act: InquiryAction, idx: number) {
    if (isAnswered || clickedIdx !== null) return; // Permanently prevent spam clicks
    const isCustomAction =
      act.actionType === "custom_input" ||
      act.actionType === "show_input" ||
      /different percentage|mức.*khác|khác\.\.\./i.test(act.label);
    if (isCustomAction) {
      setShowInput(true);
      setClickedIdx(idx);
      setTimeout(() => inputRef.current?.focus(), 50);
      return;
    }
    setIsAnswered(true);
    setClickedIdx(idx);
    act.onClick();
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (customText.trim() && onSubmitText && !isAnswered) {
      setIsAnswered(true);
      setClickedIdx(-1);
      onSubmitText(customText.trim());
      setCustomText("");
    }
  }

  return (
    <div className={`clarification-card clarification-${type} ${className}`} role="region" aria-label={typeof title === "string" ? title : "Assistant inquiry"}>
      <div className="clarification-header">
        <div className="clarification-title-wrap">
          <span className="clarification-icon" aria-hidden="true">{defaultIcon}</span>
          {title && <span className="clarification-title">{renderInlineText(title)}</span>}
        </div>
        {onDismiss && (
          <button
            type="button"
            className="clarification-dismiss"
            onClick={onDismiss}
            aria-label="Dismiss inquiry"
          >
            <CloseIcon size={14} />
          </button>
        )}
      </div>

      <p className="clarification-description">{renderInlineText(description)}</p>

      {actions.length > 0 && (
        <div className="clarification-actions-grid">
          {actions.map((act, idx) => (
            <button
              key={idx}
              type="button"
              disabled={isAnswered}
              className={`clarification-btn clarification-btn-${act.variant || "secondary"} ${clickedIdx === idx ? "is-active-click" : ""}`}
              onClick={() => handleActionClick(act, idx)}
            >
              {act.icon && <span className="btn-icon" style={{ flexShrink: 0 }}>{act.icon}</span>}
              <span className="btn-label" style={{ flex: 1, minWidth: 0, wordBreak: "break-word", display: "flex", flexDirection: "column", gap: 2 }}>
                <span style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 6, width: "100%" }}>
                  <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                    {clickedIdx === idx ? (
                      <>
                        <CheckIcon size={13} />
                        <span>{act.label}</span>
                      </>
                    ) : (
                      renderInlineText(act.label)
                    )}
                  </span>
                  {act.badge && <span className="clarification-badge">{act.badge}</span>}
                </span>
                {act.sublabel && (
                  <span className="clarification-sublabel">
                    {renderInlineText(act.sublabel)}
                  </span>
                )}
              </span>
            </button>
          ))}
        </div>
      )}

      {(showInput || allowTextInput) && onSubmitText && (
        <form className="clarification-text-form" onSubmit={handleSubmit}>
          <input
            ref={inputRef}
            type="text"
            className="clarification-input"
            value={customText}
            onChange={(e) => setCustomText(e.target.value)}
            placeholder={textPlaceholder || "Enter a different percentage (e.g. -15%, +10%)..."}
            disabled={isAnswered}
          />
          <button
            type="submit"
            className="clarification-submit-btn"
            disabled={!customText.trim() || isAnswered}
          >
            {/percent|tiếng anh|en/i.test(textPlaceholder || "") ? "Send" : "Gửi"}
          </button>
        </form>
      )}
    </div>
  );
}

export const AssistantClarificationCard = AssistantInquiryCard;
