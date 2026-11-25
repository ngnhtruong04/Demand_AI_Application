# Agent & Assistant Engineering Guardrails

## 1. Intent Clarification Before Destructive Cleanup
- When instructed to "clean up", "combine", or "remove old files", never delete directories or modules containing tools, tests, or legacy utilities without explicit confirmation if there is any doubt about user intent.
- If a cleanup request is ambiguous about whether legacy code contains useful references or tests, stop and ask the user before deleting.

## 2. Prompt Refactoring & Skill Invariants
- When expanding or refactoring system prompts to improve intent understanding or reasoning pipelines, **never omit or abbreviate explicit tool/skill mappings** (`CORE SKILLS & TOOLS`).
- Always preserve:
  1. The operational user-intent understanding protocol (business decisions behind commands).
  2. The explicit enumeration of every supported skill, its bound tool, and its specific responsibilities.

## 3. Real Data & Architecture Invariants
- Zero mock data in assistant or forecasting services: all inventory, forecasts, and drivers must route through live database caches (`_load_all_inventory_items()`).
- Single unified agent module: All assistant reasoning, RAG context generation, and LangChain tools live in `backend/app/agent/`.
