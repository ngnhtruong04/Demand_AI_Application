"""DemandAI Enterprise Retail Forecasting & Supply Chain Optimization Platform API."""
from contextlib import asynccontextmanager
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute

from app.api.router import api_router
from app.core.config import settings

logger = logging.getLogger(__name__)


def custom_generate_unique_id(route: APIRoute) -> str:
    """Generate clean, kebab-case operation IDs without underscores for Swagger UI deep-linking compatibility."""
    tag = route.tags[0] if route.tags else "api"
    name = route.name.replace("_", "-")
    return f"{tag}-{name}"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Preload trained ensemble models into RAM during server startup for zero-latency inference."""
    try:
        from app.pipeline.recursive_ensemble import get_global_models, MODELS_DIR
        logger.info("Preloading ensemble models into memory...")
        get_global_models(MODELS_DIR)
        logger.info("Ensemble models preloaded successfully.")
    except Exception as exc:
        logger.warning("Optional startup model preload skipped: %s", exc)

    try:
        from app.wiki.sync import sync_wiki_to_frontend
        sync_wiki_to_frontend()
        logger.info("Auto-synchronized authoritative wiki from backend to frontend.")
    except Exception as exc:
        logger.warning("Optional wiki sync skipped: %s", exc)

    yield


tags_metadata = [
    {
        "name": "forecast",
        "description": (
            "**Demand Forecasting & Simulation Engine**: 14-day recursive multi-model ensemble (CatBoost, LightGBM, XGBoost), "
            "TreeSHAP value driver explainability, Two-Way Price Decision & Elasticity Engine (discounts & price hikes), "
            "executive multi-page PDF report generation, and PO replenishment CSV exports."
        ),
    },
    {
        "name": "chat",
        "description": (
            "**DemandAI Conversational Assistant**: Enterprise-grade multi-turn agent with 9 specialist analytical skills, "
            "dynamic intent guard filters, real-time RAG grounding over inventory telemetry, and Server-Sent Events (SSE) token streaming."
        ),
    },
    {
        "name": "wiki",
        "description": (
            "**Authoritative Inventory Wiki**: Centralized calculation formulas, business rules, and status threshold criteria "
            "for ROP, Days of Supply (DOS), Safety Stock, Deadstock triage, and on-demand frontend synchronization."
        ),
    },
    {
        "name": "pipeline",
        "description": (
            "**ETL & Execution Pipeline**: Real-time streaming pipeline callbacks for data ingestion, cleaning, validation, "
            "and model preparation with Server-Sent Events (SSE)."
        ),
    },
    {
        "name": "feature-engineering",
        "description": (
            "**Time-Series Feature Store**: Rolling momentum indicators, calendar seasonality lags, discount interaction signals, "
            "and feature dataset export services."
        ),
    },
    {
        "name": "health",
        "description": (
            "**Infrastructure & Connectivity**: PostgreSQL RDS encrypted connection verification, TLS cipher audits, "
            "and database readiness probes."
        ),
    },
    {
        "name": "system",
        "description": (
            "**System Runtime Probes**: Service liveness probes, root metadata, and Swagger API documentation discovery."
        ),
    },
]

app = FastAPI(
    lifespan=lifespan,
    title="DemandAI Enterprise Demand Forecasting & Supply Chain API",
    description="""
## DemandAI Enterprise API Services

DemandAI is an enterprise-grade retail demand forecasting and inventory optimization platform. It combines **Recursive Ensemble Machine Learning**, **TreeSHAP Explainable AI**, **Two-Way Price Decision Simulation**, and a **Conversational Agent** to deliver actionable supply chain intelligence.

---

### Core Architectural Capabilities

1. **14-Day Recursive Ensemble Forecasting (`/forecast`)**:
   - Multi-model weighted ensemble: **CatBoost (36%) + LightGBM (34%) + XGBoost (30%)**.
   - Recursive day-by-day inference across a 14-day future horizon.
   - Dynamic inventory health classification: `In Stock`, `Monitor`, `Reorder`, `Critical (Stockout Risk)`, and `Deadstock`.

2. **Two-Way Price Decision & Elasticity Engine (`/forecast/simulate`)**:
   - **Clearance Markdown (-1% to -90%)**: Simulates demand lift, inventory depletion days (DOS), and deadstock clearance feasibility.
   - **Markup & Revenue Optimization (+1% to +150%)**: Computes Price Elasticity of Demand (PED = %ΔQ / %ΔP), 14-day revenue impact ($P \\times Q$), and demand throttling (DOS expansion) for stockout mitigation.
   - **Multi-Warehouse Network Rebalancing**: Auto-detects products across distribution hubs and recommends inter-warehouse stock transfers.

3. **Executive Reporting & PO Replenishment (`/forecast/export`)**:
   - **Multi-page Executive PDF Reports**: Clean 2-page executive layouts with vector charts (Category Donut chart, Top SKU bar charts, and paginated inventory data tables).
   - **PO Replenishment Orders CSV**: ERP-ready purchase order recommendations incorporating lead time and safety stock buffers.

4. **Conversational AI Agent (`/chat`)**:
   - LangChain ReAct SKU specialist powered by `gpt-6-luna`.
   - 9 specialized operational skills with strict tabular presentation directives (Prompt Rule 13).
   - Server-Sent Events (SSE) streaming for real-time token delivery and tool call telemetry.

5. **Authoritative Inventory Wiki (`/wiki`)**:
   - Single Source of Truth for supply chain formulas (ROP, DOS, Safety Stock).
   - Bidirectional backend-to-frontend synchronization ensuring zero configuration drift.
""",
    version="2.0.0",
    openapi_tags=tags_metadata,
    generate_unique_id_function=custom_generate_unique_id,
    contact={
        "name": "DemandAI Engineering Team",
        "url": "http://127.0.0.1:3000",
    },
    license_info={
        "name": "MIT License",
    },
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[0-1])\.\d+\.\d+|192\.168\.\d+\.\d+)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_private_network=True,
)

app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get(
    "/",
    tags=["system"],
    summary="Root Service Discovery",
    description="Returns platform application metadata and link to interactive OpenAPI Swagger documentation.",
)
def root() -> dict[str, str]:
    return {
        "name": settings.app_name,
        "version": "2.0.0",
        "docs": "/docs",
        "redoc": "/redoc",
        "openapi": "/openapi.json",
    }


@app.get(
    "/health",
    tags=["system"],
    summary="Liveness Health Check",
    description="Lightweight liveness probe checking FastAPI server health without contacting PostgreSQL database.",
)
def health() -> dict[str, str]:
    """Liveness check that does not contact PostgreSQL."""
    return {"status": "healthy"}
