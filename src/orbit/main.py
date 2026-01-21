"""Application factory: wires middleware, rate limiting, routers, error handling.

Feature routers (projects, tasks) are attached via ``include_feature_routers`` so
the app composes even while those modules are built independently; each router
module exposes a top-level ``router`` object.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from orbit.core.config import get_settings
from orbit.core.logging import RequestContextMiddleware, configure_logging
from orbit.core.rate_limit import limiter


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.debug)

    app = FastAPI(
        title="orbit",
        version="1.0.0",
        summary="A projects & tasks API with JWT auth and project-membership RBAC.",
        description=(
            "Production-grade REST API: layered architecture, JWT auth, "
            "role-based access control, validation, rate limiting, and OpenAPI docs."
        ),
    )

    # Rate limiting (slowapi): default limits from settings + per-route auth limits.
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)
    app.add_middleware(RequestContextMiddleware)

    @app.exception_handler(RateLimitExceeded)
    async def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
        return JSONResponse(
            status_code=429, content={"detail": f"Rate limit exceeded: {exc.detail}"}
        )

    @app.get("/health", tags=["meta"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    _attach_routers(app)
    return app


def _attach_routers(app: FastAPI) -> None:
    import importlib

    from orbit.api.routers import auth

    app.include_router(auth.router)

    # Feature routers built as independent slices. Imported dynamically so the
    # app still boots (and type-checks) if a slice is absent during development.
    for name in ("projects", "tasks"):
        try:
            module = importlib.import_module(f"orbit.api.routers.{name}")
        except ModuleNotFoundError:  # pragma: no cover
            continue
        app.include_router(module.router)


app = create_app()
