"""Mianbi (面壁) — evidence-grounded interview training with persistent learning memory."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from fastapi import FastAPI  # noqa: E402
from fastapi.responses import FileResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from app import db, llm, retrieval  # noqa: E402
from app.api import cards, interview, knowledge, me, practice, speech  # noqa: E402

STATIC = Path(__file__).parent / "static"
state = {"index": "starting"}


async def _warm_index():
    """Load the embedding model and sync the index in the background so the UI opens immediately."""
    try:
        n = await retrieval.reindex()
        state["index"] = f"ok ({retrieval.mem().store.count()} chunks, {n} re-embedded)"
    except Exception as e:
        state["index"] = f"unavailable: {e}"


@asynccontextmanager
async def lifespan(_):
    db.init()
    task = asyncio.create_task(_warm_index())
    yield
    task.cancel()


app = FastAPI(title="Mianbi API", version="0.2.0", lifespan=lifespan)
for r in (knowledge, practice, interview, speech, cards, me):
    app.include_router(r.router)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health():
    return {"index": state["index"], "llm_model": llm.MODEL or "not configured", "data_dir": str(db.DATA_DIR)}
