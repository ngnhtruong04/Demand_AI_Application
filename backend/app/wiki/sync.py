"""app.wiki.sync — Runtime One-Way Backend-to-Frontend Wiki Sync & Live Knowledge Loader."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import shutil
from typing import Any

logger = logging.getLogger(__name__)

BACKEND_WIKI_DIR = Path(__file__).resolve().parent
# Find frontend/src/wiki relative to project root
PROJECT_ROOT = BACKEND_WIKI_DIR.parents[2]
FRONTEND_WIKI_DIR = PROJECT_ROOT / "frontend" / "src" / "wiki"

_WIKI_CACHE: dict[str, Any] = {}
_LAST_MTIMES: dict[str, float] = {}


def sync_wiki_to_frontend() -> bool:
    """Sync metrics.json and status.json from backend to frontend (one-way, backend -> frontend)."""
    if not FRONTEND_WIKI_DIR.exists():
        return False

    updated = False
    for filename in ("metrics.json", "status.json"):
        src = BACKEND_WIKI_DIR / filename
        dst = FRONTEND_WIKI_DIR / filename
        if not src.exists():
            continue

        # Check if destination doesn't exist or content differs
        if not dst.exists() or src.read_bytes() != dst.read_bytes():
            try:
                shutil.copy2(src, dst)
                logger.info("Auto-synced backend wiki %s -> frontend wiki %s", src, dst)
                updated = True
            except OSError as exc:
                logger.warning("Failed to sync %s to frontend: %s", filename, exc)

    return updated


def get_wiki_data(force_reload: bool = False) -> dict[str, Any]:
    """Retrieve live metrics and status wiki definitions, reloading if files changed on disk."""
    global _WIKI_CACHE, _LAST_MTIMES

    files_to_check = {
        "metrics": BACKEND_WIKI_DIR / "metrics.json",
        "status": BACKEND_WIKI_DIR / "status.json",
    }

    needs_reload = force_reload or not _WIKI_CACHE

    for key, path in files_to_check.items():
        if path.exists():
            mtime = path.stat().st_mtime
            if mtime != _LAST_MTIMES.get(key):
                needs_reload = True
                _LAST_MTIMES[key] = mtime

    if needs_reload:
        data: dict[str, Any] = {}
        for key, path in files_to_check.items():
            if path.exists():
                try:
                    data[key] = json.loads(path.read_text(encoding="utf-8"))
                except Exception as exc:
                    logger.error("Error reading wiki file %s: %s", path, exc)
                    data[key] = {}
            else:
                data[key] = {}
        _WIKI_CACHE = data
        # Ensure frontend is synchronized on any reload
        sync_wiki_to_frontend()

    return _WIKI_CACHE


def format_wiki_prompt_context(lang: str = "vi") -> str:
    """Format authoritative wiki definitions into a markdown prompt context block for the assistant."""
    data = get_wiki_data()
    metrics = data.get("metrics", {}).get("metrics", {})
    statuses = data.get("status", {}).get("statuses", {})

    lines: list[str] = []
    if lang == "vi":
        lines.append("KIẾN THỨC NỀN TẢNG TỪ DEMANDAI WIKI (QUY TẮC & CÔNG THỨC CHUẨN):")
        for m_key, m in metrics.items():
            title = m.get("title", m_key)
            calc = m.get("calculation", "")
            summary = m.get("summary", "")
            lines.append(f"• {title}: {summary} (Công thức: `{calc}`)")
        lines.append("QUY TẮC PHÂN HẠNG TRẠNG THÁI TỒN KHO:")
        for s_key, s in statuses.items():
            calc = s.get("calculation", "")
            summary = s.get("summary", "")
            lines.append(f"• {s_key}: {summary} (Điều kiện: `{calc}`)")
    else:
        lines.append("AUTHORITATIVE DEMANDAI WIKI KNOWLEDGE (OFFICIAL FORMULAS & RULES):")
        for m_key, m in metrics.items():
            title = m.get("title", m_key)
            calc = m.get("calculation", "")
            summary = m.get("summary", "")
            lines.append(f"• {title}: {summary} (Formula: `{calc}`)")
        lines.append("INVENTORY HEALTH STATUS CRITERIA:")
        for s_key, s in statuses.items():
            calc = s.get("calculation", "")
            summary = s.get("summary", "")
            lines.append(f"• {s_key}: {summary} (Condition: `{calc}`)")

    return "\n".join(lines)
