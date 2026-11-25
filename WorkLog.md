# DemandAI Assistant Development & Session WorkLog

## Session Overview
- **Objective**: Implement Section 0 Intent Understanding Gate and Rule 9 Conversational Intent Inheritance, fix multi-warehouse retrieval for `Roll_57` (3 items), uncap tool data to eliminate artificial cutoffs, add report export format clarification, and fix View on Dashboard action type hijack.
- **Timestamp**: 2026-09-24

---

## 1. Work Completed in this Session

### N. Agent Intent Understanding Gate, Multi-Warehouse Retrieval & Uncapped Tool Data
1. **Intent Understanding Gate & Conversational Intent Inheritance (`sku_agent.py`, `fix _ref_agen.md`)**:
   - Added mandatory **Section 0: Intent Understanding Gate** before `RESPONSE RULES` in both Vietnamese and English system prompts (`SYSTEM_PROMPT_VI`, `SYSTEM_PROMPT_EN`).
   - Defined 8 internal intent dimensions: Target, Goal, Analytical Question, Scope, Time Horizon, Output/Action, Constraints, Authorization.
   - Enforced Zero-Guessing principle: unresolved material ambiguity triggers `show_clarification_card` rather than guessing or prematurely executing tools.
   - Replaced Rule 9 with **Conversational Intent Inheritance — Only When Unambiguous**, allowing intent inheritance from recent context only when target and goal are unambiguous.
2. **Interactive Report Export Clarification (`sku_agent.py`, `skills.py`)**:
   - Updated Rule 12 in system prompts and warehouse skill guides: when a user asks for a report or export without explicitly specifying the format, the agent calls `show_clarification_card` with concrete options (`📄 Xuất báo cáo PDF`, `📊 Tải file CSV bổ sung hàng`, `💬 Xem tóm tắt phân tích trong chat`) instead of guessing or forcing the user to type "pdf" or "csv".
3. **Multi-Warehouse SKU Resolution Fix (`tools.py`)**:
   - Fixed `get_sku_core_info`: now queries `find_all_warehouse_items_for_product(sku_or_id)`, returning all 3 warehouse locations for `Roll_57` (`Prague_1`, `Prague_2`, `Prague_3`) with their respective SKU codes, internal IDs, on-hand stocks, statuses, and category hierarchy.
   - Enhanced `get_sku_inventory_and_forecast`: when a multi-warehouse product name like `Roll_57` is queried, it now outputs the complete inventory breakdown across all warehouse locations (DOS, Safety Stock, ROP, Order quantity, Status) plus total portfolio sums.
4. **Removal of Artificial Data Cutoffs in Tools (`tools.py`, `rag.py`)**:
   - In `get_sku_shap_drivers`: removed arbitrary `[:3]` slicing on positive/negative feature drivers and `[:2]` slicing in `_format_day_drivers`, giving the agent full visibility of all active TreeSHAP drivers.
   - In `get_portfolio_overview`: passed `focus` parameter down to `build_overview_rag(focus=focus)`.
   - In `rag.py` (`build_overview_rag`): enabled dynamic limits (up to 30 items for `critical` and `reorder` when focused, all 6 deadstock items without truncation).
   - In `export_replenishment_csv`: expanded critical preview list from 3 to 10 items.
5. **Action Type Hijack Fix for Clarification Cards (`sku_agent.py`)**:
   - In `sku_agent.py`, fixed option `actionType` resolution: prioritized `view_item_on_screen` before SHAP calculation checks and removed `c_type == "run_shap"` catch-all, ensuring "View on Dashboard" never triggers TreeSHAP calculation.
6. **Tool Parameter Thinking Frame & Context-Aware Report Clarification (`sku_agent.py`, `skills.py`)**:
   - Added **Section 0.F: Tool Parameter Thinking Frame & Intent Relevance** across all tools in both Vietnamese and English system prompts.
   - Mandated parameter inspection before invoking candidate tools (`generate_pdf_report`: focus_area & warehouse; `export_replenishment_csv`: warehouse; `simulate_demand`: sku_code & price_change_percent; SKU tools: sku_or_id; `get_sku_shap_drivers`: sku_or_id & day).
   - Prohibited blind defaults (e.g. NEVER blindly default to overview PDF export when user asks for a report; NEVER blindly guess price simulation percentages).
   - Implemented **Format / Parameter Skipping**: if the user explicitly specifies the format ("PDF" or "CSV"), warehouse, or discount %, skip asking about that parameter and only clarify missing parameters.
   - Enhanced `show_clarification_card` options on `AssistantInquiryCard` to be dynamically tailored to context:
     * *No context / Portfolio*: prompt key focus areas (`Critical`, `Deadstock`, `Overview`, `Replenishment CSV`).
     * *Warehouse context*: prompt warehouse-scoped status options (`Critical`, `Deadstock`, `Overview`, `CSV`).
     * *Item context*: prompt item deep-dive analysis, warehouse PDF overview, or replenishment CSV.
7. **Mutual Exclusion of Clarification Cards & Completed Action Executions (`sku_agent.py`, `tools.py`, `ChatMessages.tsx`, `chatApi.ts`)**:
   - Fixed bug where `show_clarification_card` was displayed under an already completed export request.
   - Enforced mutual exclusion: when an action/export tool (`export_replenishment_csv`, `generate_pdf_report`) runs in the current turn, `show_clarification_card` is strictly suppressed and any trailing clarification is cleared via `clear_clarification` event.
   - Added frontend guardrail in `ChatMessages.tsx`: suppresses `AssistantInquiryCard` when the message contains a completed download link.

### M. True Context Token Accounting (250k Fixed Limit), Centralized Currency & KaTeX Rendering
1. **Context Donut Badge & Fixed 250,000 Token Ceiling (`DemandAIShell.tsx`, `chat.py`, `sku_agent.py`)**:
   - Set fixed context ceiling to `250_000` tokens across frontend (`FIXED_MAX_TOKENS = 250_000`) and backend (`context_size = 250_000`).
   - Replaced completion-only token counter with total conversation context token tracking (estimating both user queries and assistant messages across full turn history).
   - In `DemandAIShell.tsx`, dynamically updates `contextInfo.usedTokens` immediately on send using `calculateConversationTokens(nextMessages)` and accurately reconciles tokens on SSE `onDone` and synchronous fallback.
   - Preserves `INITIAL_CONTEXT` with accurate initial assistant greeting tokens and fixed 250k max capacity upon conversation reset.
2. **Centralized Currency Configuration (`config.py`, `simulation_service.py`, `sku_agent.py`, `test_simulation.py`)**:
   - Added `default_currency: str = "Thousand VND"` and `default_currency_unit: str = "K VNĐ"` in `backend/app/core/config.py`.
   - Eliminated hardcoded `CZK` from `backend/app/services/simulation_service.py`, replacing with dynamic `{CURRENCY}` placeholders.
   - Synchronized system prompt reporting rules in `backend/app/agent/sku_agent.py` to inherit currency standard directly from centralized settings, eliminating contradictory simulation output warnings.
   - Updated simulation test assertions to validate centralized currency units.
3. **Fast KaTeX LaTeX Math Rendering (`ChatMessages.tsx`, `demand-ai.css`, `layout.tsx`)**:
   - Installed `katex` and `@types/katex`, importing `katex/dist/katex.min.css` in root layout.
   - Implemented fast KaTeX block and inline rendering without double wrapper containers.
   - Added sleek dark-mode styling for `.msg-math-block` and `.msg-math-inline` matching the DemandAI design language.
4. **Visual Depth & Layered Surfaces Enhancement (`demand-ai.css`)**:
   - Added subtle radial backdrop gradient to `.demand-shell` and frosted glass blur (`backdrop-filter: blur(12px)`) to `.demand-header` with soft elevation shadow.
   - Upgraded `.workspace-canvas` with dual-layer depth shadows (`0 1px 3px rgba(15, 38, 71, 0.04), 0 8px 24px rgba(15, 38, 71, 0.06)`).
   - Added spatial separation drop shadows to `.left-slot` and `.chat-slot` flyout panels.
   - Enhanced `.chat-panel` and `.left-panel` with matching tonal depth gradients, inset highlight boundaries, frosted glass blur headers, and layered `.item-detail-card` cards.
   - Compacted LeftPanel DOM layout: inlined `ForecastStatusBadge` into item name header row (`.item-detail-name-row`), eliminated separate status row, and tightened tabs container/banner margins to eliminate redundant vertical scroll.
   - Streamlined Detail Tab (`DailyForecastLineChart.tsx`): consolidated trajectory header and hover card into a single row, merged preview/set states into a single clean string (`Preview Day xxx, ...` / `Day xxx, ...`), moved `detail-status-pill` behind the Stock metric, reduced SVG height from 150px to 110px, and minimized margins so TreeSHAP mirror bars stay in view without vertical scrolling during graph hover.
   - Cleaned up obsolete CSS selectors in `demand-ai.css` (`.detail-hover-banner`, `.detail-hover-date-bar`, `.detail-set-chip`, `.detail-preview-chip`, `.detail-hover-val`, `.detail-chart-header`, `.detail-chart-title`, `.detail-chart-badge`, `.detail-metric-unit`).
   - Enhanced `.message-bubble` (assistant and user) with gentle tonal gradients and depth shadows while keeping all layout dimensions strictly synchronized.
   - Enhanced `.forecast-row` depth and interactive states: added dual-direction tonal gradients, subtle drop shadows, reactive avatar pill elevation (`.item-initial-box`), crisp inset selection bars (`inset 4px 0 0 #187cf2`), and smooth cubic-bezier transitions.
   - Added 3-mode sort cycle for table columns (`name`, `forecast14d`, `onHandStock`): first click sorts descending, second click sorts ascending, third click clears sort and restores normal status priority order.
   - Synchronized `.left-panel-tab-bar` and `.left-panel-tab-btn` with button design language: subtle border, inner inset shadow, reactive hover background, border highlight, and elevated active card state.
   - Centralized button styling system in `demand-ai.css` using `:root` design tokens for 3 tiers (Primary, Secondary, Tertiary) across up to 4 states (`normal`, `hover`, `active`, `disabled`), featuring enhanced distinct hover effects (radial glow drop shadows, boundary ring highlights, and high-contrast color shifts) while locking typography to `font-weight: 600`.
   - Created `no_push/button_preview.html` directly reusing production `demand-ai.css` for clean visual inspection of all 3 button tiers and component mapping without bundle overhead.
1. **On-Screen Item vs Asked Item Disambiguation (`tools.py`, `sku_agent.py`)**:
   - Added `active_item_context` (`ContextVar[str | None]`) in `tools.py` ensuring `resolve_sku_item` prioritizes the query item and conversational context over UI selection.
   - Updated Rule 1 in both Vietnamese and English system prompts to clarify the on-screen selected item is only a secondary fallback, mandating full focus on the item the user is currently asking about.
2. **Model Key Isolation & OpenRouter Collision (`sku_agent.py`, `ChatComposer.tsx`)**:
   - Isolated `OPENROUTER_API_KEY` from `OPENAI_API_KEY` in `get_llm_api_key()`.
   - Added automated fallback to `get_default_model_name()` when a chosen model lacks credentials.
   - Removed 15s interval polling loop in `ChatComposer.tsx`, replacing with one-shot mount checks and window focus/reconnect listeners.
3. **Double Error Text Elimination (`sku_agent.py`)**:
   - Removed duplicate `{'type': 'token', 'content': err_msg}` emission preceding the `error` event to prevent repeating error banners in the chat UI.
4. **Split-Token `<think>` Buffer & Multi-Block Reasoning (`sku_agent.py`)**:
   - Implemented a sliding buffer accumulator across chunk boundaries to prevent split `<think>` and `</think>` tags from leaking into user-visible tokens.
   - Extended support for multiple think blocks across tool call cycles (`think` → `tool` → `think`).
5. **TreeSHAP ID Normalization (`sku_agent.py`, `DemandAIShell.tsx`)**:
   - Standardized `shap_completed` event IDs to normalized integer strings (e.g., `SKU-010` → `"10"`).
   - In `DemandAIShell.tsx`, `onShapCompleted` matches both stripped numeric IDs and lowercase SKU codes.
6. **Chat History Synchronization & Operational Compaction (`chat.py`, `sku_agent.py`)**:
   - Sliced history arrays precisely up to the last user message turn in `chat.py`.
   - Added `compact_messages()` in `sku_agent.py` to extract operational findings, referenced SKUs, and metric summaries while discarding conversational noise.
7. **Unflushed SSE Stream Buffer (`chatApi.ts`)**:
   - Added post-stream flush in `sendChatStream()` to process and dispatch trailing SSE tokens lacking trailing `\n\n`.
8. **Stale Closure State Elimination (`DemandAIShell.tsx`)**:
   - Converted all stream event handlers (`onStep`, `onToken`, `onToolStart`, `onError`, `onDone`, and catch fallbacks) to functional state updates `setMessages((prev) => ...)`.
9. **Prompt Delimiter Regex & Bare Slash Commands (`DemandAIShell.tsx`, `sku_agent.py`)**:
   - Replaced strict regex with whitespace/delimiter-tolerant pattern `tokens.join("[_\\-\\s]*")`.
   - Added `find_previously_mentioned_sku()` to allow bare slash commands (`/drivers`, `/timeline`, `/reorder`) to inherit the active context SKU from recent conversation turns.
10. **Session Restoration on F5/Re-entry (`DemandAIShell.tsx`, `WorkspaceCanvas.tsx`)**:
    - Automatic session recovery from `sessionStorage`/`localStorage` for sessions under 5 minutes old via `fetchLiveForecast()`, restoring workspace items and setting `forecastState = "completed"` without rerunning the forecast.
11. **TreeSHAP Lifecycle & LeftPanel Breakdown Tab (`LeftPanel.tsx`, `DemandAIShell.tsx`, `TreeShapComputingVisualizer.tsx`)**:
    - Defaulted active tab permanently to `"breakdown"` in `LeftPanel.tsx`.
    - Enabled on-demand calculation dispatch (`autoCalculateShap = true`) while maintaining clean queue transitions (`"queued"` → `"running"` → `"completed"`) and the yellow pending dot (`is-pending`) in `ForecastTable.tsx`.
    - Removed redundant disclaimer notes (*"⚠️ Note: TreeSHAP drivers have been successfully calculated..."*) via system prompt directives.

### K. Infinite Reconnect Limit & TreeSHAP Fast-Inquiry Context-Aware Disambiguation Fix
1. **Model Polling Limit & Manual Reconnect (`ChatComposer.tsx`)**:
   - Capped backend model availability polling to 5 consecutive failures when backend is offline.
   - Clears interval upon reaching limit, marks state as `isOffline`, changes dropdown option to `"Backend Offline"`, and presents an inline `Reconnect ↻` button.
   - Clicking `Reconnect ↻` resets fail counter and triggers a clean recheck.
2. **Explicit SKU in Daily Forecast Fast-Inquiry (`DailyForecastLineChart.tsx`)**:
   - Updated negative and positive TreeSHAP card click handlers (`lines 824, 865, 906, 947`) from `for ${item.name}.` to `for ${item.name} (${item.sku}).`.
   - Guarantees fast-inquiry prompts carry exact SKU codes, preventing ambiguous product name fuzzy-matching from accidentally matching unrelated items with identical numbers (e.g. Day 5 or Lag 1 matching Melon_5 or Roll_1).
3. **Context-Aware Intent Disambiguation Guard (`fallback.py`)**:
   - Enhanced `evaluate_intent_guard` to inspect `selected_item_id`.
   - When the user already has an item open on screen that matches query candidates, `multi_matches` disambiguation popup is bypassed so the request routes directly to the LLM agent using context instead of prompting a redundant SKU selection card.

### J. Model Dynamic Polling, Conversational Time-Series Reasoning, Item Disambiguation & Test Modernization
1. **Dynamic Model Selector & Reset Detection (`ChatComposer.tsx`, `chat.py`, `chatApi.ts`)**:
   - Added `BOOT_ID` to `/api/v1/chat/models` to detect backend restarts.
   - Replaced one-shot `useEffect` in `ChatComposer.tsx` with interval polling (3s when empty, 15s normally), window focus/online re-checks, reset detection, auto-syncing `selectedModel`, and a disabled `"Connecting..."` fallback option to prevent empty dropdowns.
2. **Mock Data Removal & Legacy Deletion (`rag.py`, `sku_agent.py`, `tools.py`)**:
   - Completely deleted legacy `backend/app/assistant/` and `backend/tests/test_assistant.py`.
   - Created `backend/app/agent/rag.py` where `build_overview_rag()` aggregates live database inventory from `_load_all_inventory_items()` (tracking all 5,390 real items across 7 warehouses, eliminating 20-item mock truncation).
   - Removed `ITEMS_KNOWLEDGE_BASE` references from `backend/app/agent/tools.py`.
3. **Conversational Intent & Time-Series Reasoning Frame (`skills.py`)**:
   - Enhanced `get_skills_system_prompt()` in both Vietnamese and English.
   - Linked natural conversation inquiries (e.g., "hàng còn đủ không?", "bán ra sao?", "tại sao dự báo giảm?", "so với các món khác thế nào?") directly to time-series patterns (peak day, weekend dynamics, runout day), TreeSHAP root causes, and replenishment calculations without forcing slash commands.
4. **Non-Existent Item Guardrail (`fallback.py`, `sku_agent.py`)**:
   - Fixed `extract_sku_mention` so arbitrary strings like "donut 22" are no longer parsed as raw integer SKUs (`SKU-22`).
   - Added Rule 8 (`NON-EXISTENT ITEM INVARIANT`) to both `SYSTEM_PROMPT_VI` and `SYSTEM_PROMPT_EN`: if an item is not found, the agent explicitly states so without substituting the on-screen item or another existing SKU.
5. **Ambiguous Item Inquiry Card & Conversational Intent Inheritance (`AssistantInquiryCard.tsx`, `fallback.py`, `sku_agent.py`)**:
   - Renamed component to `AssistantInquiryCard.tsx` and removed redundant redirect file `AssistantClarificationCard.tsx`.
   - Removed aggressive `is_vague_phrase` regex in `fallback.py`: follow-up queries like "what about this one?" now pass directly to the LLM.
   - Added Rule 9 (`CONVERSATIONAL INTENT INHERITANCE`) to system prompts: when user asks "what about this one?", the LLM inherits analytical intent (stockout, TreeSHAP, peer rank) from previous turns and answers directly for the target item.
   - For deictic inquiries genuinely ambiguous between on-screen Item A and chat history Item B, LLM invokes `show_clarification_card` to let user choose via `AssistantInquiryCard`.
6. **Clean Test Suite Modernization (`test_sku_agent.py`)**:
   - Rewrote `backend/tests/test_sku_agent.py` to remove stale assumptions on mock "SKU-010" and offline RDS failures.
   - Added 11 focused, hermetic unit tests covering language detection, memory compaction, skill routing, presets, out-of-scope templates, SKU extraction, tool execution, resolve SKU, clarification cards, models API, and intent guards. All 11 tests pass in ~4.8s.
7. **Synthesis of Advanced Analytics Skills (`stuff_to_be_add/`, `skills.py`, `sku_agent.py`)**:
   - Explored 31 portable data analytics skills in `stuff_to_be_add/data-analytics-skills` and `analytics/SKILL.md`.
   - Inherited the **Finding → So What → Why → Now What** framework from `insight-synthesis`: structure every SKU response with grounded data, quantified business risk, root-cause attribution, and decisive replenishment actions.
   - Inherited **Bottom-Line-Up-Front (BLUF)** from `executive-summary-generator` and **Technical-to-Business Translation** from `technical-to-business-translator` (translating TreeSHAP, safety buffer, and ROP into executive retail terms).
8. **Production Polish - Removed Demo Banner (`ChatMessages.tsx`)**:
   - Removed hardcoded `"DEMO CONVERSATION"` badge from the chat header.
   - Replaced with standard localized production date stamp (`TODAY` / `HÔM NAY`).

### I. Fix Clarification Button Overflow, Confusing Step, Prompt Fallback, and View Item Card
1. **Button Overflow (`demand-ai.css` & `AssistantClarificationCard.tsx`)**:
   - Switched `.clarification-actions-grid` to vertical flex layout (`flex-direction: column; width: 100%`).
   - Styled `.clarification-btn` with `white-space: normal; word-break: break-word; text-align: left; width: 100%; box-sizing: border-box;`.
   - Set `.btn-label` to `flex: 1; min-width: 0; word-break: break-word;`. Buttons wrap naturally and stay 100% within card boundaries.
2. **Confusing Step Emission (`sku_agent.py`)**:
   - Filtered `tool_name == "show_clarification_card"` from emitting `tool_start` and `step` SSE events. It is a visual interactive prompt, not a data retrieval step.
3. **Where "Deep-dive analysis..." Fallback Came From & Fix**:
   - In `sku_agent.py`, regex `sku_m` matching inside button label was evaluated before `run_shap` / `view_item_on_screen`. This mistakenly labeled `run_shap` buttons as `select_sku`.
   - In `DemandAIShell.tsx`, when `actionType === "select_sku"` and `clarification?.originalQuery` was missing, it defaulted to `Deep-dive analysis on on-hand inventory, ROP parameters, and forecast drivers for ${payload}`.
   - Fixed option actionType precedence to check `run_shap` and `view_item_on_screen` before generic SKU numbers, passed `originalQuery: query` in `card_payload`, and streamlined prompt template.
4. **"View the Item" Interactive Card**:
   - In `backend/app/agent/fallback.py`, added view intent recognition in `evaluate_intent_guard` ("view item", "view the item", "xem mặt hàng", etc.) to immediately present an interactive card with "👁️ Open on Dashboard" and "📊 View in chat".
   - In `frontend/src/components/DemandAIShell.tsx`, enhanced `view_item_on_screen` to match target SKU/ID via regex and call `setLeftOpen(true)` so the item details drawer opens reliably.

### H. Add Lead Time Stat Card to Detail View
- Added 5th `detail-stat-card` for **Lead Time** (`{item.leadTimeDays != null ? `${item.leadTimeDays}d` : "N/A"}`) to `DailyForecastLineChart.tsx`.
- Updated `.detail-stat-row` in `demand-ai.css` from `grid-template-columns: repeat(4, 1fr)` to `repeat(5, 1fr)` to house Daily Avg, Peak, Min, Day of Supply, and Lead Time harmoniously.

### G. Fix `forecast.py` Single-Item NameError Bug & Attach Active `run_id`
1. **Root Cause**:
   - In `backend/app/api/routes/forecast.py`, `_get_single_item_shap(uid)` referenced `_SINGLE_ITEM_SHAP_CACHE` and `_SHAP_DF_CACHE`, which were undefined names left after static parquet cleanup.
   - Any single-item forecast request (`/api/v1/forecast/get_forecast_14d?unique_id=X&source=cache` or whenever RDS timed out / was unreachable) crashed immediately with `NameError: name '_SINGLE_ITEM_SHAP_CACHE' is not defined`.
   - Additionally, `_load_all_inventory_items` did not attach `run_id` or `shap_status`, which prevented frontend TreeSHAP cache operations when fallback items were returned.
2. **Resolution**:
   - Refactored `_get_single_item_shap(uid)` to load on-demand computed SHAP from disk cache `cache_path(run_id, uid)` if available in the active run, or return `{}` gracefully with zero crash.
   - Updated `_load_all_inventory_items` to query active `run_id` from RDS and attach `"run_id": active_run_id` and `"shap_status": "not_calculated"`.
   - Verified with unit tests: `GET /api/v1/forecast/get_forecast_14d?unique_id=10&source=cache` returns 200 with enriched item cleanly.

### F. Enforce Intended Item Priority (Selected Item Only Acts as Fallback)
1. **Root Cause Analysis (Misleading Target Bug)**:
   - When the user asked `/drivers cucumber8` (`Cucumber_8 / SKU-613`), the assistant recognized TreeSHAP was uncalculated and displayed the confirmation card.
   - However, the confirmation card options contained the generic label `"Accept & Calculate TreeSHAP"`.
   - In `backend/app/agent/sku_agent.py`, the option parser could not extract a SKU from that generic label, setting `payload = "Accept & Calculate TreeSHAP"`.
   - In `frontend/src/components/DemandAIShell.tsx`, `handleClarificationAction` attempted to match `"accept & calculate treeshap"` against `forecastItems`. Failing to match, it unconditionally fell back to `|| selectedItem` (`Roll_56 / SKU-4879`).
   - Consequently, the UI triggered calculation on `Roll_56`, built the analysis prompt with `SKU-4879`, and the assistant answered for the wrong item while `Cucumber_8` remained uncalculated.
2. **Resolution & Fixes**:
   - **Target Intended Item Directive**: Added strict system prompt rules in both Vietnamese and English stating: "The assistant must prioritize and answer exclusively for the INTENDED item asked or mentioned in the user prompt (e.g. `cucumber8` -> `Cucumber_8 / SKU-613`). The on-screen selected item ONLY acts as a fallback when NO intended item is known or when the user explicitly says 'this item'/'it'."
   - **Intent Tracking in Agent Streaming (`sku_agent.py`)**: Directly extracted `intended_sku` from query using `extract_sku_mention(query, selected_item_id=None)` and tracked `last_queried_sku` across tool calls.
   - **Dynamic Target SKU in Clarification Card**:
     - Added `sku: str = ""` parameter to `show_clarification_card` in `backend/app/agent/tools.py`.
     - In `on_tool_start`, automatically bound `target_sku` to `tool_input.sku` or `last_queried_sku` or `intended_sku`.
     - Explicitly set option `payload` to `target_sku` (e.g. `"SKU-613"`), and ensured button labels display the SKU (e.g. `"Accept & Calculate TreeSHAP (SKU-613)"`).
     - Emitted `sku: target_sku` inside the clarification SSE payload.
   - **Multi-Level Intended Item Resolution in Frontend (`DemandAIShell.tsx`)**:
     - `handleClarificationAction` now searches for the intended item across: (1) `payload` via regex `SKU-\d+` and numeric IDs, (2) `clarification.sku` or title/desc regex, (3) matching against recent user messages in chat history.
     - `selectedItem` ONLY acts as a fallback when NO intended item is known anywhere.
     - The calculation `loadItemShap`, UI status update (`shap_status: "completed"`), and follow-up prompt all run strictly for the intended item (`SKU-613`).
     - Fixed `item-shap-dot` update in `ForecastTable` by matching on `String(it.id) === String(item.id)`.

### E. Ground-Up Online TreeSHAP Calculation & Complete SHAP Parquet Audit
1. **Audit of All Locations Loading SHAP Parquet (`ensemble_local_shap_union.parquet`)**:
   - `backend/app/api/routes/forecast.py`:
     - `_ensure_static_models_loaded()`: Loaded `shap_path = models / "ensemble_local_shap_union.parquet"`, built `_SHAP_DF_CACHE`, and populated static `drivers_map`.
     - `_load_all_inventory_items()`: Embedded static `drivers_map.get(uid, [])` as `grouped_drivers`.
     - `_get_single_item_shap(uid)`: Read positive/negative features from `_SHAP_DF_CACHE`.
     - `/api/forecast/items/{unique_id}` (`_get_cached_forecast_payload`): Called `_get_single_item_shap(str(unique_id))` to attach offline SHAP.
   - `backend/app/services/forecast_persistence.py`:
     - `extract_model_parquet_data(...)`: Read `shap_df = pl.read_parquet(shap_path)` (default `ensemble_local_shap_union.parquet`) to extract business group impacts and summary/daily features.
     - `save_predictions_to_db(...)`: Called `extract_model_parquet_data(..., shap_path=shap_path, include_shap=True)`.
   - `backend/app/pipeline/recursive_ensemble.py`:
     - `TreeExplainer.__init__()`: Defined `self.offline_parquet_path = self.models_dir / "ensemble_local_shap_union.parquet"`.
     - `TreeExplainer.preload_offline_data(...)`: Read `self.offline_parquet_path` via `pl.scan_parquet`.
     - `TreeExplainer.explain(...)`: In offline/auto mode, queried `self._offline_df` and returned precomputed rows.
2. **Ground-Up Online Calculation in `get_sku_shap_drivers` (`backend/app/agent/tools.py`)**:
   - Eliminated reliance on `_get_single_item_shap` and the outdated `ensemble_local_shap_union.parquet`.
   - Checked active forecast session (`CoreForecastRun` where `is_latest == True`) and PostgreSQL item record (`CoreForecastItemSummary`).
   - If driver SHAP is **not active** on that item, immediately invokes `calculate_item_shap(latest_run_id, uid)` on-the-fly using native C++ multi-threaded TreeSHAP across 14 horizons.
   - Persists fresh results into PostgreSQL (`CoreForecastItemSummary`, `CoreForecastDailyPoint`) and disk cache.
   - Formats and returns actual dynamically computed factor group shares and top positive/negative feature drivers.
   - If uncalculated and cannot calculate (e.g. no forecast run exists), returns `Status: NOT CALCULATED YET` so the UI's `run_shap` card triggers without hallucinations.
3. **Removal of Stale Parquet Loading in `forecast.py`**:
   - Removed `pl.read_parquet` of `ensemble_local_shap_union.parquet` inside `_ensure_static_models_loaded()`. Items now start with empty `grouped_drivers: []` until computed online.


### A. Root-Cause Diagnosis: TreeSHAP Hallucination & Tool Skips on Ling-3.0
1. **Mock Drivers in Database Loader (`forecast.py:L149-155, L220`)**:
   - `forecast.py` defined hardcoded `default_drivers` (60% Sales Lags, 25% Pricing, 10% Promotion, 3% Calendar, 2% Context).
   - In `_load_all_inventory_items`, every uncalculated item received `drivers_map.get(uid, default_drivers)`!
   - Because of this, `grouped_drivers` was **never empty** for any item in the entire system.
   - Consequence A: In `DemandAIShell.tsx:L253`, `item.grouped_drivers && item.grouped_drivers.length > 0` was always truthy, so clicking "Run TreeSHAP" or asking for TreeSHAP bypassed calculation and never ran `loadItemShap`.
   - Consequence B: `get_sku_shap_drivers` in `tools.py` never entered `Status: NOT CALCULATED YET` because mock `grouped_drivers` was present while specific feature drivers were empty (`No positive drivers found`).
   - Consequence C: When the LLM was asked to explain drivers, it saw 60% / 25% but zero features, forcing the model to **fabricate feature numbers** to justify the mock percentages!
2. **Prompt Leaks in `skills.py`**:
   - `skills.py:L106, L129` had the literal example `giải thích 55% Sales Momentum`. Ling-3.0 seized on this text and regurgitated "55%" directly.
3. **Reasoning-Token Trap (`ling-3.0-flash-vl`)**:
   - As a reasoning model, Ling-3.0 placed its post-tool synthesis entirely inside `reasoning_content` (227 reasoning tokens, 0 regular content tokens). The SSE parser routed this to `step: think`, leaving the main response stream blank and prompting fallback.

### B. Dynamic `DEFAULT_MODEL`
- Implemented `get_default_model_name()` in `backend/app/agent/sku_agent.py`:
  - Dynamically grabs the first model where `provider == "openrouter"` if OpenRouter key is configured, else first `provider == "openai"`, else first key in `MODELS`.
  - Updated `backend/app/api/routes/chat.py` to use `get_default_model_name()` and safe `MODELS.get(...)` fallbacks, eliminating `KeyError` exceptions when models are modified or commented out in `MODELS`.

### C. Total Eradication of Mock & Offline Mode
- **Backend (`forecast.py`)**: Deleted `default_drivers` mock list. Uncalculated items now have `"grouped_drivers": drivers_map.get(uid, [])`.
- **Frontend API Client (`chatApi.ts`)**: Removed `isDemoFallback` and lines 180–202 containing mock `demoReply` ("DemandAI Assistant (Demo Mode)..."). Unsuccessful requests now throw proper errors.
- **Frontend UI (`DemandAIShell.tsx`)**: Removed `isDemoFallback` check and replaced the offline demo message in the sync error catch block with an authentic localized error notice.

### D. Stale Code Cleanup & Verification
- **`backend/app/agent/skills.py`**: Removed `55% Sales Momentum` examples; added strict directive that `get_sku_shap_drivers` must be called and numbers must never be guessed.
- **`backend/app/agent/tools.py`**: Updated `get_sku_shap_drivers` signature to `sku_or_id: str = ""` with robust deictic/selected fallback and verified non-zero driver scores.
- **`backend/tests/test_sku_agent.py`**: Replaced `test_skills_matching_and_offline_resolution` (which called the deleted `answer_offline_skill_query`) with `test_skills_matching` to verify intent and tool assignment directly.
- **Test Suite Status**: 20/20 deterministic and guardrail tests PASSED. Live LLM tests confirmed functioning, currently encountering OpenRouter free-tier 50 requests/day rate limit (`Rate limit exceeded: free-models-per-day`).
- **Frontend Build**: TypeScript typecheck passed cleanly with 0 errors.

---

### A. Pull Review (`bd418f0..c25111e`)
- Investigated commit `c25111e` which implemented the SKU Analysis Agent via LangChain, SSE streaming, 5 analytical tools querying RDS, bilingual intent guardrails, and frontend real-time tool execution visualizer.
- Identified required setup command for newly introduced dependencies (`langchain>=0.3.0`, `langchain-core>=0.3.0`, `langchain-openai>=0.2.0`).

### B. End-to-End Pipeline & Workflow Analysis
- Traced the complete lifecycle of a user prompt:
  1. Input in `ChatComposer.tsx` $\rightarrow$ `DemandAIShell.tsx`.
  2. Native `ReadableStream` in `chatApi.ts: sendChatStream` invoking `POST /api/v1/chat/stream`.
  3. Language detection & Intent Guardrails in `fallback.py` (Out-of-scope, Missing SKU, Ambiguous Intent clarifying questions).
  4. LangChain execution in `sku_agent.py` invoking 5 RDS tools in `tools.py`.
  5. Real-time SSE token & tool-badge rendering in `ChatMessages.tsx`.

### C. Dynamic Model Selection
- Added `/api/v1/chat/models` backend support checking for `OPENROUTER_API_KEY`.
- Updated `ChatComposer.tsx` with native `<select>` dropdown:
  - Default: `gpt-6-luna` ("GPT-6 Luna").
  - Dynamically includes `inclusionai/ling-3.0-flash-vl:free` ("Ling 3.0 Flash") only if `OPENROUTER_API_KEY` is configured in the environment; otherwise shows only the default model.
- Wired selected model through `DemandAIShell.tsx` $\rightarrow$ `ChatPanel.tsx` $\rightarrow$ `ChatComposer.tsx` and into `sendChatStream`.

### D. Chat Composer Layout Optimization
- Fixed cramped layout in `ChatComposer`:
  - Split `.composer-actions` into `.composer-actions-left` (action buttons & model select) and `.composer-actions-right` (context donut badge & send button).
  - Removed wrapping multi-line keyboard hint from the cramped button row, restoring ample breathing room.

### E. Language Toggle in Chat Header (Default EN)
- Added `EN / VI` toggle button in `chat-header` (`ChatPanel.tsx`).
- Default: `EN`.
- Enforced downstream via `language` field in `ChatRequest` (`backend/app/api/routes/chat.py`):
  - Overrides detection in `sku_agent.py` to enforce English or Vietnamese system prompts and tool summaries.
  - Passes through `evaluate_intent_guard` to enforce localized clarifying questions and errors.
- Added automated regression test `test_api_chat_language_toggle` in `backend/tests/test_sku_agent.py`.

### F. Model Attribution Display ("Active Only")
- Investigated the origin of the 4-point clarifying question response: confirmed it originates from `evaluate_intent_guard()` in `fallback.py` under ambiguous SKU inquiries.
- Added explicit backend SSE event: `{"type": "model_active", "model": "<name>"}` emitted only when the LLM agent is compiled and executed.
- Updated `DemandAIShell.tsx` to set `message.model` only upon receiving `model_active`.
- Updated `ChatMessages.tsx` so the subtle model attribution tag at the bottom of the message bubble renders **only** when an LLM model was actually active (hiding it on initial greeting, fallback clarifying menus, missing SKU prompts, and offline demo responses).

### G. Ambiguous Intent & Greeting False-Positive Fix
- **Root Cause Analysis**:
  1. `tools.py: resolve_sku_item()` used substring matching `if query in name:`. When the user typed `"hi"`, `"hi"` was found inside `"Chicken_23"`, returning an SKU despite no intention of selecting chicken.
  2. `fallback.py: extract_sku_mention()` had a loose fallback `or len(clean.split()) <= 3:` which bound any 1-3 word message to whatever `selected_item_id` was active in the workspace context.
- **Fix Implemented**:
  1. Added word-boundary matching and $\ge 4$ characters minimum requirement in `tools.py: resolve_sku_item()` to prevent short greetings from matching substrings.
  2. Expanded `OUT_OF_SCOPE_KEYWORDS` in `fallback.py` to include conversational greetings (`"hi"`, `"hello"`, `"hey"`, `"chào"`, `"xin chào"`, etc.) with word-boundary regex `\b`.
  3. Strict deictic binding in `extract_sku_mention()`: only binds to `selected_item_id` if explicit pointing words (`"this"`, `"it"`, `"nó"`, `"mặt hàng này"`, etc.) are present.
  4. Added regression assertions to `test_sku_agent.py` ensuring `"hi"` and `"hello"` immediately trigger `out_of_scope` without SKU binding.

### H. System Prompt Combination & Refinement
- Seamlessly combined original domain rules (factual accuracy, mandatory tool calling, inventory cross-referencing against safety stock and ROP, markdown formatting) with concise, simple-term, and targeted-reference instructions.
- Explicitly instructed the model to use tool numbers as targeted reference for answering the user's specific inquiry rather than regurgitating/dumping raw data tables.

### I. Route Cleanup & Memory/Registry Architecture Optimization
- **Preserved & Integrated Valuable Mechanisms into `sku_agent.py`**:
  - Relocated `MODELS` registry and `DEFAULT_MODEL` into `sku_agent.py`, breaking the circular dependency where the agent imported models from the route controller.
  - Ported `compact_messages()` and `estimate_tokens()` into `sku_agent.py`: preserves multi-turn conversational memory by keeping recent turns verbatim while auto-compacting older turns into a concise `[System Context Memory: Earlier conversation summary]` when conversations grow beyond 6 turns or 80% context threshold.
  - Added `get_portfolio_overview` to `SKU_TOOLS` in `app/agent/tools.py` and updated `fallback.py` to allow `/overview` and portfolio-wide queries without forcing single-SKU selection.
- **Cleaned `chat.py`**:
  - Removed dead imports (`os`, `re`, `settings`, `extract_sku_mention`, `handle_assistant_turn`).
  - Streamlined `chat.py` to act as the clean HTTP controller: imports `MODELS`, `DEFAULT_MODEL`, and `stream_sku_agent_response` directly from `sku_agent.py`.
  - Both `/stream` and synchronous `/message` run directly against `stream_sku_agent_response`.

### J. Stacked Dropdown UI for Tool Execution (Outside Message Bubble)
- Redesigned the tool usage indicator to match modern AI interfaces (per user screenshot):
  - Added vertical green accent line on the left (`2px solid rgba(16, 185, 129, 0.7)`).
  - Two-tier hierarchical dropdown control:
    - Tier 1 (`Worked for Xs ˅`): Clicking collapses/expands the entire secondary level.
    - Tier 2 (`Explored N tools, N searches >`): Indented sub-line; clicking reveals/hides the detailed tool list.
  - Collapsible tool list with status dots (emerald for done, pulsing blue for active), friendly Vietnamese names, and monospace tool signatures.
  - Refined with a subtle slate/neutral palette (`#475569` headers, `#64748b` sub-text, `#94a3b8` chevrons) instead of saturated blues.
- **Moved completely OUTSIDE `.message-bubble`**: Positioned directly between `.message-author` and `.message-bubble`.
- During active generation before first token, renders only the active tool execution indicator without an empty floating message bubble.
- Added elapsed duration tracking (`durationSeconds`) in `DemandAIShell.tsx` and `types/chat.ts`.

### K. Selected / On-Screen Item Grounding Fix
- **Root Causes**:
  1. `fallback.py: extract_sku_mention` did not recognize `"selected"`, `"looking at"`, `"viewing"`, or `"what item"`, causing queries like `"what item am i selected/looking at"` to return `None` and fail with `missing_sku`.
  2. `sku_agent.py: build_langchain_agent` never injected `selected_item_id` into the agent's system prompt, so the model had zero awareness of what the user was currently looking at on screen.
- **Fix Implemented**:
  1. Added full deictic referencing in `fallback.py` (`"selected"`, `"looking at"`, `"viewing"`, `"see"`, `"open"`, `"what item"`, `"tôi đang xem"`, `"món gì"`).
  2. Injected `CURRENT ON-SCREEN USER WORKSPACE CONTEXT` into `build_langchain_agent` in `sku_agent.py` providing item name, SKU, category, stock, 14-day demand forecast, and status directly in the system prompt.
  3. Added deterministic fallback for item identity inquiries in offline mode.
  4. Added automated regression test `test_query_selected_item_knowledge` in `backend/tests/test_sku_agent.py`.

### L. Out-of-Scope Fallback Default & LLM Intent Delegation
- **Requirements**:
  - Removed brittle hardcoded regex keyword filtering (`OUT_OF_SCOPE_KEYWORDS`) and missing-SKU blocking from `backend/app/agent/fallback.py`.
  - Allowed general, overview, and conversational queries to pass directly to the LLM agent without being intercepted by rigid guards.
  - Standardized exact out-of-scope fallback templates in `backend/app/agent/fallback.py` (`get_out_of_scope_message`) and enforced them via Rule 6 in both `SYSTEM_PROMPT_VI` and `SYSTEM_PROMPT_EN` in `backend/app/agent/sku_agent.py`:
    - Vietnamese:
      ```
      Tôi là DemandAI Assistant, chuyên viên phân tích dự báo nhu cầu bán lẻ và tối ưu hóa tồn kho hàng hóa. Câu hỏi của bạn nằm ngoài phạm vi hỗ trợ của tôi.
      Bạn có thể hỏi tôi về:
      •Phân tích nguy cơ đứt hàng hoặc dư thừa tồn kho cho một SKU (ví dụ: SKU-010).
      •Giải thích nguyên nhân tăng/giảm dự báo bằng TreeSHAP Drivers.
      •So sánh nhu cầu và rủi ro tồn kho với các mặt hàng cùng ngành.
      ```
    - English:
      ```
      I am DemandAI Assistant, a specialist in retail demand forecasting and inventory replenishment optimization. Your question is outside my scope of support.
      You can ask me about:
      •Analyzing stockout or deadstock risks for a specific SKU (e.g. SKU-010).
      •Explaining forecast drivers and feature attributions using TreeSHAP Drivers.
      •Comparing demand velocity and inventory risks across category peers.
      ```
- **Tests Updated**:
  - Updated `backend/tests/test_sku_agent.py` to verify standardized template strings and assert that `evaluate_intent_guard` delegates intent to the LLM (`is_fallback=False`).
  - 13/13 backend tests passing.

### M. Agent Code Review & Cleanup (SKILL-review.md / Ponytail)
- **Dead Code Eliminated**:
  - `backend/app/agent/tools.py`: Removed unused `json` and `logging` imports and unused `logger` instance (-4 lines).
  - `backend/app/agent/sku_agent.py`: Removed dead 13-line fallback loop over `.env` files with `dotenv_values` (-12 lines).
  - `backend/app/agent/sku_agent.py`: Replaced manual slice `url[:-17]` with stdlib `removesuffix("/chat/completions")` (-2 lines).
  - `backend/app/agent/sku_agent.py`: Simplified `compact_messages` loop into concise list comprehension (-5 lines).
- **Code Reused**:
  - `backend/app/agent/sku_agent.py`: Reused `get_out_of_scope_message("vi")` and `get_out_of_scope_message("en")` from `app.agent.fallback` in `SYSTEM_PROMPT_VI` and `SYSTEM_PROMPT_EN` instead of duplicating long message strings (-10 lines).
  - `backend/app/agent/sku_agent.py`: Hoisted deferred inner imports of `resolve_sku_item`, `get_sku_inventory_and_forecast`, `get_sku_shap_drivers`, `get_portfolio_overview` to module-level imports (-7 lines).
- **Net**: -40 lines eliminated across `backend/app/agent`.
### N. Tool Dropdown Labeling & Thinking Bubble Indicator
- **Tool Dropdown Dynamic Labeling**:
  - Replaced rigid `'Explored x tool, x search'` with dynamic, contextual discovery text:
    - Single tool: `Explored ${formatFriendlyToolName(tool)}` (e.g., `Explored Tồn kho on-hand & Điểm đặt hàng ROP`).
    - Multiple tools: `Explored ${count} tools (${names.slice(0, 2).join(", ")}...)`.
    - Active execution: `Running ${formatFriendlyToolName(activeTool)}...` or `Analyzing demand data...`.
  - Scaled down typography across `.tool-dropdown-*` elements (`10.5px` top, `10px` sub-row, `9.5px` item list, `8.5px` code tag).
- **Thinking Bubble Indicator**:
  - Restored `.message-bubble.is-thinking` indicator rendering "Thinking..." with animated bouncing dots when `isThinking && !message.text`.
  - Transitions seamlessly into markdown response as soon as streaming tokens arrive.
- **Verification**: TypeScript clean, ESLint clean, 13/13 backend tests passing.

### O. Deictic Context Binding & Multi-Question Capabilities
- **Deictic & Implicit Subject Resolution (`fallback.py`)**:
  - `extract_sku_mention` automatically binds to `selected_item_id` for any inventory/timing/forecast inquiry that omits an explicit SKU or uses pronouns (`this`, `it`, `thứ Ba tuần sau`, `có đứt hàng không`).
  - Preserved `/overview` bypass to allow portfolio-wide queries without binding to single SKU.
- **Tool Enrichments (`tools.py`)**:
  - `get_daily_forecast_series`: Added weekday names (`Monday (Thứ Hai)`), peak velocity day tagging (`🔥 PEAK DEMAND`), and running inventory depletion tracking pinpointing the exact stockout date (`⚠️ STOCKOUT REACHED`).
  - `get_sku_inventory_and_forecast`: Added recommended replenishment quantity (`Recommended Reorder Quantity`) and ROP definition formula.
  - `resolve_sku_item`: Added graceful handling for deictic keywords (`this`, `it`, `selected`, `current`).
- **Tool Routing & Metrics in System Prompt (`sku_agent.py`)**:
  - Added explicit tool routing guidelines mapping question types to respective tools.
  - Added metric definitions for ROP, Days of Supply, Deadstock, TreeSHAP.
  - Offline dispatcher dynamically routes queries by intent to the right tool.
- **Test Suite**:
  - Added `test_deictic_and_implicit_subject_binding`, `test_daily_forecast_series_enrichment`, and `test_end_to_end_deictic_and_timing_queries`.

### P. Step-by-Step Thinking Dropdown, Skill Query Routing & LAN HTTP UUID Fix
- **LAN HTTP `crypto.randomUUID` Bug Fix (`ForecastLoadingState.tsx`)**:
  - Implemented `generateSafeUUID()` RFC4122 v4 fallback that works seamlessly in non-secure contexts (`http://192.168.189.192:3000`) where `window.crypto.randomUUID` is unavailable.
- **Step-by-Step Thinking & Tool Dropdown (`ChatMessages.tsx`, `demand-ai.css`, `sku_agent.py`)**:
  - Replaced abstract grouping with chronological execution steps:
    - `Think ˅`: Collapsible dropdown displaying reasoning tokens in small monospace font.
    - `Use tool <tool_name>`: Flat row with active status dot and tool identifier (no unnecessary nested dropdown).
  - Streamed sequential step events (`type: "step"`, `step_type: "think" | "tool"`) through SSE and backend agent events.
- **Skill Intent Router & Question Coverage (`skills.py`, `sku_agent.py`, `testq.md`)**:
  - Created `skills.py` with 7 dedicated skills covering all question groups in `testq.md` (metrics, replenishment, daily timeline, TreeSHAP drivers, category peers, portfolio overview, hierarchy).
  - System prompt enriched with strict tool usage directives preventing raw JSON tool calls from leaking into message bubbles.
  - Resolved tricky queries like *"Yếu tố nào đang kéo tụt nhu cầu của sản phẩm này xuống mạnh nhất?"*.
- **Selected Language Adherence & Mismatch Banner (`ChatComposer.tsx`, `ChatPanel.tsx`)**:
  - Assistant responds strictly in the user's **selected language** (`language` state), regardless of what language the question was written in.
  - Added non-intrusive language mismatch banner suggesting switching when query language mismatches response language.
  - Expanded slash suggestions (`/overview`, `/reorder`, `/timeline`, `/drivers`, `/peers`, `/item`, `/help`).
- **OpenRouter Prioritization in Tests (`sku_agent.py`)**:
  - Prioritized `OPENROUTER_API_KEY` and `inclusionai/ling-3.0-flash-vl:free` during automated tests.

### Q. Authoritative Backend Wiki & Runtime One-Way Frontend Auto-Sync
- **Backend Authoritative Wiki (`backend/app/wiki/`)**:
  - Migrated `metrics.json` and `status.json` into `backend/app/wiki/` as the single source of truth for metric calculations and inventory health thresholds.
  - Added [`frontend/src/wiki/README.md`](file:///home/intern-tntthanh/D/Demand_AI_Application/frontend/src/wiki/README.md) alerting developers to edit in backend only.
- **Runtime One-Way Auto-Sync (`backend/app/wiki/sync.py`)**:
  - Created `sync_wiki_to_frontend()` which automatically compares mtimes/checksums and copies backend wiki files to `frontend/src/wiki/`.
  - Registered in server startup lifespan (`main.py`) and on every dynamic knowledge reload.
- **Live Update Checking & On-Demand Sync API (`backend/app/api/routes/wiki.py`)**:
  - Added REST endpoints: `GET /api/v1/wiki`, `GET /api/v1/wiki/metrics`, `GET /api/v1/wiki/status`, and `POST /api/v1/wiki/sync` for immediate on-demand synchronization without waiting for slow polling.
### R. On-Demand Wiki Skill Querying & Reasoning Pipeline
- **Lean Prompt Architecture**:
  - Removed full static Wiki dump (`format_wiki_prompt_context`) from the system prompt to prevent token bloat (~1,500 tokens saved per turn).
- **On-Demand Wiki Tool (`query_inventory_wiki`)**:
  - Tool queries `metrics.json` and `status.json` on-demand with multi-lingual alias support (ROP, DOS, Safety Stock, Deadstock, TreeSHAP, Critical, Monitor, Reorder).
  - Registered in `SKU_TOOLS` and mapped in `frontend/src/components/chat/ChatMessages.tsx` (`TOOL_NAME_MAP`).
- **Standard Reasoning & Execution Chain**:
  - Encoded user-specified pipeline: `user prompt > "what user intent" > tool > data > ... > "what i need to know" > wiki > response`.
  - Configured in `get_skills_system_prompt` and mirrored in `sku_agent.py` sequential thinking/tool event stream.
- **Verification**:
  - Added `test_query_inventory_wiki_tool` in `test_wiki_sync.py` (5/5 tests passing).
  - Frontend typecheck (`tsc --noEmit`) 100% clean.

### S. Reusable Clarification Card, Interactive Inquiry UI & Ignore Language Mismatch
- **Reusable `AssistantClarificationCard` Component (`AssistantClarificationCard.tsx`, `demand-ai.css`)**:
  - Replaced cramped/squished single-line banners with a unified, responsive interactive card UI.
  - Fixes vertical button wrapping bug (`white-space: nowrap; flex-shrink: 0;`).
  - Supports primary/secondary action buttons, icons, clean typography, and optional inline clarification text form.
- **Interactive Assistant Inquiries (4 Core Scenarios)**:
  1. **Automatic "Run Forecast" Prompt**: Triggers when user hasn't run the forecast yet (`forecastState !== "completed"`), providing a 1-click `[▶ Khởi chạy Dự báo ngay (Run Forecast)]` button that calls `handleRunForecast()`.
  2. **Intent Clarification**: When user prompt is vague or ambiguous (bare SKU), renders 4 interactive quick-action pills (`📦 Tồn kho & ROP`, `🔍 Động lực TreeSHAP`, `📅 Lịch trình 14 ngày`, `👥 So sánh cùng ngành`) plus an inline freeform input for instant clarification.
  3. **Run SHAP Trigger**: When user asks for SHAP drivers on an uncomputed/unselected SKU, offers `[⚡ Tính toán SHAP cho {sku}]` and `[📊 Xem tồn kho trước]`.
  4. **Language Mismatch Suggestion with Session Ignore**: Suggests switching response language when a mismatch is detected, and includes `[Giữ EN & Không nhắc lại]` / `[Keep VI & Don't ask again]` to suppress further prompts for users intentionally asking across languages.
- **Verification**:
  - Frontend TypeScript typecheck (`tsc --noEmit`): 0 errors.
  - Backend Wiki and SKU Agent tests: 25/25 passing (100%).

### T. Pre-Forecast Query Interceptor & Token Waste Prevention
- **Client-Side Guard (`DemandAIShell.tsx`)**:
  - Automatically intercepts user queries before sending them to the LLM backend if `forecastState !== "completed"`.
  - Halts stream initialization (`isGenerating` remains false), eliminating 100% of wasted OpenRouter / LLM tokens on un-grounded sessions.
  - Automatically emits an informative response explaining that a demand forecast must be run first to ground the assistant in actual stock, ROP, and TreeSHAP data.
  - Attaches a 1-click `[▶ Khởi chạy Dự báo ngay (Run Forecast)]` card that triggers `handleRunForecast()`.

### U. Disambiguation Popup, Typo/Concatenation Parser & Exact SKU Selection
- **Multi-SKU Disambiguation Tool (`show_clarification_card`)**:
  - Added `show_clarification_card(title, description, options, card_type)` tool to `tools.py` and registered in `SKU_TOOLS`.
  - Added Rule 6 in system prompts (EN/VI) instructing LLM when to ask with structured interactive options.
  - Connected SSE event `clarification` from backend streaming through `chatApi.ts` to `AssistantClarificationCard` in `ChatMessages.tsx`.
  - Removed brittle client-side regex scrapers from `ChatMessages.tsx`.
- **Selection Bug Fix**:
  - Fixed `qNorm.includes(skuNorm)` in `DemandAIShell.tsx` that caused `SKU-4884` to falsely match `SKU-48 (Toust_1)`.
  - Replaced with strict word-boundary regex (`\bsku[-_\s]?(\d+)\b`) and exact ID equality.
- **Product Name Parser & Typo Tolerance**:
  - Implemented boundary-aware normalization in `normalize_text_for_search` / `normalizeSearchText` separating letter-digit concatenations (`Onion20` $\rightarrow$ `Onion 20`, `Roll57` $\rightarrow$ `Roll 57`).
  - Added word-boundary matching and Python stdlib `difflib.SequenceMatcher` to handle spelling typos (`Onioon 20`, `Onnion_20` $\rightarrow$ `Onion 20`).
### V. User Intent Preservation, Backend Preset Wrapper & Workflow Anti-Spam Fixes
- **Lean Zero-LLM Backend Preset Wrapper (`backend/app/agent/presets.py`)**:
  - Implemented single self-contained Python module providing instant zero-token responses for `/help`, `/overview`, and core metric definitions (`rop là gì`, `days of supply là gì`, etc.) before compiling LLM agent.
  - No JSON sync overhead or redundant schemas; operates seamlessly inside backend request pipeline.
- **User Intent Preservation on Clarification & Disambiguation**:
  - Attached `originalQuery` and `productName` to `clarification_data` in `backend/app/agent/fallback.py`.
  - In `frontend/src/components/DemandAIShell.tsx: handleClarificationAction`: Replaced generic `"Detail about SKU-xxx"` with exact intent interpolation: substitutes the ambiguous product name with the chosen SKU in the user's prior query (e.g., *"Yếu tố nào đang kéo tụt nhu cầu của Onion 10?"* $\rightarrow$ *"Yếu tố nào đang kéo tụt nhu cầu của SKU-2457?"*), ensuring the LLM analyzes the user's intended question rather than dumping generic item information.
  - Fallback builds a grounded prompt utilizing the LLM's system context memory.
- **Card Anti-Spam & Auto-Dismissal Once Job is Done**:
  - In `frontend/src/components/chat/AssistantClarificationCard.tsx`: Replaced temporary 1.2s timeout with permanent `isAnswered` state; buttons disable immediately on click with active checkmark pill (`✓ {label}`).
  - In `frontend/src/components/chat/ChatMessages.tsx`: Clarification cards render exclusively on the latest active message (`index === messages.length - 1`), automatically disappearing once the user submits their choice or a new turn begins.
- **Elimination of Unsolicited UI Screen State Mutations**:
  - Removed automatic `handleSelectItem(mentionedItem)` on prompt submissions in `DemandAIShell.tsx`.
  - Removed unsolicited `select_sku` SSE emissions from `backend/app/agent/sku_agent.py` and no-op'd `onSelectSku` in `DemandAIShell.tsx`. Screen item selection remains strictly under user control.
- **Dead Code Pruning & Hoisting**:
  - Removed ~105 lines of unreachable `pendingPromptRef` logic in `DemandAIShell.tsx`.
  - Hoisted `normalizeSearchText`, `wordSimilarity`, `isFuzzyNameMatch` to module level.
  - Fixed `tools.py: resolve_sku_item` to use `selected_item_id` on deictic queries (`this`, `current`) and integer-normalized SKU matching (`SKU-10` $\rightarrow$ `SKU-010`).

---

## 2. Verification & Test Results
- **Frontend TypeScript (`tsc --noEmit`)**: Passed (0 errors).
- **Frontend Lint (`eslint`)**: Passed (0 errors, 0 warnings).
- **Backend Tests (`backend/.venv/bin/pytest`)**:
  - `test_preset_wrapper_and_intent_preservation`: PASSED (100%).
  - `test_resolve_sku_item_deictic_with_selected_item`: PASSED (100%).
  - `test_sku_tools_live_execution`: PASSED (100%).
  - `test_fallback_ambiguous_intent`: PASSED (100%).
---

## Session: 2026-09-17 — TreeSHAP Hallucination & Workflow Bug Fixes

### Issues Fixed

#### 1. TreeSHAP Hallucination in `skills.py`
- **Root Cause**: `answer_offline_skill_query` in `skills.py` had hardcoded fabricated percentages (`Sales Lags 55%, Pricing 25%...`) that were always returned regardless of whether TreeSHAP was calculated, ignoring the actual `shap_res` from `get_sku_shap_drivers`.
- **Fix**: Now checks `"NOT CALCULATED YET" in shap_res` before returning. If uncalculated, returns a factual notice (no numbers) directing user to activate TreeSHAP. If calculated, returns `shap_res` directly (real data).

#### 2. Online Mode TreeSHAP Guard (`sku_agent.py`)
- **Root Cause**: The `astream_events` loop had no `on_tool_end` handler, so when the LLM called `get_sku_shap_drivers` and got `NOT CALCULATED YET`, it would hallucinate made-up driver percentages in its text output.
- **Fix**: Added `elif event_kind == "on_tool_end":` handler that intercepts `get_sku_shap_drivers` output. If `NOT CALCULATED YET` is detected, emits a `run_shap` clarification card (▶ Kích hoạt TreeSHAP / 👁️ View Dashboard / 📊 View Inventory & ROP) before the LLM stream continues.

#### 3. "Run Forecast" Button in Message Bubble
- **Status**: Already fixed in previous session via `handleClarificationAction("run_forecast") → handleRunForecast()` at line 189 of `DemandAIShell.tsx`. Verified wiring: `ChatMessages.tsx` → `ChatPanel.tsx` → `DemandAIShell.tsx`.

### Files Modified
- `backend/app/agent/skills.py` — removed hardcoded fake TreeSHAP percentages; returns real data or factual not-calculated notice
- `backend/app/agent/sku_agent.py` — added `on_tool_end` SSE handler emitting `run_shap` clarification card when online agent uses `get_sku_shap_drivers` and SHAP is uncalculated

### Verification
- **Backend tests**: `test_preset_wrapper_and_intent_preservation` PASSED, `test_resolve_sku_item_deictic_with_selected_item` PASSED (2/2).
- **Frontend typecheck** (`tsc --noEmit`): PASSED (0 errors).

---

## Session: 2026-09-17 — Remove Offline Mock Generation

### Changes
- **Deleted** `answer_offline_skill_query` from [`skills.py`](backend/app/agent/skills.py) (~107 lines of hardcoded keyword-matched templates).
- **Removed** the entire `if not api_key:` offline block from [`sku_agent.py`](backend/app/agent/sku_agent.py) (~110 lines of mock pipeline simulation).
- **Replaced** with a 6-line clear error message: `"No API key configured. Please set OPENROUTER_API_KEY or OPENAI_API_KEY in .env"`.
- **Cleaned** all now-dead imports from both files (`compare_sku_peers`, `get_daily_forecast_series`, `get_portfolio_overview`, `get_sku_core_info`, `get_sku_inventory_and_forecast`, `query_inventory_wiki`, `match_skill`, `answer_offline_skill_query`, `re`).

### Net result
`skills.py`: 252 → 145 lines. `sku_agent.py`: ~215 lines removed. No offline mode — the LLM does all interpretation.

### Verification
- Import check: `from app.agent.skills import ...; from app.agent import sku_agent` → OK.
- Backend tests: 2/2 PASSED.

---

## Session: 2026-09-18 — Production Agent & TreeSHAP Day-Separated Breakdown

### Changes
- **Dynamic Model Selector**:
  - Added `BOOT_ID` to `/api/v1/chat/models` and active polling with re-sync in `ChatComposer.tsx`.
- **RAG & Non-Existent Item Guardrails**:
  - Live inventory aggregation across all 5,390 SKUs via `backend/app/agent/rag.py` (removed mock RAG & deleted `backend/app/assistant`).
  - Added Rule 8 (Non-Existent Item Invariant) to prevent substituting on-screen items for missing query SKUs.
  - Relaxed intent fallback guard in `backend/app/agent/fallback.py` to allow follow-ups like "what about this one?" to inherit analytical intent (Rule 9).
- **TreeSHAP Explainability (14-Day Cumulative Sum + 14-Day Separated Breakdown)**:
  - Updated `get_sku_shap_drivers(sku_or_id, day)` in `backend/app/agent/tools.py` to query `CoreForecastDailyPoint` for horizon days 1..14.
  - Preserved the 14-day cumulative sum (5 business factor groups + top positive/negative drivers) while adding separated day-by-day drivers (or single-day zoom when `day` argument is specified).
- **UI & Interaction Cleanup**:
  - Replaced `AssistantClarificationCard` with `AssistantInquiryCard.tsx` (item navigation confirmation prompt).
  - Replaced `DEMO CONVERSATION` in `ChatMessages.tsx` with localized `HÔM NAY` / `TODAY`.
  - Refined `handleAskAssistant` in `DemandAIShell.tsx` with bilingual prompts and removed non-existent uncertainty bounds.

### Verification
- Backend tests: `backend/.venv/bin/pytest backend/tests/test_sku_agent.py` — 11/11 PASSED (4.42s).
- Frontend typecheck: `npm --prefix frontend run typecheck` — 0 errors.

---

## Session: 2026-09-18 — UX Refinements (TreeSHAP Pending Dot, Pipeline Status, Auto New Session)

### Changes
- **Item TreeSHAP Pending Dot State (`item-shap-dot`)**:
  - In [`DemandAIShell.tsx`](frontend/src/components/DemandAIShell.tsx), when user confirms running TreeSHAP from `AssistantInquiryCard`, immediately sets `shap_status: "queued"` on the item in `forecastItems` and `selectedItem`.
  - Wired live job status callback in `loadItemShap` to transition states (`queued` -> `running` -> `completed`), immediately rendering the yellow pulsing `.item-shap-dot.is-pending` in `ForecastTable.tsx`.
- **Forecast Running / Pending Startup State**:
  - In [`ChatComposer.tsx`](frontend/src/components/chat/ChatComposer.tsx), added `forecastState === "loading"` state card displaying an in-progress status without the "Run Forecast" CTA button.
  - In [`DemandAIShell.tsx`](frontend/src/components/DemandAIShell.tsx), intercepted prompts sent while `forecastState === "loading"` with an in-progress notice rather than a "must run forecast" prompt.
- **Auto "New Session" On Forecast Completion**:
  - In [`DemandAIShell.tsx`](frontend/src/components/DemandAIShell.tsx), updated `handleForecastComplete` to automatically trigger `handleNewConversation()`, resetting prior unforecasted warnings or demo prompts into a clean live assistant session.

### Verification
- Frontend typecheck (`tsc --noEmit`): PASSED (0 errors).
- Backend hermetic tests (`pytest`): 11/11 PASSED (4.59s).

---

## Session: 2026-09-18 — Fix "View on Dashboard" Action Type & useEffect React Lifecycle

### Changes
- **Action Type Separation & Typings**:
  - Added `"view_item_on_screen"` to [`ClarificationOption.actionType`](frontend/src/types/chat.ts), resolving TS lint notice on type overlap.
  - In [`ChatMessages.tsx`](frontend/src/components/chat/ChatMessages.tsx), routed `view_item_on_screen` directly to avoid false interception by `run_shap`.
  - In [`DemandAIShell.tsx`](frontend/src/components/DemandAIShell.tsx), ensured `view_item_on_screen` invokes `handleSelectItem(item, false)` (no SHAP calculation triggered).
- **React Hook Lifecycle (`LeftPanel.tsx`)**:
  - Standardized `useEffect` dependency array to constant-sized `[selectedItem]`, eliminating Turbopack render mismatch error.
  - Defaulted uncalculated items in `LeftPanel` to `"detail"` tab with `"not_requested"` state.

### Verification
- Frontend lint (`eslint`): PASSED (0 errors, 0 warnings).
- Frontend typecheck (`tsc --noEmit`): PASSED (0 errors).
- Backend tests (`pytest`): 11/11 PASSED (5.24s).

---

## Session: 2026-09-21 — Frontend Anti-Freeze, TreeSHAP Fast-Inquiry Intent Fix & Wiki Driver Glossary

### Changes

#### 1. Machine Freeze Prevention: Polling & Reconnect Loop Cap
- In [`frontend/src/components/chat/ChatComposer.tsx`](frontend/src/components/chat/ChatComposer.tsx), added `consecutiveFailuresRef` tracking failed backend polling requests.
- Capped infinite reconnect loop at 5 attempts. When reached, transitions to `isOffline = true` and halts polling, rendering a manual `Reconnect ↻` button rather than freezing user machine with endless requests.

#### 2. TreeSHAP Fast-Inquiry SKU Disambiguation Fix
- In [`frontend/src/components/leftpanel/DailyForecastLineChart.tsx`](frontend/src/components/leftpanel/DailyForecastLineChart.tsx):
  - Fast-inquiry prompt generator previously only sent product name (e.g. `Roll_57`), causing regex number matching on day numbers (e.g. `Day 5`) to spuriously match `Roll_1`, `Roll_5`, `Melon_5`.
  - Appended exact SKU ID `(${item.sku})` to all fast-inquiry prompts.
- In [`backend/app/agent/fallback.py`](backend/app/agent/fallback.py):
  - In `evaluate_intent_guard`: If `selected_item_id` is supplied in context and matches the target item or candidate list, the intent guard bypasses ambiguity clarification and routes directly to the LLM agent.

#### 3. Wiki Enrichment for Specific TreeSHAP Drivers (Plain Language)
- Ground-truthed model features from `backend/app/pipeline/feature_engineering.py` and expanded [`backend/app/wiki/metrics.json`](backend/app/wiki/metrics.json) & [`frontend/src/wiki/metrics.json`](frontend/src/wiki/metrics.json).
- Added specific individual driver entries written in simple, intuitive language without complex math formulas (clear for a 15-year-old):
  - `sales_lag_1` (Yesterday's Sales): Momentum check.
  - `sales_lag_7` (Same Day Last Week): Weekly shopping habits (e.g. Saturday grocery rush).
  - `sales_lag_14` (Two Weeks Ago): Bi-weekly anchor to prevent anomalies from tricking the model.
  - `sales_order_interaction` (Basket Share): Distinguishes item popularity vs general store traffic.
  - `sales_price_interaction` (Revenue Momentum): Checks whether customer spend is healthy or price is hurting demand.
  - `sales_summary_stats` (Sales Range): Normal average, worst-day baseline, and peak rush numbers.
  - `max_discount` & `discounted_price`: Promotional demand boost and shelf-price sensitivity.
  - `discount_lags`: Post-sale slump ("discount hangover" as customer stockpiles clear).
  - `weekday`: Calendar effect (weekend surge vs quiet weekdays).
  - `sin_cos_dayofyear`: Yearly seasonal shifts (summer drinks vs winter soups).
  - `total_orders`: Warehouse-wide shopping volume.
  - `shap_base_value`: Normal baseline starting point.
- In [`frontend/src/wiki/index.tsx`](frontend/src/wiki/index.tsx), expanded `ALIAS_MAP` so UI tooltips resolve feature names seamlessly.

### Verification
- **Frontend Typecheck (`tsc --noEmit`)**: PASSED (0 errors).
- **Backend Wiki Tests (`pytest backend/tests/test_wiki_sync.py`)**: 5/5 PASSED.
- **Agent Tool Verification**: `query_inventory_wiki` verified live with `sales_lag_1` and `weekday`.

---

## Session: 2026-09-21 — Unified Detail Hover Card & TreeSHAP Day Parameter Resolution Fix

### Changes

#### 1. Combined Detail Hover Card & Fast Inquiry Button
- In [`frontend/src/components/leftpanel/DailyForecastLineChart.tsx`](frontend/src/components/leftpanel/DailyForecastLineChart.tsx):
  - Consolidated separate date bar (`detail-hover-date-bar`) and demand/stock banner (`detail-hover-banner`) into a single unified card (`detail-hover-unified-card`).
  - Added dedicated fast inquiry button with prompt: `"Tại sao ${item.sku} lại dự báo bán được tới ${activePoint.predicted.toLocaleString()} cái trong ngày ${activePoint.day}?"`.
- In [`frontend/src/styles/demand-ai.css`](frontend/src/styles/demand-ai.css):
  - Added styles for `.detail-hover-unified-card`, `.detail-hover-top-row`, `.detail-status-pill`, `.detail-hover-metrics-row`, and `.detail-fast-inquiry-btn`.

#### 2. TreeSHAP Tool Day Parsing Bug Fix (`get_sku_shap_drivers`)
- In [`backend/app/agent/tools.py`](backend/app/agent/tools.py):
  - Root cause: `get_sku_shap_drivers` expected `day: int`, failing with `TypeError` when the LLM passed string values (`"5"`, `"Day 5"`, `"ngày 5"`).
  - Enhanced `day` resolution to dynamically parse integers, day-string formats, and calendar dates (`2024-06-07`, `07/06`).
  - Fixed cache parsing in `get_sku_shap_drivers` to correctly read `daily_points` (`day`, `predicted`, `all_features_shap`) from disk cache.
  - Kept strict active-run scoping: uncalculated items return `NOT CALCULATED YET` to trigger the interactive `run_shap` confirmation card as per system prompt rules.
- In [`backend/app/agent/sku_agent.py`](backend/app/agent/sku_agent.py):
  - Added explicit instructions in `SYSTEM_PROMPT_VI` and `SYSTEM_PROMPT_EN` directing the LLM to pass the `day` parameter to `get_sku_shap_drivers` whenever the user asks about a specific day.

### Verification
- **Frontend Typecheck (`tsc --noEmit`)**: PASSED (0 errors).
- **Backend Wiki Tests (`pytest backend/tests/test_wiki_sync.py`)**: 5/5 PASSED.
- **Backend Sku Agent Tests (`pytest backend/tests/test_sku_agent.py`)**: 11/11 PASSED.

---

## Session: 2026-09-21 — TreeSHAP Lifecycle, LeftPanel Timer Glitch & Assistant Table Formatting

### Changes

#### 1. LeftPanel Default Tab & Breakdown View
- In [`frontend/src/components/LeftPanel.tsx`](frontend/src/components/LeftPanel.tsx):
  - Fixed tab switching so opening any item always defaults to `"breakdown"`, displaying `TreeShapComputingVisualizer` while computing and `ForecastBreakdownChart` once ready.

#### 2. TreeSHAP Lifecycle & Queue Preservation
- In [`frontend/src/components/DemandAIShell.tsx`](frontend/src/components/DemandAIShell.tsx) and [`ForecastTable.tsx`](frontend/src/components/workspace/ForecastTable.tsx):
  - Preserved `"queued"` $\rightarrow$ `"running"` $\rightarrow$ `"completed"` lifecycle transitions.
  - Table status dot shows pulsing yellow (`is-pending`) during both `"queued"` and `"running"`, switching to green (`is-ready`) upon completion.
  - Removed redundant TreeSHAP notice (*"⚠️ Note: TreeSHAP drivers have been successfully calculated for this item..."*).

#### 3. LeftPanel Timer Glitch & Pill Formatting Fix
- In [`frontend/src/components/LeftPanel.tsx`](frontend/src/components/LeftPanel.tsx):
  - **Root Cause**: Polling updates replaced `selectedItem` reference every few seconds, triggering the timer reset effect and resetting `elapsedMs` to `0.0s`.
  - **Fix**: Keyed reset effect to `currentItemId` (`selectedItem?.id`) so background polling does not reset the timer.
  - Formatted timer pill to show `%` progress only when active (`shapStatus === "running"`), showing pure timer in queue (`1.2s`).

#### 4. Direct `/driver` & TreeSHAP Query Short-Circuit
- In [`backend/app/agent/sku_agent.py`](backend/app/agent/sku_agent.py):
  - When user directly asks about drivers or TreeSHAP and the item is uncalculated, the agent presents only the `run_shap` `AssistantInquiryCard` and halts without dumping unrelated inventory/forecast data.

#### 5. Assistant Markdown Table Output Encouragement
- In [`backend/app/agent/sku_agent.py`](backend/app/agent/sku_agent.py) & [`backend/app/agent/skills.py`](backend/app/agent/skills.py):
  - Added Rule 10 in both Vietnamese and English system prompts and skills frameworks instructing the model to actively present multi-metric summaries, daily timelines, TreeSHAP drivers, and category comparisons in standard Markdown table format (`| Metric | Value | Status |`).

#### 6. 15-Minute Session Expiry & Auto-Reload
- In [`frontend/src/components/DemandAIShell.tsx`](frontend/src/components/DemandAIShell.tsx):
  - Changed session inactivity timeout from 5 minutes to 15 minutes (`SESSION_TTL_MS = 15 * 60 * 1000`).
  - Implemented auto-reload trigger (`window.location.reload()`) when a session expires: cleans up `sessionStorage` and `localStorage`, notifies backend `/api/v1/forecast/sessions/expire`, and reloads the browser window.
  - Added `visibilitychange` and `focus` event listeners to immediately catch expired sessions when returning to background/sleeping browser tabs.

#### 7. Detail Tab Chart Day 1 Default & Fast-Inquiry Button Activation
- In [`frontend/src/components/leftpanel/DailyForecastLineChart.tsx`](frontend/src/components/leftpanel/DailyForecastLineChart.tsx):
  - Initialized `setDayIdx` to `1` (Day 1) instead of `0` (Day 0 / baseline), immediately displaying Day 1 forecast trajectory and showing the fast-inquiry button on chart load.
  - Kept fast-inquiry button strictly restricted to forecast days (`activePoint.day > 0`), omitting it for Day 0 baseline.

#### 8. Page Reload TreeSHAP Mirror Restoration Fix
- In [`frontend/src/components/DemandAIShell.tsx`](frontend/src/components/DemandAIShell.tsx):
  - **Root Cause**: Bulk `/forecast/live` returns items with summary `grouped_drivers` but omits per-day `top_positive_features` / `top_negative_features` to keep payload small. On page reload, `selectedItemId` restoration only called `setSelectedItem(it)` without `handleSelectItem(it)`, and `handleSelectItem` prematurely returned early because `item.grouped_drivers.length > 0` was true even though `daily_points` had no SHAP features.
  - **Fix**: Replaced early-return condition with `hasFullShap()` to ensure daily SHAP attributions exist before skipping fetch. On reload, `DemandAIShell` now calls `handleSelectItem(it)`, immediately retrieving cached full 14-day TreeSHAP drivers from backend into `selectedItem`.
- In [`frontend/src/components/leftpanel/DailyForecastLineChart.tsx`](frontend/src/components/leftpanel/DailyForecastLineChart.tsx):
  - Render skeleton loader whenever `posDrivers` and `negDrivers` are empty to prevent an empty blank section while attributions load.

## Session: 2026-09-21 — Non-Existent SKU Guard, Warehouse Chips & Multi-Category Filter

### Changes

#### 1. Non-Existent SKU Guardrail (`backend/app/agent/fallback.py`)
- **Root Cause**: When a user inquired about an explicit SKU or bare code not present in inventory (e.g. `sku 9999`, `SKU-9999`, `item 9999`, `9999`), `evaluate_intent_guard` fell through to `is_fallback = False`, attempting to route through LLM and wasting tokens / latency.
- **Fix**: Added guard in `evaluate_intent_guard` right after `sku_mention = extract_sku_mention(query, selected_item_id)`. If `sku_mention` exists but `resolve_sku_item(sku_mention)` is `None`, immediately returns `fallback_type = "sku_not_found"`:
  - VI: `"⚠️ Không tìm thấy mặt hàng **{sku_mention}** trong hệ thống dữ liệu kho và dự báo. Vui lòng kiểm tra lại mã SKU."`
  - EN: `"⚠️ No item found for **{sku_mention}** in the inventory and forecast system. Please verify the SKU code."`
  - Attaches `clarify_intent` interactive inquiry card allowing the user to search or enter an existing SKU.
- Added test coverage in `backend/tests/test_sku_agent.py` asserting `sku_not_found` fallback on `sku 9999` and `/drivers SKU-9999`.

#### 2. Warehouse Chip in Forecast List & Left Panel
- In [`frontend/src/components/workspace/ForecastTable.tsx`](frontend/src/components/workspace/ForecastTable.tsx):
  - Rendered `warehouse-chip` near `category-chip` in `.item-sku-row`:
    ```tsx
    {item.warehouse && (
      <span className="category-chip warehouse-chip" title={`Warehouse: ${item.warehouse}`}>
        {item.warehouse}
      </span>
    )}
    ```
- In [`frontend/src/components/LeftPanel.tsx`](frontend/src/components/LeftPanel.tsx):
  - Rendered `warehouse-chip` near `category-chip` in `.item-detail-sku-row`.
- In [`frontend/src/styles/demand-ai.css`](frontend/src/styles/demand-ai.css):
  - Added `.category-chip.warehouse-chip` with distinct subtle blue styling (`background: #f0f7ff; color: #1e40af; border-color: #dbeafe;`).

#### 3. Multi-Category Selection Filter (`frontend/src/components/workspace/ForecastTable.tsx`)
- Migrated `selectedCategory` string state to `selectedCategories: string[]`.
- Updated table filtering logic: matches items whose `category` is in `selectedCategories` (when non-empty).
- Updated filter dropdown UI:
  - Clicking any category toggles it in/out of `selectedCategories`.
  - Clicking "All" clears all categories.
  - Added "Clear ({selectedCategories.length})" action button in category filter header.
  - Active filter badge & indicator dot highlight whenever any category is selected.

### Verification
- **Frontend Typecheck (`tsc --noEmit`)**: PASSED (0 errors).
- **Backend Tests (`pytest backend/tests/test_sku_agent.py`)**: 11/11 PASSED.

---

## Session: 2026-09-21 — Suggest View Item, Smooth Stream Fade-in, Smart Scroll & Latest Message Dot

### Changes

#### 1. Suggest View Item on Item Mismatch (`backend/app/agent/sku_agent.py`)
- When a user asks about an SKU or item that differs from `selected_item_id` currently displayed in the workspace, the assistant appends an interactive clarification option to open that item on screen (`👁️ Mở trên Dashboard (${target_sku})` / `👁️ Open on Dashboard (${target_sku})`).
- Implemented `normalize_sku_code()` helper to compare SKU IDs cleanly regardless of padding (`SKU-0010` vs `SKU-10`).
- Guarded so it only attaches when no other clarification card was already emitted.

#### 2. Smooth Text Stream & Fade-in Animation (`frontend/src/styles/demand-ai.css`, `frontend/src/components/chat/ChatMessages.tsx`)
- Added `@keyframes tokenFadeIn` to `.msg-paragraph` so incoming tokens and paragraphs transition into view smoothly.
- Added `.streaming-cursor` with `@keyframes cursorPulse` rendered dynamically at the end of the streaming message content while generation is active.

#### 3. Free Chat Scrolling (Smart Sticky Scroll) (`frontend/src/components/chat/ChatMessages.tsx`)
- Replaced unconditional `scrollTop = scrollHeight` on message updates with scroll position tracking via `isNearBottomRef`.
- Auto-scrolls only when the user is already near the bottom (`scrollHeight - scrollTop - clientHeight < 70`) or when a new user turn begins, allowing users to freely scroll up and read without being snapped down by incoming stream tokens.

#### 4. Green Dot on Top-Right Corner of Latest Message (`frontend/src/components/chat/ChatMessages.tsx`, `frontend/src/styles/demand-ai.css`)
- Rendered `.latest-message-dot` on the top-right corner of `.message-bubble` when `index === messages.length - 1`.
- Styled with emerald green indicator (`#10b981`) and subtle glow shadow.

### Verification
- **Frontend Typecheck (`tsc --noEmit`)**: PASSED (0 errors).
- **Backend Tests (`pytest backend/tests/test_sku_agent.py`)**: 11/11 PASSED.

---

## Session: 2026-09-21 — Preset Prompt Language Consistency, TreeSHAP Disclaimer Removal & Unclicked Session Reload Fix

### Changes

#### 1. Language-Aware Preset Prompts & Actions
- In [`backend/app/agent/fallback.py`](backend/app/agent/fallback.py) and [`backend/app/agent/sku_agent.py`](backend/app/agent/sku_agent.py):
  - Fixed hardcoded Vietnamese payloads on `opt-view-2` and `opt-shap-3` to respect `lang == "en"` (`View on-hand inventory, ROP, and forecast for {sku}`).
- In [`frontend/src/components/leftpanel/ForecastBreakdownChart.tsx`](frontend/src/components/leftpanel/ForecastBreakdownChart.tsx) and [`frontend/src/components/LeftPanel.tsx`](frontend/src/components/LeftPanel.tsx):
  - Wired `language` prop into `ForecastBreakdownChart` and localized fast-inquiry prompt on the breakdown chart sparkle button.
- In [`frontend/src/components/chat/ChatMessages.tsx`](frontend/src/components/chat/ChatMessages.tsx):
  - Localized `DEFAULT_SUGGESTIONS` and `run_shap` fallback dispatch based on `language`.

#### 2. Complete Removal of Boilerplate "Run TreeSHAP" Note
- In [`backend/app/agent/tools.py`](backend/app/agent/tools.py):
  - Removed `Action: Advise the user to click 'Run TreeSHAP' for {sku} in the workspace to compute driver explainability.` which previously caused the LLM to write out `"Note: TreeSHAP drivers have not been calculated for this item. Click 'Run TreeSHAP' in the workspace..."`.
- In [`backend/app/agent/sku_agent.py`](backend/app/agent/sku_agent.py):
  - Enforced Rule 6 in both VI and EN system prompts strictly prohibiting outputting TreeSHAP disclaimers or boilerplate instructions.
  - When direct `/driver` or TreeSHAP inquiries encounter uncalculated items, ends cleanly after emitting the interactive inquiry card without appending redundant text.

#### 3. Auto-Reload TreeSHAP for Unclicked Session-Reloaded Items
- In [`backend/app/api/routes/forecast.py`](backend/app/api/routes/forecast.py):
  - In `_load_all_inventory_items`, pre-loaded `computed_shap_map` from `CoreForecastItemSummary` for the active run so restored sessions immediately tag computed items with `shap_status: "completed"` and load their `grouped_drivers`.
- In [`frontend/src/components/DemandAIShell.tsx`](frontend/src/components/DemandAIShell.tsx):
  - In `onShapCompleted`, automatically dispatches `loadItemShap` to populate `itemCacheRef`, `forecastItems`, and `selectedItem` with the full 14-day daily SHAP feature vectors immediately without requiring the user to manually click the item first.

### Verification
- **Frontend Typecheck (`tsc --noEmit`)**: PASSED (0 errors).
- **Backend Tests (`pytest backend/tests/test_sku_agent.py`)**: 11/11 PASSED.

---

## 2026-09-21: Suggest View Item Card Fix for Unselected Target Item

### Root Cause
In [`frontend/src/components/DemandAIShell.tsx`](frontend/src/components/DemandAIShell.tsx), `activeSku` was computed as `mentionedItem ? (mentionedItem.sku || String(mentionedItem.id)) : (selectedItem?.sku ...)`. When a user asked about an item different from the selected item, `mentionedItem` resolved to the target item and was transmitted as `selected_item_id`. Consequently, the backend compared the target SKU with `selected_item_id`, perceived them as identical (already on-screen), and skipped generating the suggestion card. Additionally, tool executions passing query or item names without standard "SKU-" prefix did not resolve to SKU strings in `sku_agent.py`.

### Changes
1. **Frontend Context (`DemandAIShell.tsx`)**:
   - Replaced `activeSku` with `onScreenSku` computed strictly from `selectedItem`.
   - Transmitted `onScreenSku` as `selectedItemId` to `sendChatStream` and `sendChatMessage`.
2. **Backend Tool SKU Resolution (`sku_agent.py`)**:
   - Added item resolution fallback in `on_tool_start` for tool input queries/names (`resolve_sku_item`), ensuring `last_queried_sku` accurately resolves product names to their canonical SKU.
3. **Automated Test (`test_sku_agent.py`)**:
   - Added `@pytest.mark.anyio` test `test_suggest_view_item_when_different_from_selected` verifying that asking about an SKU different from `selected_item_id` reliably yields the `"select_item"` suggestion card.

---

## 2026-09-21: Multi-Session Isolation, DB Expiry Cleanup & Single Source of Truth for Predictions & TreeSHAP

### Root Cause
1. **Prediction & Driver Discrepancy**: The rendered UI loaded live forecasts from PostgreSQL RDS (`forecast_item_summary` and `forecast_daily_points`), whereas the Assistant's item resolution tools (`resolve_sku_item`, `get_sku_details`) relied on in-memory static parquet data from startup (`_ALL_FORECAST_ITEMS_CACHE`). TreeSHAP lookups also defaulted to `is_latest == True` rather than the user's active session run.
2. **Concurrent Session Overwrites**: When two users generated forecasts simultaneously, saving a new run set all previous runs' `is_latest` flag to `False` without tracking session keys. Furthermore, session expiration (`/sessions/expire`) only cleared local disk artifacts, leaving orphan forecast runs and data in PostgreSQL RDS.

### Changes
1. **Forecast Persistence Service (`forecast_persistence.py`)**:
   - Added `session_key: str | None` and `allow_overwrite: bool = True` to `save_forecast_run`: automatically tags `model_version` with `[session:{session_key}]` and preserves existing runs when overwrite is disallowed.
   - Added `delete_forecast_session(db, session_key)`: cleanly removes `CoreForecastRun` by UUID or session tag, triggering DB foreign key cascade deletion for all associated item summaries and daily points.
2. **Session Expiry API (`forecast.py`)**:
   - Updated `POST /api/v1/forecast/sessions/expire` to execute `delete_forecast_session`, cleaning up both RDS tables and local files on expiration.
   - Updated `save_current_forecast` to accept `session_key` and `allow_overwrite`.
3. **Session-Aware Forecast Jobs (`forecast_jobs.py`)**:
   - Propagated `request_id` as `session_key` through `ForecastJobs.start`, `_run`, and `run_live_pipeline`.
4. **Single Source of Truth in Tools & Assistant (`tools.py`, `sku_agent.py`, `chat.py`)**:
   - Introduced `active_session_id` ContextVar.
   - In `tools.py`: Added `_enrich_item_with_live_db` to `resolve_sku_item` so `get_sku_details` and `get_sku_shap_drivers` query the exact database forecast run active in the user's session.
   - In `chat.py`: Added `session_id` to `ChatRequest` and forwarded it to `stream_sku_agent_response`.
5. **Frontend Context Propagation (`chatApi.ts`, `DemandAIShell.tsx`)**:
   - Added `sessionId` parameter to `sendChatStream` and `sendChatMessage`.
   - Transmitted `activeSessionId` (`session?.id || selectedItem?.run_id`) with all chat requests.
6. **Automated Tests**:
   - Added `test_expire_session_prunes_db` in `backend/tests/test_forecast_api.py`.
   - Verified complete backend suite: 83 passed, 11 skipped. Frontend `typecheck`: 0 errors.

---

## 2026-09-21: Slash Suggestion Popup Simplification

### Changes
1. **Removed Invented Information (`ChatComposer.tsx`)**:
   - Stripped fabricated labels (`label`: "Central Distribution Hub", "Logistics Forwarding Center", etc.) and countries (`region`: "Czech Republic", "Hungary", "Germany") from `SYSTEM_WAREHOUSES`.
   - Kept canonical warehouse identifiers matching `core.inventory` (`Prague_1`, `Prague_2`, `Prague_3`, `Brno_1`, `Budapest_1`, `Frankfurt_1`, `Munich_1`, `All Warehouses`).
2. **Removed Action Hint & Simplified Layout (`ChatComposer.tsx`, `demand-ai.css`)**:
   - Removed `.wh-action-hint` ("Click row to insert, or export:").
   - Transformed warehouse suggestions into a clean, compact single-row layout displaying the warehouse tag on the left and direct export actions (📊 PDF / 📦 CSV) on the right.











