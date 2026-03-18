from __future__ import annotations

from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.config import SESSION_SECRET
from app.database import init_db
from app.auth import router as auth_router
from app.routes import router as routes_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    await init_db()
    yield


app = FastAPI(title="IssueMatch", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

templates = Jinja2Templates(directory="app/templates")

app.include_router(auth_router)
app.include_router(routes_router)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    if request.session.get("user_id"):
        from fastapi.responses import RedirectResponse

        return RedirectResponse(url="/vote", status_code=303)  # type: ignore[return-value]
    return templates.TemplateResponse("login.html", {"request": request})
