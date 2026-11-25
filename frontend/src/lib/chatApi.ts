import { getApiBaseUrl } from "./api";
import type { AgentStep, ChatMessage, ContextInfo, ClarificationPrompt } from "@/types/chat";

export interface ChatApiResult {
  reply: string;
  contextInfo: ContextInfo;
}

export interface StreamCallbacks {
  onToken: (token: string) => void;
  onStep?: (step: AgentStep) => void;
  onToolStart?: (toolName: string) => void;
  onFallbackType?: (fallbackType: string) => void;
  onSelectSku?: (sku: string) => void;
  onModelActive?: (modelName: string) => void;
  onClarification?: (data?: ClarificationPrompt) => void;
  onShapCompleted?: (itemId: string, sku: string) => void;
  onDone?: (usedTokens: number) => void;
  onError?: (errorMessage: string) => void;
}

const DEFAULT_MODEL = "gpt-6-luna";

export interface ModelInfo { name: string; description: string; }

export async function fetchAvailableModels(): Promise<{ defaultModel: string; models: ModelInfo[]; bootId?: string }> {
  try {
    const res = await fetch(`${getApiBaseUrl()}/api/v1/chat/models`);
    if (res.ok) {
      const data = await res.json();
      return {
        defaultModel: data.default || DEFAULT_MODEL,
        models: Array.isArray(data.models) ? data.models : [],
        bootId: data.boot_id,
      };
    }
  } catch {}
  return { defaultModel: DEFAULT_MODEL, models: [] };
}

export async function sendChatStream(
  messages: ChatMessage[],
  callbacks: StreamCallbacks,
  model: string = DEFAULT_MODEL,
  selectedItemId?: string,
  signal?: AbortSignal,
  language: string = "en",
  sessionId?: string
): Promise<void> {
  const baseUrl = getApiBaseUrl();
  const url = `${baseUrl}/api/v1/chat/stream`;

  const res = await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      messages: messages.map((m) => ({
        role: m.role,
        text: m.text,
      })),
      model,
      selected_item_id: selectedItemId || null,
      session_id: sessionId || null,
      stream: true,
      language,
    }),
    signal,
  });

  if (!res.ok || !res.body) {
    throw new Error(`Streaming failed with status ${res.status}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  const processLine = (rawLine: string) => {
    const line = rawLine.trim();
    if (!line || !line.startsWith("data: ")) return;

    try {
      const payload = JSON.parse(line.slice(6).trim());
      if (payload.type === "token" && typeof payload.content === "string") {
        callbacks.onToken(payload.content);
      } else if (payload.type === "step") {
        callbacks.onStep?.({
          type: payload.step_type === "think" ? "think" : "tool",
          content: payload.content,
          toolName: payload.name,
        });
      } else if (payload.type === "tool_start" && typeof payload.name === "string") {
        callbacks.onToolStart?.(payload.name);
      } else if (payload.type === "fallback_type" && typeof payload.fallback === "string") {
        callbacks.onFallbackType?.(payload.fallback);
      } else if (payload.type === "select_sku" && typeof payload.sku === "string") {
        callbacks.onSelectSku?.(payload.sku);
      } else if (payload.type === "model_active" && typeof payload.model === "string") {
        callbacks.onModelActive?.(payload.model);
      } else if (payload.type === "clarification" && payload.data) {
        callbacks.onClarification?.(payload.data);
      } else if (payload.type === "clear_clarification") {
        callbacks.onClarification?.(undefined);
      } else if (payload.type === "shap_completed" && payload.item_id) {
        callbacks.onShapCompleted?.(String(payload.item_id), String(payload.sku || ""));
      } else if (payload.type === "done") {
        callbacks.onDone?.(typeof payload.used_tokens === "number" ? payload.used_tokens : 0);
      } else if (payload.type === "error" && typeof payload.message === "string") {
        callbacks.onError?.(payload.message);
      }
    } catch {
      // Skip malformed individual event line
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    // Keep the remainder in buffer
    buffer = lines.pop() || "";

    for (const rawLine of lines) {
      processLine(rawLine);
    }
  }

  // Flush any final event remaining in buffer without trailing newline
  if (buffer.trim()) {
    const remaining = buffer.split("\n");
    for (const rawLine of remaining) {
      processLine(rawLine);
    }
  }
}

export async function sendChatMessage(
  messages: ChatMessage[],
  model: string = DEFAULT_MODEL,
  selectedItemId?: string,
  language: string = "en",
  sessionId?: string
): Promise<ChatApiResult> {
  const baseUrl = getApiBaseUrl();
  const url = `${baseUrl}/api/v1/chat/message`;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 45000);

  try {
    const res = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        messages: messages.map((m) => ({
          role: m.role,
          text: m.text,
        })),
        model,
        selected_item_id: selectedItemId || null,
        session_id: sessionId || null,
        stream: false,
        language,
      }),
      signal: controller.signal,
    });

    if (!res.ok) {
      throw new Error(`Chat API responded with status ${res.status}`);
    }

    const data = await res.json();
    return {
      reply: data.reply,
      contextInfo: {
        usedTokens: data.used_tokens,
        maxTokens: data.context_size,
        compacted: data.compacted,
        model: data.model,
      },
    };
  } finally {
    clearTimeout(timer);
  }
}
