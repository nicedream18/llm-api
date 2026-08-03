"""WaLiAPI-Python main application entry point."""
import logging
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.config import config
from app.api.middleware.auth import ApiKeyAuthMiddleware
from app.api.controllers.routes import (
    gateway_router, channel_router, apikey_router, dashboard_router,
    kb_router, agent_router, security_router, mcp_router,
)

logging.basicConfig(
    level=getattr(logging, config.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="WaLiAPI-Python", version="1.0.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    max_age=3600,
)

# API key auth middleware
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


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"code": "0001", "info": str(exc), "data": None},
    )


# Static files (frontend)
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=config.server_port, reload=False)
