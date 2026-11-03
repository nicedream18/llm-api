"""WaLiAPI-Python main application entry point."""
import asyncio
import logging
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.controllers.access_routes import router as access_router
from app.api.controllers.administration_routes import router as administration_router
from app.api.controllers.auth_routes import router as auth_router
from app.api.controllers.mcp_routes import router as standard_mcp_router
from app.api.controllers.operations_routes import router as operations_router
from app.api.controllers.platform_routes import router as platform_router
from app.api.controllers.provider_routes import router as provider_router
from app.api.controllers.routes import (
    agent_router,
    apikey_router,
    channel_router,
    dashboard_router,
    gateway_router,
    kb_router,
    mcp_router,
    security_router,
    software_router,
)
from app.api.controllers.routing_routes import router as routing_router
from app.api.controllers.usage_routes import router as usage_router
from app.api.controllers.wiki_routes import router as wiki_router
from app.api.error_handlers import application_error_handler
from app.api.middleware.auth import ApiKeyAuthMiddleware, RequestContextMiddleware
from app.application.errors import ApplicationError
from app.config import config
from app.container import get_container
from app.infrastructure.database.migrations import apply_migrations
from app.infrastructure.telemetry import configure_tracing


@asynccontextmanager
async def lifespan(app):
    await asyncio.to_thread(apply_migrations)
    container = get_container()
    await asyncio.to_thread(container.security_repo.seed_builtin_rules)
    await asyncio.to_thread(container.security_repo.initialize_settings)
    async def close_resource(callback):
        try:
            await asyncio.wait_for(callback(), timeout=10)
        except Exception:  # noqa: BLE001 - continue closing the remaining resources
            logger.warning("Resource shutdown incomplete", exc_info=False)

    async with AsyncExitStack() as stack:
        telemetry = getattr(app.state, "telemetry_provider", None)
        if telemetry:
            stack.callback(telemetry.shutdown)
        stack.push_async_callback(close_resource, container.gateway.aclose)
        for worker in (container.quota_recovery_worker, container.kb_worker, container.provider_sync_worker, container.operations_worker):
            stack.push_async_callback(close_resource, worker.stop)
            await worker.start()
        yield

logging.basicConfig(
    level=getattr(logging, config.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="WaLiAPI-Python", version="1.0.0", lifespan=lifespan)
configure_tracing(app)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(config.cors_allowed_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    max_age=3600,
)

# API key auth middleware
app.add_middleware(RequestContextMiddleware)
app.add_middleware(ApiKeyAuthMiddleware)

# Routers
app.include_router(gateway_router)
app.include_router(channel_router)
app.include_router(apikey_router)
app.include_router(dashboard_router)
app.include_router(kb_router)
app.include_router(agent_router)
app.include_router(security_router)
app.include_router(mcp_router)
app.include_router(standard_mcp_router)
app.include_router(auth_router)
app.include_router(administration_router)
app.include_router(wiki_router)
app.include_router(access_router)
app.include_router(software_router)
app.include_router(provider_router)
app.include_router(routing_router)
app.include_router(usage_router)
app.include_router(operations_router)
app.include_router(platform_router)
app.add_exception_handler(ApplicationError, application_error_handler)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", None)
    logger.error(
        "Unhandled exception",
        exc_info=(type(exc), exc, exc.__traceback__),
        extra={"request_id": request_id},
    )
    return JSONResponse(
        status_code=500,
        content={"code": "0001", "info": "Internal server error", "data": None},
        headers={"X-Request-ID": request_id} if request_id else None,
    )


# Static files (frontend)
static_dir = Path(__file__).parent / "static"


@app.get("/", include_in_schema=False)
async def landing_page():
    return FileResponse(static_dir / "landing" / "index.html")


if static_dir.exists():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=config.server_port, reload=False)
