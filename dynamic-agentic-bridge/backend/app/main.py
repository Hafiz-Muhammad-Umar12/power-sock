"""
Dynamic Agentic Bridge — FastAPI application entrypoint.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.endpoints import router as api_router
from app.api.websocket import router as ws_router
from app.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    # Startup: nothing to init yet (DB engine created at import time)
    yield
    # Shutdown: dispose engine
    from app.database import engine

    await engine.dispose()


app = FastAPI(
    title="Dynamic Agentic Bridge",
    description="Observe legacy web UIs and expose them as dynamic MCP tools.",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — allow the Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(api_router, prefix="/api")
app.include_router(ws_router)
