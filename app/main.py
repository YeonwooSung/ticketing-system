"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import router as v1_router
from app.config import get_settings
from app.redis_client import close_redis, get_redis
from app.tasks import background_tasks


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    logger.info("Starting Ticketing System API...")

    # Initialize Redis connection
    await get_redis()
    logger.info("Redis connection established")

    # Start background tasks
    await background_tasks.start()

    yield

    # Shutdown
    logger.info("Shutting down Ticketing System API...")

    # Stop background tasks
    await background_tasks.stop()

    # Close Redis connection
    await close_redis()
    logger.info("Redis connection closed")


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="""
## Ticketing System API v1

A distributed ticketing system with support for:
- **Distributed Locking**: Redis-based locks for concurrent seat reservation
- **Optimistic Locking**: Database-level version control for seat updates
- **Atomic Reservations**: Multi-seat reservations with rollback support
- **Automatic Expiration**: Background cleanup of expired reservations

### Authentication
All endpoints require `X-User-ID` header for user identification.

### Workflow
1. Browse events and available seats
2. Reserve seats (creates temporary hold)
3. Create booking from reserved seats
4. Confirm payment to finalize booking

### Coming Soon (v2)
- Message queue-based sequential processing
- Priority queuing for high-demand events
        """,
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Configure appropriately for production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include API routers
    app.include_router(v1_router, prefix="/api")

    # Health check endpoint
    @app.get("/health", tags=["Health"])
    async def health_check():
        """Health check endpoint."""
        return {
            "status": "healthy",
            "version": settings.APP_VERSION,
        }

    # Global exception handler
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """Handle uncaught exceptions."""
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal Server Error",
                "detail": str(exc) if settings.DEBUG else None,
            },
        )

    return app


# Create application instance
app = create_app()


def run():
    """Run the application with uvicorn."""
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
    )


if __name__ == "__main__":
    run()
