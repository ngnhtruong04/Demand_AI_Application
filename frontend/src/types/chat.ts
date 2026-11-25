export type ChatRole = "assistant" | "user";

export interface AgentStep {
  id?: string;
  type: "think" | "tool";
  content?: string;
  toolName?: string;
}

export interface ClarificationOption {
  label: string;
  actionType:
    | "send_text"
    | "run_forecast"
    | "run_shap"
    | "switch_language"
    | "accept_select_item"
    | "deny_select_item"
    | "accept_run_shap"
    | "deny_run_shap"
    | "select_sku"
    | "view_item_on_screen";
  payload?: string;
  primary?: boolean;
}

export interface ClarificationPrompt {
  type: "language_suggest" | "run_forecast" | "clarify_intent" | "run_shap" | "custom";
  title?: string;
  description: string;
  targetSku?: string;
  sku?: string;
  originalQuery?: string;
  productName?: string;
  options: ClarificationOption[];
  allowTextInput?: boolean;
  textPlaceholder?: string;
}

export interface ChatMessage {
  role: ChatRole;
  text: string;
  isThinking?: boolean;
  activeTool?: string;
  toolsUsed?: string[];
  steps?: AgentStep[];
  model?: string;
  durationSeconds?: number;
  clarification?: ClarificationPrompt;
}

export interface ContextInfo {
  usedTokens: number;
  maxTokens: number;
  compacted?: boolean;
  model?: string;
}

