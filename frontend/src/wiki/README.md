# Frontend Wiki Data Notice

> [!WARNING]
> **DO NOT EDIT `metrics.json` OR `status.json` IN THIS DIRECTORY DIRECTLY.**
>
> All authoritative inventory metric definitions, formulas, and status thresholds are maintained in the backend:
> **Path**: [`backend/app/wiki/`]
> - [`backend/app/wiki/metrics.json`]
> - [`backend/app/wiki/status.json`]
## How It Works
1. **Source of Truth**: The backend [`backend/app/wiki/`] is the single source of truth for all formulas and definitions used by both the DemandAI Agent and the UI.
2. **One-Way Auto-Sync**: The backend automatically syncs `metrics.json` and `status.json` into this directory (`frontend/src/wiki/`) at runtime and on demand whenever changes are detected.
3. **Any manual edits here will be overwritten by the backend sync.** To make updates, edit the files in `backend/app/wiki/`.
