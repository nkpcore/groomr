"""FastAPI application entrypoint."""

import re
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis

from chair_api import __version__
from chair_api.api.v1 import api_v1_router
from chair_api.core.auth_store import RedisAuthStore
from chair_api.core.config import Settings, get_settings
from chair_api.core.errors import register_exception_handlers
from chair_api.core.logging import configure_logging
from chair_api.db.session import create_engine_and_sessionmaker

_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the CHAIR FastAPI application."""
    cfg = settings or get_settings()
    configure_logging(debug=cfg.debug)

    @asynccontextmanager
    async def lifespan(app_instance: FastAPI) -> AsyncIterator[None]:
        engine, session_factory = create_engine_and_sessionmaker(cfg.database_url)
        redis_client: Redis = Redis.from_url(
            cfg.redis_url,
            decode_responses=True,
            socket_connect_timeout=2.0,
            socket_timeout=2.0,
        )
        app_instance.state.settings = cfg
        app_instance.state.db_engine = engine
        app_instance.state.db_session_factory = session_factory
        app_instance.state.redis_client = redis_client
        app_instance.state.auth_store = RedisAuthStore(redis_client)
        try:
            yield
        finally:
            await redis_client.aclose()
            await engine.dispose()

    app = FastAPI(
        title="CHAIR API",
        version=__version__,
        description=(
            "Authoritative booking, marketplace discovery, partner operations, "
            "and verification API for CHAIR."
        ),
        openapi_url=f"{cfg.api_v1_prefix}/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )
    app.state.settings = cfg

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def attach_request_id(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        raw_req_id = request.headers.get("X-Request-ID") or ""
        request_id = raw_req_id if _VALID_REQUEST_ID.fullmatch(raw_req_id) else str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    register_exception_handlers(app)
    app.include_router(api_v1_router, prefix=cfg.api_v1_prefix)
    return app


app = create_app()
