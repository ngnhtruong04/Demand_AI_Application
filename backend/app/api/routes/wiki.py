"""app.api.routes.wiki — Authoritative Inventory Wiki & Knowledge Base API."""
from __future__ import annotations

from typing import Any
from fastapi import APIRouter

from app.wiki.sync import get_wiki_data, sync_wiki_to_frontend

router = APIRouter()


@router.get(
    "",
    summary="Get Complete Authoritative Inventory Wiki",
    description=(
        "Retrieves all official inventory metrics definitions, calculation formulas, and status thresholds. "
        "Automatically checks and synchronizes the authoritative wiki state to the frontend repository."
    ),
    response_description="Consolidated wiki payload containing metrics, status definitions, and sync status flag.",
)
@router.get("/", include_in_schema=False)
def get_all_wiki() -> dict[str, Any]:
    """Retrieve all authoritative wiki data and ensure frontend sync."""
    data = get_wiki_data()
    synced = sync_wiki_to_frontend()
    return {
        "metrics": data.get("metrics"),
        "status": data.get("status"),
        "synced": synced,
    }


@router.get(
    "/metrics",
    summary="Get Inventory Metrics Formulas & Definitions",
    description=(
        "Retrieves authoritative formulas, calculation rationale, and guidance for key supply chain metrics "
        "including Reorder Point (ROP), Days of Supply (DOS), Safety Stock, TreeSHAP drivers, and Lead Time."
    ),
    response_description="Dictionary mapping metric IDs to calculation formulas and explanations.",
)
def get_wiki_metrics() -> dict[str, Any]:
    """Retrieve metrics definitions from backend authoritative wiki."""
    data = get_wiki_data()
    return data.get("metrics", {})


@router.get(
    "/status",
    summary="Get Inventory Health Status Thresholds",
    description=(
        "Retrieves operational criteria and classification boundaries for SKU inventory triage "
        "including In Stock, Monitor, Reorder, Critical (Stockout Risk), and Deadstock (Capital Trap)."
    ),
    response_description="Dictionary mapping status labels to business rules and threshold parameters.",
)
def get_wiki_status() -> dict[str, Any]:
    """Retrieve inventory status rules from backend authoritative wiki."""
    data = get_wiki_data()
    return data.get("status", {})


@router.post(
    "/sync",
    summary="Trigger On-Demand Wiki Synchronization",
    description=(
        "Manually synchronizes backend authoritative inventory markdown files directly to the frontend "
        "wiki repository, ensuring 100% parity across UI tooltips, chat knowledge, and documentation."
    ),
    response_description="Synchronization result status and confirmation message.",
)
def post_sync_wiki() -> dict[str, Any]:
    """Manually trigger immediate on-demand synchronization from backend to frontend wiki."""
    updated = sync_wiki_to_frontend()
    return {
        "status": "success",
        "updated": updated,
        "message": "Wiki synchronized from backend to frontend successfully.",
    }
