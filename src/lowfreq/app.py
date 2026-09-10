from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from lowfreq.api import create_router
from lowfreq.application import QuantPlatform
from lowfreq.config import settings

app = FastAPI(title=settings.app_name, version="0.1.0")
platform = QuantPlatform(settings)
app.include_router(create_router(platform))

static_dir = Path(__file__).resolve().parents[2] / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(static_dir / "index.html")
