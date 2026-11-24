"""Speech reflection: local SenseVoice transcription -> learner edits -> AI reflection -> saved record + gaps."""

import asyncio
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import BaseModel

from app import agent, db
from app.api import User, call

router = APIRouter(prefix="/api", tags=["speech"])

AUDIO_EXT = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".webm"}
ROOT = Path(__file__).resolve().parent.parent.parent
_worker = None
_lock = asyncio.Lock()


async def _ask_worker(path: str) -> str:
    """Send one file to the SenseVoice worker process (started on first use, restarted if it died)."""
    global _worker
    if importlib.util.find_spec("funasr") is None:
        raise HTTPException(503, "SenseVoice 未安装：pip install -e \".[speech]\"")
    async with _lock:
        if _worker is None or _worker.returncode is not None:
            _worker = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "app.asr_worker", cwd=ROOT, limit=2**24,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            await _worker.stdout.readline()  # {"ready": true} once the model is loaded
        _worker.stdin.write((path + "\n").encode())
        await _worker.stdin.drain()
        line = await _worker.stdout.readline()
    if not line:
        raise HTTPException(500, "转写进程意外退出")
    msg = json.loads(line)
    if "error" in msg:
        raise HTTPException(500, f"转写失败：{msg['error']}")
    return msg["text"]


@router.post("/speech/transcribe")
async def transcribe(file: UploadFile, user: User):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in AUDIO_EXT:
        raise HTTPException(400, f"不支持的格式，可用：{sorted(AUDIO_EXT)}")
    with tempfile.NamedTemporaryFile(suffix=ext) as tmp:
        tmp.write(await file.read())
        tmp.flush()
        text = await _ask_worker(tmp.name)
    return {"transcript": text, "engine": "SenseVoiceSmall (local)"}


class ReflectIn(BaseModel):
    transcript: str
    kind: Literal["knowledge", "behavioral", "case"] = "knowledge"


class ReflectionIn(BaseModel):
    title: str = ""
    transcript: str
    analysis: dict
    domain_id: int | None = None


@router.post("/speech/reflect")
async def reflect(r: ReflectIn, user: User):
    if not r.transcript.strip():
        raise HTTPException(400, "转写内容为空")
    return (await call(agent.reflect, user, r.transcript, r.kind)).model_dump()


@router.get("/reflections")
def list_reflections(user: User):
    return db.rows("SELECT * FROM reflections WHERE user_id=? ORDER BY id DESC", user)


@router.post("/reflections")
def save_reflection(r: ReflectionIn, user: User):
    """Saved to the learning store (never the reference store); weaknesses become candidate gaps."""
    rid = db.insert("reflections", user_id=user, domain_id=r.domain_id, title=r.title or "语音复盘",
                    transcript=r.transcript, analysis=r.analysis)
    agent.add_gaps(user, r.analysis.get("weaknesses", []), "reflection", rid, r.domain_id)
    return db.owned("reflections", rid, user)


@router.delete("/reflections/{rid}")
def delete_reflection(rid: int, user: User):
    db.owned("reflections", rid, user)
    db.run("DELETE FROM reflections WHERE id=?", rid)
    return {"ok": True}
