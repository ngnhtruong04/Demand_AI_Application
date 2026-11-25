"""pipeline.py — Lightweight mock test SSE route for UI testing.

Provides real-time callback emission without touching RDS:
Step 1: Load data (mock)
Step 2: Feature engineering (mock/synthetic)
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

router = APIRouter()


@router.get(
    "/test-run",
    summary="UI API Test: Mock Pipeline SSE Stream",
    description="Streams real-time step callback emissions for frontend testing without touching DB. Set fast=true for snappy Swagger UI testing.",
)
async def test_run_pipeline_sse(
    mock_mode: bool = Query(default=True, description="Always True for UI API test"),
    fast: bool = Query(default=False, description="Fast mode with reduced sleep intervals (recommended for Swagger UI testing)"),
    use_inactive_items: bool = Query(default=False, description="Whether to include items with 10+ days no sales (default False filters them out immediately after load)"),
) -> StreamingResponse:
    """Stream real callback events with responsive delay intervals."""

    async def _event_generator() -> AsyncGenerator[str, None]:
        scale = 0.06 if fast else 0.25
        steps = [
            {
                "id": 1,
                "step": "data_collection",
                "title": "1. Data Collection",
                "logs": [
                    {"type": "info", "tag": "INFO", "text": "Connecting to data source & verifying credentials..."},
                    {"type": "info", "tag": "INFO", "text": "Loading historical sales orders & inventory records..."},
                    {"type": "success", "tag": "DONE", "text": "2,723 records collected across warehouses."},
                ],
                "delay": 0.9 * scale,
            },
            {
                "id": 2,
                "step": "data_validation_and_cleaning",
                "title": "2. Data Preprocessing",
                "logs": [
                    {"type": "info", "tag": "INFO", "text": "Validating schema constraints & observation keys..."},
                    {"type": "info", "tag": "INFO", "text": "Imputing missing values & zero-demand streaks..."},
                    {"type": "success", "tag": "DONE", "text": "Schema verified & 3 records cleaned."},
                ],
                "delay": 0.9 * scale,
            },
            {
                "id": 3,
                "step": "feature_engineering",
                "title": "3. Feature Engineering",
                "logs": [
                    {"type": "info", "tag": "INFO", "text": "Computing calendar lags & rolling momentum..."},
                    {"type": "info", "tag": "INFO", "text": "Generating discount interaction aggregates..."},
                    {"type": "success", "tag": "DONE", "text": "12 features engineered across 14d future horizon."},
                ],
                "delay": 1.0 * scale,
            },
            {
                "id": 4,
                "step": "forecasting",
                "title": "4. Ready for Forecast",
                "logs": [
                    {"type": "info", "tag": "INFO", "text": "Initializing demand projection models..."},
                    {"type": "info", "tag": "INFO", "text": "Calculating point forecasts & confidence intervals..."},
                    {"type": "success", "tag": "DONE", "text": "14-day forecasts generated for all items."},
                ],
                "delay": 0.8 * scale,
            },
        ]

        for s in steps:
            # Emit running status with initial log
            yield "data: " + json.dumps({"id": s["id"], "step": s["step"], "status": "running", "title": s["title"], "log": s["logs"][0]}, ensure_ascii=False) + chr(10) + chr(10)
            await asyncio.sleep(s["delay"] / 2)

            # Emit in-progress log
            yield "data: " + json.dumps({"id": s["id"], "step": s["step"], "status": "running", "title": s["title"], "log": s["logs"][1]}, ensure_ascii=False) + chr(10) + chr(10)
            await asyncio.sleep(s["delay"] / 2)

            # Emit step done with success log
            yield "data: " + json.dumps({"id": s["id"], "step": s["step"], "status": "done", "title": s["title"], "log": s["logs"][2]}, ensure_ascii=False) + chr(10) + chr(10)
            await asyncio.sleep(0.04 if fast else 0.08)

        # Emit completion
        yield "data: " + json.dumps({"step": "complete", "status": "done", "message": "Pipeline execution completed."}, ensure_ascii=False) + chr(10) + chr(10)

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
