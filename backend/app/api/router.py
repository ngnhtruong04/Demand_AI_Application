from fastapi import APIRouter

from app.api.routes import chat, feature_engineering, forecast, health, pipeline, wiki


api_router = APIRouter()
api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(
    feature_engineering.router,
    prefix="/feature-engineering",
    tags=["feature-engineering"],
)
api_router.include_router(
    pipeline.router,
    prefix="/pipeline",
    tags=["pipeline"],
)
api_router.include_router(
    forecast.router,
    prefix="/forecast",
    tags=["forecast"],
)
api_router.include_router(
    chat.router,
    prefix="/chat",
    tags=["chat"],
)
api_router.include_router(
    wiki.router,
    prefix="/wiki",
    tags=["wiki"],
)

