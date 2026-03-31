"""FastAPI application entry-point and middleware setup."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.auth import router as auth_router
from app.config import SESSION_SECRET, validate_secrets
from app.crypto import hash_api_token
from app.database import async_session
from app.models import ApiToken
from app.routes import router as routes_router


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Validate required secrets on startup."""
    validate_secrets()
    yield


class BearerTokenMiddleware(BaseHTTPMiddleware):
    """Resolve ``Authorization: Bearer <token>`` to user_id + role on request.state."""

    async def dispatch(self, request: Request, call_next):  # noqa: ANN001, ANN201, D102
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            raw_token = auth_header[7:]
            token_hash = hash_api_token(raw_token)
            session_factory = getattr(request.app.state, "session_factory", async_session)
            async with session_factory() as db:
                result = await db.execute(
                    select(ApiToken).where(
                        ApiToken.token_hash == token_hash,
                        ApiToken.is_active.is_(True),
                    ),
                )
                api_token = result.scalar_one_or_none()
                if api_token is not None:
                    request.state._bearer_user_id = api_token.user_id  # noqa: SLF001
                    request.state._bearer_role = api_token.role  # noqa: SLF001
                    api_token.last_used_at = datetime.now(UTC)
                    await db.commit()
        return await call_next(request)


app = FastAPI(title="IssueMatch", lifespan=lifespan)
app.state.session_factory = async_session
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)
app.add_middleware(BearerTokenMiddleware)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

templates = Jinja2Templates(directory="app/templates")

app.include_router(auth_router)
app.include_router(routes_router)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Show login page or redirect authenticated users to /vote."""
    if request.session.get("user_id"):
        return RedirectResponse(url="/vote", status_code=303)  # type: ignore[return-value]
    return templates.TemplateResponse("login.html", {"request": request})
