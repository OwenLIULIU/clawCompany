"""
Main entry point for the Feishu Multi-Bot Bridge.

Starts the FastAPI application with the unified webhook endpoint
and initializes the role registry.
"""

import logging
from fastapi import FastAPI, Request
from contextlib import asynccontextmanager

from roles.registry import build_registry
from feishu.webhook import handle_webhook

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan handler for startup/shutdown."""
    # Build the role registry from environment variables
    build_registry()
    logger.info("Feishu Multi-Bot Bridge started")
    yield
    logger.info("Feishu Multi-Bot Bridge shutting down")


app = FastAPI(title="Feishu Multi-Bot Bridge", lifespan=lifespan)


@app.post("/webhook")
async def webhook_endpoint(request: Request):
    """Unified webhook endpoint for all Feishu bot events."""
    return await handle_webhook(request)


@app.get("/health")
async def health():
    """Health check endpoint."""
    from roles.registry import ROLE_REGISTRY
    return {
        "status": "ok",
        "service": "feishu-multi-bot-bridge",
        "active_roles": len(ROLE_REGISTRY),
        "roles": [
            {"id": r.role_id, "name": r.display_name, "emoji": r.emoji}
            for r in ROLE_REGISTRY.values()
        ],
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
