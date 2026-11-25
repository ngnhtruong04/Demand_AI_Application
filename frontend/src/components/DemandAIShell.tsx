"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import type { ChatMessage, ContextInfo } from "@/types/chat";
import type { ForecastedItem, ForecastState } from "@/types/forecast";
import { sendChatMessage, sendChatStream } from "@/lib/chatApi";
import { loadItemShap, fetchShapStatus, fetchLiveForecast, FORECAST_SESSION_KEY } from "@/lib/forecastApi";
import WorkspaceCanvas from "./workspace/WorkspaceCanvas";
import ChatPanel from "./chat/ChatPanel";
import LeftPanel from "./LeftPanel";
import DemandAIHeader, { type ForecastSessionInfo } from "./common/DemandAIHeader";
import { getApiBaseUrl } from "@/lib/api";

const INITIAL_MESSAGES: ChatMessage[] = [
  {
    role: "assistant",
    text: "Hi! I’m your DemandAI assistant. This is a preview of your forecast conversation space. What would you like to explore?",
  },
];

const FIXED_MAX_TOKENS = 250_000;

function estimateTokens(text: string): number {
  if (!text) return 0;
  // ~4 chars per token approximation for mixed EN/VI text + markdown
  return Math.max(1, Math.ceil(text.length / 4));
}

function calculateConversationTokens(msgs: ChatMessage[]): number {
  return msgs.reduce((sum, m) => sum + estimateTokens(m.text), 0);
}

const INITIAL_CONTEXT: ContextInfo = {
  usedTokens: calculateConversationTokens(INITIAL_MESSAGES),
  maxTokens: FIXED_MAX_TOKENS,
  model: "inclusionai/ling-3.0-flash-vl:free",
};

const SESSION_TTL_MS = 60 * 60 * 1000; // 60 minutes inactivity TTL

export default function DemandAIShell() {
  const [open, setOpen] = useState<boolean>(false);
  const [leftOpen, setLeftOpen] = useState<boolean>(false);
  const [selectedItem, setSelectedItem] = useState<ForecastedItem | null>(null);
  const [draft, setDraft] = useState<string>("");
  const [messages, setMessages] = useState<ChatMessage[]>(INITIAL_MESSAGES);
  const [contextInfo, setContextInfo] = useState<ContextInfo>(INITIAL_CONTEXT);
  const [isGenerating, setIsGenerating] = useState<boolean>(false);
  const [selectedModel, setSelectedModel] = useState<string>("gpt-6-luna");
  const [language, setLanguage] = useState<"en" | "vi">("en");

  // Manage state and data for the Forecast model
  const [forecastState, setForecastState] = useState<ForecastState>("idle");
  const [forecastItems, setForecastItems] = useState<ForecastedItem[]>([]);

  // Session system (cache UUID, 15-min inactivity expiry, rerun expiry)
  const [session, setSession] = useState<ForecastSessionInfo | null>(null);
  const [isRestoringSession, setIsRestoringSession] = useState<boolean>(false);
  const [restoreProgress, setRestoreProgress] = useState<string>("Restoring saved session items...");
  const lastActiveRef = useRef<number>(Date.now());
  const restoreAbortRef = useRef<AbortController | null>(null);

  // Restore session from storage on client mount (avoids SSR hydration mismatch)
  useEffect(() => {
    try {
      const raw =
        sessionStorage.getItem("demandai.cache_session") ||
        localStorage.getItem("demandai.cache_session");
      if (raw) {
        const parsed = JSON.parse(raw);
        const elapsed = Date.now() - (parsed.lastActive || 0);
        const isExpired = elapsed > SESSION_TTL_MS;
        if (!isExpired && parsed.id) {
          const now = Date.now();
          lastActiveRef.current = now;
          const restoredSession: ForecastSessionInfo = {
            id: parsed.id,
            isExpired: false,
            lastActive: now,
          };
          // eslint-disable-next-line react-hooks/set-state-in-effect
          setSession(restoredSession);
          try {
            const payload = JSON.stringify({
              id: parsed.id,
              lastActive: now,
              selectedItemId: parsed.selectedItemId,
            });
            sessionStorage.setItem("demandai.cache_session", payload);
            localStorage.setItem("demandai.cache_session", payload);
          } catch { }

          // If in-flight forecast job is already running, FORECAST_SESSION_KEY handles that.
          // Otherwise, automatically load the saved forecast results for this valid session without rerunning:
          if (!sessionStorage.getItem(FORECAST_SESSION_KEY)) {
            setIsRestoringSession(true);
            setRestoreProgress("Restoring saved forecast results...");
            const controller = new AbortController();
            restoreAbortRef.current = controller;

            fetchLiveForecast(
              undefined,
              controller.signal,
              (loaded, total) => {
                setRestoreProgress(
                  `Loading forecast results: ${loaded.toLocaleString()} / ${total.toLocaleString()} items...`
                );
              },
              parsed.id
            )
              .then((items) => {
                setForecastItems(items);
                setForecastState("completed");
                setIsRestoringSession(false);
                if (parsed.selectedItemId) {
                  const it = items.find(
                    (x) => String(x.id) === String(parsed.selectedItemId)
                  );
                  if (it) {
                    void handleSelectItem(it);
                  }
                }
              })
              .catch((err) => {
                if (controller.signal.aborted) return;
                const msg = String(err?.message ?? err);
                const isNetworkError = err instanceof TypeError || msg.toLowerCase().includes("networkerror") || msg.toLowerCase().includes("failed to fetch");
                if (isNetworkError) {
                  // Transient: backend not reachable. Keep session alive so user can retry.
                  console.warn("Session restore skipped — backend unreachable:", msg);
                  setIsRestoringSession(false);
                  setForecastState("idle");
                  return;
                }
                // Genuine data-not-found: wipe the stale session.
                console.warn("Failed to restore session forecast items:", err);
                setSession((prev) => (prev ? { ...prev, isExpired: true } : null));
                try {
                  sessionStorage.removeItem("demandai.cache_session");
                  localStorage.removeItem("demandai.cache_session");
                } catch { }
                setIsRestoringSession(false);
                setForecastState("idle");
              });
          }
        } else {
          setSession({ id: parsed.id, isExpired: true, lastActive: parsed.lastActive });
          try {
            sessionStorage.removeItem("demandai.cache_session");
            localStorage.removeItem("demandai.cache_session");
          } catch { }
        }
      }
    } catch { }
  }, []);

  // Race-condition guard & memory cache for rapid item switching
  const detailAbortRef = useRef<AbortController | null>(null);
  const chatAbortRef = useRef<AbortController | null>(null);
  const debounceTimerRef = useRef<NodeJS.Timeout | null>(null);
  useEffect(() => () => {
    detailAbortRef.current?.abort();
    chatAbortRef.current?.abort();
    restoreAbortRef.current?.abort();
    if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
  }, []);
  const activeFetchIdRef = useRef<string | null>(null);
  const itemCacheRef = useRef<Map<string, ForecastedItem>>(new Map());

  useEffect(() => {
    if (sessionStorage.getItem(FORECAST_SESSION_KEY)) {
      queueMicrotask(() => setForecastState("loading"));
    }
  }, []);

  // Activity tracking and 5-minute inactivity watchdog
  useEffect(() => {
    const onUserActivity = () => {
      lastActiveRef.current = Date.now();
      if (session && !session.isExpired) {
        try {
          const payload = JSON.stringify({
            id: session.id,
            lastActive: Date.now(),
            selectedItemId: selectedItem?.id,
          });
          sessionStorage.setItem("demandai.cache_session", payload);
          localStorage.setItem("demandai.cache_session", payload);
        } catch { }
      }
    };

    const throttledActivity = () => {
      if (Date.now() - lastActiveRef.current > 4000) {
        onUserActivity();
      }
    };

    const events = ["mousedown", "keydown", "scroll", "touchstart"];
    events.forEach((ev) => window.addEventListener(ev, throttledActivity, { passive: true }));
    return () => {
      events.forEach((ev) => window.removeEventListener(ev, throttledActivity));
    };
  }, [session, selectedItem]);

  // Activity tracking and 15-minute inactivity watchdog with auto-reload
  useEffect(() => {
    if (!session || session.isExpired) return;

    let isExpiring = false;
    const triggerSessionExpiry = () => {
      if (isExpiring) return;
      isExpiring = true;
      try {
        sessionStorage.removeItem("demandai.cache_session");
        localStorage.removeItem("demandai.cache_session");
        sessionStorage.removeItem(FORECAST_SESSION_KEY);
      } catch { }
      setSession((prev) => (prev ? { ...prev, isExpired: true } : null));

      // Notify backend to prune expired session local files, then auto-reload page
      fetch(`${getApiBaseUrl()}/api/v1/forecast/sessions/expire`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: session.id }),
      })
        .catch(() => { })
        .finally(() => {
          window.location.reload();
        });
    };

    const checkInterval = setInterval(() => {
      if (Date.now() - lastActiveRef.current >= SESSION_TTL_MS) {
        triggerSessionExpiry();
      }
    }, 60_000); // check every 1 minute

    const onVisibilityOrFocus = () => {
      if (Date.now() - lastActiveRef.current >= SESSION_TTL_MS) {
        triggerSessionExpiry();
      }
    };

    document.addEventListener("visibilitychange", onVisibilityOrFocus);
    window.addEventListener("focus", onVisibilityOrFocus);

    return () => {
      clearInterval(checkInterval);
      document.removeEventListener("visibilitychange", onVisibilityOrFocus);
      window.removeEventListener("focus", onVisibilityOrFocus);
    };
  }, [session]);

  useEffect(() => {
    if (!session && forecastItems.length > 0 && forecastItems[0]?.run_id) {
      const cacheUuid = forecastItems[0].run_id;
      const now = Date.now();
      lastActiveRef.current = now;
      const newSession: ForecastSessionInfo = { id: cacheUuid, isExpired: false, lastActive: now };
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setSession(newSession);
      try {
        const payload = JSON.stringify({
          id: cacheUuid,
          lastActive: now,
          selectedItemId: selectedItem?.id,
        });
        sessionStorage.setItem("demandai.cache_session", payload);
        localStorage.setItem("demandai.cache_session", payload);
      } catch { }
    }
  }, [forecastItems, session, selectedItem]);

  // Continuously reconcile background SHAP queue until all queued/running items finish
  useEffect(() => {
    const hasPending = forecastItems.some(
      it => it.shap_status === "queued" || it.shap_status === "running"
    );
    if (!hasPending) return;

    const runId = forecastItems.find(it => it.run_id)?.run_id;
    if (!runId) return;

    const interval = setInterval(async () => {
      const pendingItem = forecastItems.find(
        it => it.shap_status === "running" || it.shap_status === "queued"
      );
      if (!pendingItem) return;

      try {
        const data = await fetchShapStatus(runId, pendingItem.id);
        const completedIds = [...(data.completed_item_ids || [])];
        if (data.status === "completed" && data.item_id && !completedIds.includes(data.item_id)) {
          completedIds.push(data.item_id);
        }
        const queuedIds = data.queued_item_ids || [];
        const activeId = data.active_item_id || null;

        setForecastItems(prev => prev.map(it => {
          if (it.run_id !== runId) return it;
          if (completedIds.includes(it.id)) {
            const enriched = data.item && it.id === data.item_id ? data.item : it;
            return { ...enriched, shap_status: "completed" };
          }
          if (activeId && it.id === activeId) {
            return { ...it, shap_status: "running" };
          }
          if (queuedIds.includes(it.id)) {
            return { ...it, shap_status: "queued" };
          }
          return it;
        }));
        setSelectedItem(prev => {
          if (!prev || prev.run_id !== runId) return prev;
          if (completedIds.includes(prev.id)) {
            const enriched = data.item && prev.id === data.item_id ? data.item : prev;
            return { ...enriched, shap_status: "completed" };
          }
          if (activeId && prev.id === activeId) {
            return { ...prev, shap_status: "running" };
          }
          if (queuedIds.includes(prev.id)) {
            return { ...prev, shap_status: "queued" };
          }
          return prev;
        });
      } catch {
        // silent background poll error
      }
    }, 1200);

    return () => clearInterval(interval);
  }, [forecastItems]);

  // Trigger forecast loading state (ForecastLoadingState handles the single SSE stream)
  function handleRunForecast() {
    if (forecastState === "loading") return; // Spam prevention
    restoreAbortRef.current?.abort();
    setIsRestoringSession(false);
    if (session) {
      fetch(`${getApiBaseUrl()}/api/v1/forecast/sessions/expire`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: session.id }),
      }).catch(() => { });
    }
    setSession(null);
    try {
      sessionStorage.removeItem("demandai.cache_session");
      localStorage.removeItem("demandai.cache_session");
      sessionStorage.removeItem(FORECAST_SESSION_KEY);
    } catch { }

    detailAbortRef.current?.abort();
    if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);
    setForecastItems([]);
    setSelectedItem(null);
    setLeftOpen(false);
    activeFetchIdRef.current = null;
    itemCacheRef.current.clear();
    setForecastState("loading");
  }

  function handleForecastComplete(items: ForecastedItem[]) {
    const cacheUuid = items[0]?.run_id;
    if (cacheUuid) {
      const now = Date.now();
      lastActiveRef.current = now;
      const newSession: ForecastSessionInfo = { id: cacheUuid, isExpired: false, lastActive: now };
      setSession(newSession);
      try {
        const payload = JSON.stringify({
          id: cacheUuid,
          lastActive: now,
          selectedItemId: selectedItem?.id,
        });
        sessionStorage.setItem("demandai.cache_session", payload);
        localStorage.setItem("demandai.cache_session", payload);
      } catch { }
    }
    setForecastItems(items);
    setForecastState("completed");
    handleNewConversation();
  }

  async function handleSelectItem(item: ForecastedItem, autoCalculateShap = true) {
    setLeftOpen(true);
    if (
      selectedItem?.id === item.id &&
      (selectedItem.grouped_drivers?.length ||
        selectedItem.shap_status === "running" ||
        selectedItem.shap_status === "queued" ||
        selectedItem.shap_status === "completed")
    ) {
      return; // Spam prevention
    }
    detailAbortRef.current?.abort();
    if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current);

    const key = `${item.run_id}:${item.id}`;
    activeFetchIdRef.current = key;
    const cached = itemCacheRef.current.get(key);
    const hasFullShap = (it?: ForecastedItem | null) =>
      Boolean(
        it?.daily_points &&
        it.daily_points.length > 0 &&
        it.daily_points.some((p) => p.top_positive_features && p.top_positive_features.length > 0)
      );

    if (hasFullShap(cached)) {
      setSelectedItem(cached!);
      return;
    }
    if (hasFullShap(item)) {
      setSelectedItem(item);
      return;
    }

    if (!autoCalculateShap) {
      setSelectedItem(cached || item);
      return;
    }

    // Set to queued immediately while dispatching to backend
    setSelectedItem({ ...item, shap_status: "queued", shap_error: undefined });
    setForecastItems(prev =>
      prev.map(it =>
        it.id === item.id && it.run_id === item.run_id
          ? { ...it, shap_status: "queued" }
          : it
      )
    );

    const controller = new AbortController();
    detailAbortRef.current = controller;

    debounceTimerRef.current = setTimeout(async () => {
      try {
        if (!item.run_id) throw new Error("This forecast has no run ID. Run a new forecast to calculate SHAP.");
        const enriched = await loadItemShap(item.run_id, item.id, controller.signal, (status, queuedIds, activeId, completedIds) => {
          if (controller.signal.aborted) return;
          if (activeFetchIdRef.current === key) {
            setSelectedItem(prev => (prev ? { ...prev, shap_status: status } : prev));
          }
          setForecastItems(prev => prev.map(it => {
            if (it.run_id !== item.run_id) return it;
            if (completedIds?.includes(it.id)) {
              return { ...it, shap_status: "completed" };
            }
            if (it.shap_status === "completed" || (it.grouped_drivers && it.grouped_drivers.length > 0)) {
              return it;
            }
            if (activeId && it.id === activeId) {
              return { ...it, shap_status: "running" };
            }
            if (queuedIds?.includes(it.id)) {
              return { ...it, shap_status: "queued" };
            }
            return it;
          }));
        });
        if (controller.signal.aborted) return;
        itemCacheRef.current.set(key, enriched);
        setForecastItems(prev => prev.map(it => it.id === item.id && it.run_id === item.run_id ? enriched : it));
        if (activeFetchIdRef.current === key) setSelectedItem(enriched);
      } catch (error) {
        if (controller.signal.aborted || activeFetchIdRef.current !== key) return;
        setSelectedItem({ ...item, shap_status: "failed", shap_error: error instanceof Error ? error.message : String(error) });
      }
    }, 120);
  }

  async function handleClarificationAction(
    actionType: string,
    payload?: string,
    clarification?: import("@/types/chat").ClarificationPrompt
  ) {
    const isVi = language === "vi";

    // Route TreeSHAP calculation intents to run_shap only when explicitly targeted
    let resolvedAction = actionType;
    if (
      resolvedAction !== "view_item_on_screen" &&
      resolvedAction !== "select_sku" &&
      resolvedAction !== "run_forecast" &&
      (resolvedAction === "run_shap" ||
        /calculate.*shap|tính.*toán.*shap|accept.*shap/i.test(payload || ""))
    ) {
      resolvedAction = "run_shap";
    }

    if (resolvedAction === "run_forecast") {
      handleRunForecast();
      return;
    }

    if (resolvedAction === "select_sku" && payload) {
      // Do not reuse or mutate original user query; use AI agent's suggested response
      const targetPrompt = /^SKU[-_\s]?\d+$/i.test(payload.trim())
        ? (isVi ? `Phân tích chi tiết mặt hàng ${payload.trim()}.` : `Analyze details for ${payload.trim()}.`)
        : payload;

      await handleSend(targetPrompt);
      return;
    }

    if (resolvedAction === "view_item_on_screen" && payload) {
      setLeftOpen(true);
      const skuM = payload.match(/\b(SKU[-_\s]?\d+)\b/i)?.[1];
      const numM = payload.match(/\b(\d{1,6})\b/)?.[1];
      const targetSku = skuM ? skuM.replace(/[\s_]/g, "-").toUpperCase() : "";
      const targetNum = numM ? parseInt(numM, 10) : null;
      const cleanPayload = payload.trim().toLowerCase();

      const item = forecastItems.find(
        (it) =>
          (targetSku && it.sku?.toUpperCase() === targetSku) ||
          (targetNum !== null && String(it.id) === String(targetNum)) ||
          it.sku?.toLowerCase() === cleanPayload ||
          it.name?.toLowerCase().includes(cleanPayload)
      );
      if (item) {
        await handleSelectItem(item, true); // Activate TreeSHAP calculation
        const confirmMsg: ChatMessage = {
          role: "assistant",
          text: isVi
            ? `Đã mở mặt hàng **${item.name} (${item.sku})** lên giao diện làm việc và kích hoạt tính toán các yếu tố ảnh hưởng dự báo.`
            : `Opened **${item.name} (${item.sku})** on the workspace dashboard and activated forecast drivers calculation.`,
        };
        setMessages((prev) => [...prev, confirmMsg]);
      }
      return;
    }

    if (resolvedAction === "run_shap" && payload) {
      // 1. Resolve intended SKU/item: check payload, clarification prompt, and recent user message
      const skuFromPayload = payload.match(/\b(SKU[-_\s]?\d+)\b/i)?.[1];
      const numFromPayload = payload.match(/^\s*(\d{1,6})\s*$/)?.[1];
      const cardText = `${clarification?.title || ""} ${clarification?.description || ""} ${clarification?.sku || ""}`;
      const skuFromCard = cardText.match(/\b(SKU[-_\s]?\d+)\b/i)?.[1];

      let intendedItem: ForecastedItem | undefined;
      if (skuFromPayload) {
        const clean = skuFromPayload.replace(/^sku[-_\s]?/i, "");
        intendedItem = forecastItems.find(
          (it) => it.sku?.toLowerCase() === skuFromPayload.toLowerCase() || String(it.id) === clean
        );
      } else if (numFromPayload) {
        intendedItem = forecastItems.find(
          (it) => String(it.id) === numFromPayload || it.sku?.toLowerCase() === `sku-${numFromPayload}`
        );
      }

      if (!intendedItem && skuFromCard) {
        const clean = skuFromCard.replace(/^sku[-_\s]?/i, "");
        intendedItem = forecastItems.find(
          (it) => it.sku?.toLowerCase() === skuFromCard.toLowerCase() || String(it.id) === clean
        );
      }

      if (!intendedItem) {
        const cleanPayload = payload.trim().toLowerCase();
        intendedItem = forecastItems.find(
          (it) => it.sku?.toLowerCase() === cleanPayload || isFuzzyNameMatch(cleanPayload, it.name || "")
        );
      }

      if (!intendedItem) {
        const lastUserMsg = [...messages].reverse().find((m) => m.role === "user")?.text || "";
        const skuFromMsg = lastUserMsg.match(/\b(SKU[-_\s]?\d+)\b/i)?.[1];
        if (skuFromMsg) {
          const clean = skuFromMsg.replace(/^sku[-_\s]?/i, "");
          intendedItem = forecastItems.find(
            (it) => it.sku?.toLowerCase() === skuFromMsg.toLowerCase() || String(it.id) === clean
          );
        }
        if (!intendedItem && lastUserMsg) {
          intendedItem = forecastItems.find((it) => isFuzzyNameMatch(lastUserMsg, it.name || ""));
        }
      }

      // The selected item on screen ONLY acts as a fallback when no intended item is known anywhere
      const item = intendedItem || selectedItem;

      if (!item) {
        const targetLabel = skuFromPayload || skuFromCard || payload;
        const prompt = isVi
          ? `Tính toán và phân tích các yếu tố ảnh hưởng dự báo cho ${targetLabel}.`
          : `Calculate and analyze forecast drivers for ${targetLabel}.`;
        await handleSend(prompt);
        return;
      }

      // Resolve focal day and original inquiry context to prevent context drift
      const cardFocalDay = (clarification as any)?.focalDay;
      const originalQ = (clarification as any)?.originalQuery || "";
      const lastUser = [...messages].reverse().find((m) => m.role === "user")?.text || "";
      const dayMatch = (originalQ || lastUser).match(/\b(?:day|ngày)\s*(\d{1,2})\b/i);
      const focalDay = cardFocalDay || (dayMatch ? parseInt(dayMatch[1], 10) : undefined);
      const userGoal = originalQ || (!lastUser.startsWith("/") && !lastUser.startsWith("Phân tích") && !lastUser.startsWith("Analyze") ? lastUser : "");

      const followUpPrompt = focalDay
        ? (isVi
          ? `Phân tích các yếu tố ảnh hưởng dự báo cho ${item.sku} vào Ngày ${focalDay} dựa trên kết quả tính toán thực tế vừa hoàn thành.`
          : `Analyze forecast drivers for ${item.sku} on Day ${focalDay} based on the freshly completed calculation.`)
        : userGoal
          ? (isVi
            ? `Phân tích các yếu tố ảnh hưởng dự báo cho ${item.sku} để giải đáp: "${userGoal}".`
            : `Analyze forecast drivers for ${item.sku} to answer: "${userGoal}".`)
          : (isVi
            ? `Phân tích chuyên sâu các nhóm yếu tố ảnh hưởng dự báo cho ${item.sku} dựa trên kết quả tính toán thực tế vừa hoàn thành.`
            : `Analyze forecast drivers for ${item.sku} based on the freshly completed calculation.`);

      // If TreeSHAP is already calculated, send analysis prompt immediately
      if (item.grouped_drivers && item.grouped_drivers.length > 0) {
        await handleSend(followUpPrompt);
        return;
      }

      // Immediately open left panel and set yellow pending state ("queued") in forecast list and selected item
      setLeftOpen(true);
      setSelectedItem({ ...item, shap_status: "queued" });
      setForecastItems((prev) =>
        prev.map((it) => (String(it.id) === String(item.id) ? { ...it, shap_status: "queued" } : it))
      );

      // Otherwise, display progress message, run loadItemShap, and wait until done
      const waitMsg: ChatMessage = {
        role: "assistant",
        text: isVi
          ? `**Đang phân tích các yếu tố ảnh hưởng dự báo cho ${item.name} (${item.sku})...**\n\nHệ thống đang tính toán tác động của các nhóm nhân tố kinh doanh. Trợ lý sẽ tự động phân tích ngay khi có số liệu thực tế.`
          : `**Calculating forecast drivers for ${item.name} (${item.sku}).**\n\nComputing attribution across business factor groups. The assistant will automatically analyze the results once calculated.`,
        isThinking: true,
      };
      setMessages((prev) => [...prev, waitMsg]);

      try {
        const targetRunId = item.run_id || forecastItems.find((it) => it.run_id)?.run_id;
        if (targetRunId) {
          const controller = new AbortController();
          const enriched = await loadItemShap(
            targetRunId,
            item.id,
            controller.signal,
            (status, queuedIds, activeId, completedIds) => {
              setForecastItems((prev) =>
                prev.map((it) => {
                  if (String(it.id) === String(item.id)) {
                    return { ...it, shap_status: status };
                  }
                  if (completedIds?.includes(it.id)) return { ...it, shap_status: "completed" };
                  if (activeId && it.id === activeId) return { ...it, shap_status: "running" };
                  if (queuedIds?.includes(it.id)) return { ...it, shap_status: "queued" };
                  return it;
                })
              );
              if (selectedItem && String(selectedItem.id) === String(item.id)) {
                setSelectedItem((prev) => (prev ? { ...prev, shap_status: status } : prev));
              }
            }
          );
          const key = `${targetRunId}:${item.id}`;
          itemCacheRef.current.set(key, enriched);
          setForecastItems((prev) =>
            prev.map((it) => (String(it.id) === String(item.id) ? { ...it, ...enriched, shap_status: "completed" } : it))
          );
          setSelectedItem(enriched);
        }
      } catch (err) {
        console.warn("TreeSHAP calculation error:", err);
        setForecastItems((prev) =>
          prev.map((it) => (String(it.id) === String(item.id) ? { ...it, shap_status: "not_requested" } : it))
        );
        if (selectedItem && String(selectedItem.id) === String(item.id)) {
          setSelectedItem((prev) => (prev ? { ...prev, shap_status: "not_requested" } : prev));
        }
      }

      // Once completed, send query to analyze real computed data
      await handleSend(followUpPrompt);
      return;
    }
  }


  function normalizeSearchText(text: string): string {
    if (!text) return "";
    return text
      .replace(/([a-zA-Z])(\d)/g, "$1 $2")
      .replace(/(\d)([a-zA-Z])/g, "$1 $2")
      .replace(/[_\-\s]+/g, " ")
      .trim()
      .toLowerCase();
  }

  function wordSimilarity(a: string, b: string): number {
    if (a === b) return 1.0;
    if (Math.abs(a.length - b.length) > 2) return 0.0;
    const matrix: number[][] = [];
    for (let i = 0; i <= b.length; i++) matrix[i] = [i];
    for (let j = 0; j <= a.length; j++) matrix[0][j] = j;
    for (let i = 1; i <= b.length; i++) {
      for (let j = 1; j <= a.length; j++) {
        if (b.charAt(i - 1) === a.charAt(j - 1)) {
          matrix[i][j] = matrix[i - 1][j - 1];
        } else {
          matrix[i][j] = Math.min(
            matrix[i - 1][j - 1] + 1,
            matrix[i][j - 1] + 1,
            matrix[i - 1][j] + 1
          );
        }
      }
    }
    const dist = matrix[b.length][a.length];
    return 1 - dist / Math.max(a.length, b.length);
  }

  function isFuzzyNameMatch(queryText: string, itemName: string): boolean {
    const qNorm = normalizeSearchText(queryText);
    const itNorm = normalizeSearchText(itemName);
    if (!qNorm || !itNorm) return false;

    if (qNorm === itNorm) return true;

    // Word-boundary match: prevents "onion 2" from matching "onion 20"
    const wordBoundaryRegex = new RegExp(`\\b${itNorm.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`);
    if (wordBoundaryRegex.test(qNorm)) return true;

    const qTokens = qNorm.split(" ");
    const itTokens = itNorm.split(" ");

    // Number constraint: if item has numeric component (e.g. "20"), query must contain that exact number
    const qNums = qTokens.filter((t) => /^\d+$/.test(t));
    const itNums = itTokens.filter((t) => /^\d+$/.test(t));
    if (itNums.length > 0) {
      if (!itNums.every((n) => qNums.includes(n))) return false;
    } else if (qNums.length > 0) {
      return false;
    }

    const qWords = qTokens.filter((t) => !/^\d+$/.test(t));
    const itWords = itTokens.filter((t) => !/^\d+$/.test(t));
    if (itWords.length === 0) return false;

    return itWords.every((itW) =>
      qWords.some((qW) => wordSimilarity(qW, itW) >= 0.75)
    );
  }

  async function handleSend(text = draft) {
    const content = text.trim();
    if (!content || isGenerating) return;

    const userMessage: ChatMessage = { role: "user", text: content };
    const nextMessages = [...messages, userMessage];

    // Intercept if forecast has not run yet to prevent wasting tokens
    if (forecastState !== "completed") {
      const isVi = language === "vi";
      if (forecastState === "loading") {
        const runningMessage: ChatMessage = {
          role: "assistant",
          text: isVi
            ? "⏳ **Dự báo nhu cầu đang được xử lý (Forecast in progress)...**\n\nHệ thống đang tính toán chuỗi thời gian 14 ngày. Trợ lý sẽ tự động bắt đầu phiên hội thoại mới ngay khi hoàn tất."
            : "⏳ **Demand forecast is currently in progress...**\n\n14-day pipeline computation is actively running. The assistant will automatically start a new session as soon as it completes.",
        };
        setMessages([...nextMessages, runningMessage]);
        setDraft("");
        return;
      }

      const mustRunMessage: ChatMessage = {
        role: "assistant",
        text: isVi
          ? "**Bạn chưa chạy dự báo (Run Forecast)!**\n\nĐể đảm bảo câu trả lời chính xác, hệ thống yêu cầu bạn phải khởi chạy dự báo nhu cầu trước. Trợ lý chỉ có thể phân tích dữ liệu tồn kho, ROP và các yếu tố ảnh hưởng dự báo sau khi có phiên dự báo mới nhất."
          : "**Forecast not executed yet!**\n\nTo ensure grounded analysis, you must run a demand forecast before asking the assistant. The assistant requires active forecast records to evaluate stockout risks, ROP, and forecast drivers.",
        clarification: {
          type: "run_forecast",
          title: isVi ? "Bắt buộc khởi chạy dự báo" : "Forecast Required",
          description: isVi
            ? "Nhấn nút bên dưới để khởi chạy dự báo nhu cầu:"
            : "Click below to execute the forecast:",
          options: [
            {
              label: isVi ? "▶ Khởi chạy Dự báo (Run Forecast)" : "▶ Run Forecast",
              actionType: "run_forecast",
              primary: true,
            },
          ],
        },
      };
      setMessages([...nextMessages, mustRunMessage]);
      setDraft("");
      return;
    }

    const skuCodeMatch = content.match(/\bsku[-_\s]?(\d+)\b/i);
    const _mentionedItem = forecastItems.find((it) => {
      if (skuCodeMatch) {
        const targetNum = skuCodeMatch[1];
        const itSkuNum = it.sku?.replace(/^sku[-_\s]?/i, "");
        return String(it.id) === targetNum || itSkuNum === targetNum;
      }
      return isFuzzyNameMatch(content, it.name || "");
    });
    void _mentionedItem;

    const thinkingMessage: ChatMessage = { role: "assistant", text: "", isThinking: true };
    setMessages([...nextMessages, thinkingMessage]);
    setDraft("");
    setIsGenerating(true);

    // Update context immediately with current conversation tokens (user + assistant history)
    setContextInfo((prev) => ({
      ...prev,
      usedTokens: calculateConversationTokens(nextMessages),
      maxTokens: FIXED_MAX_TOKENS,
    }));

    let accumulatedText = "";
    let firstTokenReceived = false;
    let activeModelName: string | undefined = undefined;
    let receivedClarification: import("@/types/chat").ClarificationPrompt | undefined = undefined;
    const toolsCalled: string[] = [];
    const currentSteps: import("@/types/chat").AgentStep[] = [];
    const startTime = Date.now();
    // Pass the actual on-screen item open in workspace dashboard (not the query-mentioned item)
    const onScreenSku = selectedItem?.sku || (selectedItem?.id ? String(selectedItem.id) : undefined);
    const activeSessionId = session?.id || selectedItem?.run_id || forecastItems[0]?.run_id;

    const controller = new AbortController();
    chatAbortRef.current = controller;

    try {
      await sendChatStream(
        nextMessages,
        {
          onSelectSku: () => {
            // Screen item selection remains strictly under user control; no unsolicited auto-navigation
          },
          onModelActive: (modelName) => {
            activeModelName = modelName;
          },
          onClarification: (data) => {
            receivedClarification = data;
            setMessages((prev) => {
              const last = prev[prev.length - 1];
              if (last && last.role === "assistant") {
                return [
                  ...prev.slice(0, -1),
                  {
                    ...last,
                    clarification: data,
                  },
                ];
              }
              return prev;
            });
          },
          onShapCompleted: (itemId, sku) => {
            const cleanId = String(itemId).replace(/^sku[-_\s]?/i, "");
            setForecastItems((prev) =>
              prev.map((it) =>
                String(it.id) === cleanId || it.sku?.toLowerCase() === sku.toLowerCase()
                  ? { ...it, shap_status: "completed" }
                  : it
              )
            );
            setSelectedItem((prev) =>
              prev && (String(prev.id) === cleanId || prev.sku?.toLowerCase() === sku.toLowerCase())
                ? { ...prev, shap_status: "completed" }
                : prev
            );

            // Auto-reload TreeSHAP payload for items that were calculated or session reloaded
            const targetItem = forecastItems.find(
              (it) => String(it.id) === cleanId || it.sku?.toLowerCase() === sku.toLowerCase()
            );
            const runId = targetItem?.run_id || session?.id || forecastItems[0]?.run_id;
            if (targetItem && runId) {
              const controller = new AbortController();
              loadItemShap(runId, targetItem.id, controller.signal, () => { })
                .then((enriched) => {
                  itemCacheRef.current.set(`${runId}:${targetItem.id}`, enriched);
                  setForecastItems((prev) =>
                    prev.map((it) => (String(it.id) === cleanId ? { ...it, ...enriched, shap_status: "completed" } : it))
                  );
                  setSelectedItem((prev) =>
                    prev && (String(prev.id) === cleanId || prev.sku?.toLowerCase() === sku.toLowerCase())
                      ? { ...prev, ...enriched, shap_status: "completed" }
                      : prev
                  );
                })
                .catch(() => { });
            }
          },
          onStep: (step) => {
            if (step.type === "think") {
              const last = currentSteps[currentSteps.length - 1];
              if (last && last.type === "think") {
                last.content = (last.content || "") + (step.content || "");
              } else {
                currentSteps.push({ type: "think", content: step.content });
              }
            } else if (step.type === "tool") {
              currentSteps.push({ type: "tool", toolName: step.toolName });
            }
            const elapsed = Math.max(1, Math.round((Date.now() - startTime) / 1000));
            setMessages((prev) => {
              const last = prev[prev.length - 1];
              if (!last || last.role !== "assistant") return prev;
              return [
                ...prev.slice(0, -1),
                {
                  ...last,
                  text: accumulatedText,
                  isThinking: !firstTokenReceived,
                  toolsUsed: [...toolsCalled],
                  steps: [...currentSteps],
                  model: activeModelName,
                  durationSeconds: elapsed,
                  clarification: receivedClarification ?? last.clarification,
                },
              ];
            });
          },
          onToken: (token) => {
            firstTokenReceived = true;
            accumulatedText += token;
            const elapsed = Math.max(1, Math.round((Date.now() - startTime) / 1000));
            setMessages((prev) => {
              const last = prev[prev.length - 1];
              if (!last || last.role !== "assistant") return prev;
              return [
                ...prev.slice(0, -1),
                {
                  ...last,
                  text: accumulatedText,
                  isThinking: false,
                  toolsUsed: [...toolsCalled],
                  steps: [...currentSteps],
                  model: activeModelName,
                  durationSeconds: elapsed,
                  clarification: receivedClarification ?? last.clarification,
                },
              ];
            });
          },
          onToolStart: (toolName) => {
            if (!toolsCalled.includes(toolName)) {
              toolsCalled.push(toolName);
            }
            const elapsed = Math.max(1, Math.round((Date.now() - startTime) / 1000));
            setMessages((prev) => {
              const last = prev[prev.length - 1];
              if (!last || last.role !== "assistant") return prev;
              return [
                ...prev.slice(0, -1),
                {
                  ...last,
                  text: accumulatedText,
                  isThinking: !firstTokenReceived,
                  activeTool: toolName,
                  toolsUsed: [...toolsCalled],
                  steps: [...currentSteps],
                  model: activeModelName,
                  durationSeconds: elapsed,
                  clarification: receivedClarification ?? last.clarification,
                },
              ];
            });
          },
          onDone: (usedTokens) => {
            const finalElapsed = Math.max(1, Math.round((Date.now() - startTime) / 1000));
            const fullTokens =
              usedTokens ||
              calculateConversationTokens([
                ...nextMessages,
                { role: "assistant", text: accumulatedText },
              ]);
            setContextInfo((prev) => ({
              ...prev,
              usedTokens: fullTokens,
              maxTokens: FIXED_MAX_TOKENS,
            }));
            setMessages((prev) => {
              const last = prev[prev.length - 1];
              if (last && last.role === "assistant") {
                return [
                  ...prev.slice(0, -1),
                  {
                    ...last,
                    isThinking: false,
                    activeTool: undefined,
                    toolsUsed: [...toolsCalled],
                    steps: [...currentSteps],
                    model: activeModelName,
                    durationSeconds: finalElapsed,
                    clarification: receivedClarification || last.clarification,
                  },
                ];
              }
              return prev;
            });
          },
          onError: (errMsg) => {
            accumulatedText = errMsg;
            setMessages((prev) => {
              const last = prev[prev.length - 1];
              if (!last || last.role !== "assistant") return prev;
              return [
                ...prev.slice(0, -1),
                {
                  ...last,
                  text: accumulatedText,
                  isThinking: false,
                  activeTool: undefined,
                  toolsUsed: [...toolsCalled],
                  model: undefined,
                },
              ];
            });
          },
        },
        selectedModel,
        onScreenSku,
        controller.signal,
        language,
        activeSessionId
      );
    } catch (err) {
      if (controller.signal.aborted) {
        return;
      }
      console.warn("Streaming chat failed, falling back to synchronous chat:", err);
      if (!firstTokenReceived) {
        try {
          const res = await sendChatMessage(nextMessages, selectedModel, onScreenSku, language, activeSessionId);
          setMessages((prev) => {
            const last = prev[prev.length - 1];
            if (last && last.role === "assistant") {
              return [
                ...prev.slice(0, -1),
                {
                  ...last,
                  role: "assistant",
                  text: res.reply,
                  model: selectedModel,
                  isThinking: false,
                  activeTool: undefined,
                },
              ];
            }
            return [...prev, { role: "assistant", text: res.reply, model: selectedModel }];
          });
          setContextInfo({
            ...res.contextInfo,
            usedTokens:
              res.contextInfo?.usedTokens ||
              calculateConversationTokens([...nextMessages, { role: "assistant", text: res.reply }]),
            maxTokens: FIXED_MAX_TOKENS,
          });
        } catch (syncErr) {
          console.error("Chat error:", syncErr);
          setMessages((prev) => {
            const last = prev[prev.length - 1];
            const fallbackText = language === "vi"
              ? "Không thể kết nối tới Trợ lý AI. Vui lòng kiểm tra lại kết nối backend hoặc cấu hình API key."
              : "Unable to connect to AI Assistant. Please check your backend connection or API key configuration.";
            if (last && last.role === "assistant") {
              return [
                ...prev.slice(0, -1),
                {
                  ...last,
                  role: "assistant",
                  text: fallbackText,
                  isThinking: false,
                  activeTool: undefined,
                },
              ];
            }
            return [
              ...prev,
              {
                role: "assistant",
                text: fallbackText,
              },
            ];
          });
        }
      }
    } finally {
      chatAbortRef.current = null;
      setIsGenerating(false);
    }
  }

  function handleStopGeneration() {
    chatAbortRef.current?.abort();
    chatAbortRef.current = null;
    setIsGenerating(false);
    setMessages((prev) => {
      const last = prev[prev.length - 1];
      if (last && last.role === "assistant" && (last.isThinking || !last.text)) {
        return [
          ...prev.slice(0, -1),
          {
            ...last,
            isThinking: false,
            text: last.text || (language === "vi" ? "Đã dừng phản hồi." : "Response stopped."),
          },
        ];
      }
      return prev;
    });
  }

  function handleAskAssistant(item: ForecastedItem, customPrompt?: string) {
    setSelectedItem(item);
    setOpen(true);
    if (customPrompt) {
      handleSend(customPrompt);
    }
  }

  function handleNewConversation() {
    fetch(`${getApiBaseUrl()}/api/v1/chat/cleanup`, { method: "POST" }).catch(() => { });
    const isVi = language === "vi";
    setMessages([
      {
        role: "assistant",
        text: isVi
          ? "Xin chào! Tôi là trợ lý DemandAI. Bạn muốn phân tích hoặc tìm hiểu mặt hàng nào trong danh mục?"
          : "Hi! I’m your DemandAI assistant. What would you like to explore across your portfolio?",
      },
    ]);
    setContextInfo(INITIAL_CONTEXT);
    setDraft("");
    setIsGenerating(false);
  }

  const handleCloseChat = useCallback(() => setOpen(false), []);
  const handleToggleChat = useCallback(() => setOpen((prev) => !prev), []);
  const handleCloseLeft = useCallback(() => setLeftOpen(false), []);
  const handleToggleLeft = useCallback(() => setLeftOpen((prev) => !prev), []);

  return (
    <>
      <DemandAIHeader session={session} />
      <div
        className={`demand-body ${open ? "chat-is-open" : ""} ${leftOpen ? "left-panel-is-open" : ""}`}
      >
        <LeftPanel
          open={leftOpen}
          onToggle={handleToggleLeft}
          onClose={handleCloseLeft}
          selectedItem={selectedItem}
          language={language}
          onRetryShap={() => { if (selectedItem) void handleSelectItem(selectedItem); }}
          onAskAssistant={handleAskAssistant}
        />
        <WorkspaceCanvas
          forecastState={forecastState}
          forecastItems={forecastItems}
          onRunForecast={handleRunForecast}
          onRerunForecast={handleRunForecast}
          onForecastComplete={handleForecastComplete}
          onOpenAssistant={() => setOpen(true)}
          selectedItemId={selectedItem?.id}
          onSelectItem={handleSelectItem}
          isRestoringSession={isRestoringSession}
          restoringMessage={restoreProgress}
        />
        <ChatPanel
          open={open}
          onToggle={handleToggleChat}
          onClose={handleCloseChat}
          messages={messages}
          draft={draft}
          onChangeDraft={setDraft}
          onSend={handleSend}
          onStopGeneration={handleStopGeneration}
          onNewConversation={handleNewConversation}
          contextInfo={contextInfo}
          isGenerating={isGenerating}
          selectedModel={selectedModel}
          onSelectModel={setSelectedModel}
          language={language}
          onSelectLanguage={setLanguage}
          forecastState={forecastState}
          onRunForecast={handleRunForecast}
          onClarificationAction={handleClarificationAction}
          selectedItem={selectedItem}
        />
      </div>
    </>
  );
}
