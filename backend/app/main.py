import os
from pathlib import Path

import asyncio
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles

from . import daily
from .build import build_info, service_worker_source
from .podcasts import automation
from .routers import anki, articles, podcasts, talk

FRONTEND_DIR = Path(
    os.environ.get("FRONTEND_DIR", Path(__file__).resolve().parents[2] / "frontend")
)

PACKS_DIR = Path(
    os.environ.get("PACKS_DIR", Path(__file__).resolve().parents[2] / "content" / "packs")
)



@asynccontextmanager
async def lifespan(_: FastAPI):
    async def loop():
        while True:
            await articles.refresh_daily()
            await asyncio.sleep(daily.REFRESH_SECONDS)
    task = asyncio.create_task(loop())
    pod = asyncio.create_task(automation.loop())
    yield
    task.cancel()
    pod.cancel()


app = FastAPI(title="Language App", lifespan=lifespan)
app.include_router(anki.router, prefix="/api/anki")
app.include_router(articles.router, prefix="/api/articles")
app.include_router(podcasts.router, prefix="/api/podcasts")
app.include_router(talk.router, prefix="/api/talk")

# The app can be hosted elsewhere (GitHub Pages) and call this server: list its origin here.
_origins = [o for o in os.environ.get("CORS_ORIGINS", "").split(",") if o]
if _origins:
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_methods=["GET", "POST"], allow_headers=["*"])


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/version")
def version() -> dict:
    return {"version": build_info(FRONTEND_DIR)["version"]}


@app.get("/sw.js")
def service_worker() -> Response:
    """Generated per request: version + file list always match what's on disk."""
    return Response(service_worker_source(FRONTEND_DIR), media_type="text/javascript",
                    headers={"Cache-Control": "no-cache"})


@app.get("/api/packs")
def packs() -> list[dict]:
    if not PACKS_DIR.is_dir():
        return []
    return [json.loads(p.read_text()) for p in sorted(PACKS_DIR.glob("*/pack.json"))]


@app.middleware("http")
async def no_cache_shell(request: Request, call_next):
    """Service worker and shell must revalidate so updates reach the phone."""
    response = await call_next(request)
    if request.url.path in ("/sw.js", "/", "/index.html", "/manifest.webmanifest"):
        response.headers["Cache-Control"] = "no-cache"
    return response


GRAMMAR_DIR = Path(
    os.environ.get("GRAMMAR_DIR", Path(__file__).resolve().parents[2] / "content" / "grammar")
)
app.mount("/grammar", StaticFiles(directory=GRAMMAR_DIR, check_dir=False), name="grammar")
app.mount("/packs", StaticFiles(directory=PACKS_DIR, check_dir=False), name="packs")
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
