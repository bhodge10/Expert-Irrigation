"""Expert Inbox Queue — API and, in production, the frontend too."""

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import settings
from .routers import auth as auth_router
from .routers import messages as messages_router
from .routers import private_senders as private_senders_router
from .routers import users as users_router

app = FastAPI(title="Expert Inbox Queue", version="0.1.0")

app.include_router(auth_router.router)
app.include_router(users_router.router)
app.include_router(messages_router.router)
app.include_router(private_senders_router.router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


# In production the built frontend sits in frontend/dist and FastAPI serves it,
# so Render only needs one web service. In dev the Vite server handles this and
# proxies /api here, so the directory won't exist and we skip all of it.
if settings.static_dir.is_dir():
    assets_dir = settings.static_dir / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    index_file = settings.static_dir / "index.html"

    @app.exception_handler(StarletteHTTPException)
    async def spa_fallback(request, exc: StarletteHTTPException):
        """Unknown non-API path? Hand back the app and let the router decide."""
        if exc.status_code == 404 and not request.url.path.startswith("/api"):
            return FileResponse(index_file)
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(index_file)
