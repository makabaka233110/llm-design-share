"""语音转文字 + 面试复盘 API"""

import asyncio
import os
import re
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

try:
    from memsearch.compact import compact_chunks
    HAS_COMPACT = True
except ImportError:
    HAS_COMPACT = False

router = APIRouter(prefix="/api/speech", tags=["speech"])

# ASR 引擎：仅 SenseVoice（中文最佳，本地 CPU 推理）
try:
    from funasr import AutoModel
    HAS_SENSEVOICE = True
except ImportError:
    HAS_SENSEVOICE = False

_asr_model = None
_asr_engine = None


def _set_asr_model(model, engine: str):
    global _asr_model, _asr_engine
    _asr_model = model
    _asr_engine = engine


async def get_asr_model():
    """获取 ASR 模型：仅 SenseVoice（异步加载，不阻塞事件循环）"""
    global _asr_model, _asr_engine
    if _asr_model is not None:
        return _asr_model, _asr_engine

    loop = asyncio.get_event_loop()

    if not HAS_SENSEVOICE:
        raise HTTPException(status_code=503, detail="SenseVoice 未安装。运行: pip install funasr modelscope torch")

    print("[ASR] 开始加载 SenseVoice 模型（首次需下载 ~230MB，请耐心等待）...")
    _asr_model = await loop.run_in_executor(
        None,
        lambda: AutoModel(
            model="iic/SenseVoiceSmall",
            vad_model="iic/speech_fsmn_vad_zh-cn-16k-common-pytorch",
            vad_kwargs={"max_single_segment_time": 30000, "min_single_segment_time": 5000},
            trust_remote_code=True,
        ),
    )
    _asr_engine = "SenseVoice-Small (FunASR)"
    print(f"[ASR] SenseVoice 加载完成")
    return _asr_model, _asr_engine


class TranscribeResponse(BaseModel):
    """转录响应"""
    ok: bool
    transcript: str = ""
    language: str = ""
    error: str = ""


class CompactSummaryRequest(BaseModel):
    """总结请求"""
    text: str
    interview_type: str = "tech"


class CompactSummaryResponse(BaseModel):
    """总结响应"""
    ok: bool
    summary: str = ""
    weak_points: list[str] = []
    error: str = ""


@router.post("/transcribe")
async def transcribe_audio(file: UploadFile = File(...)) -> TranscribeResponse:
    """将音频文件转为文字

    支持：.wav, .mp3, .m4a, .flac 等
    """
    if not HAS_SENSEVOICE:
        return TranscribeResponse(ok=False, error="SenseVoice 未安装。运行: pip install funasr modelscope torch")

    # 验证文件类型
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename")

    allowed_extensions = {".wav", ".mp3", ".m4a", ".flac", ".ogg", ".webm"}
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported format. Allowed: {allowed_extensions}",
        )

    tmp_path = None
    try:
        # 保存到临时文件
        with tempfile.NamedTemporaryFile(delete=False, suffix=file_ext) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name

        model, engine = await get_asr_model()
        loop = asyncio.get_event_loop()

        res = await loop.run_in_executor(
            None, lambda: model.generate(input=tmp_path, language="zh", use_itn=True)
        )
        raw = "".join(r["text"] for r in res if r.get("text"))
        # 去掉 SenseVoice 的特殊标记（语言、情感、事件类型等）
        transcript = re.sub(r"<\|[^|]+\|>", "", raw).strip()

        return TranscribeResponse(
            ok=True,
            transcript=transcript,
            language="zh",
        )
    except Exception as e:
        return TranscribeResponse(
            ok=False,
            error=str(e),
        )
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)


SUMMARIZE_PROMPT = """\
这是一次{interview_type}面试的录音转录。请：
1. 简明扼要总结核心要点（3-5 句）
2. 列举 3 个最明显的不足之处（如回答不完整、缺乏深度等）
3. 建议的改进方向

格式：
总结：xxx
弱点：
- 弱点1
- 弱点2
- 弱点3
改进方向：xxx

面试内容：
{{chunks}}"""


@router.post("/summarize")
async def summarize_interview(req: CompactSummaryRequest) -> CompactSummaryResponse:
    """总结面试录音内容并识别弱点

    使用 memsearch.compact.compact_chunks 调 LLM 做摘要。
    需要环境变量 ANTHROPIC_API_KEY 或 OPENAI_API_KEY。
    """
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="Empty text")

    if not HAS_COMPACT:
        return CompactSummaryResponse(
            ok=False, error="memsearch not installed. Run: pip install memsearch"
        )

    try:
        # compact_chunks 接收 list[dict]，每个 dict 需有 "content" key
        chunks = [{"content": req.text}]
        prompt = SUMMARIZE_PROMPT.format(interview_type=req.interview_type)

        # 优先用环境变量里配好的 LLM（支持 DeepSeek/MiniMax 等 OpenAI 兼容服务）
        llm_provider = os.getenv("LLM_PROVIDER", "openai").lower()
        provider = "anthropic" if llm_provider in {"anthropic", "claude"} else "openai"

        summary = await compact_chunks(
            chunks,
            llm_provider=provider,
            model=os.getenv("LLM_MODEL") or None,
            prompt_template=prompt,
            base_url=os.getenv("LLM_BASE_URL") or None,
            api_key=os.getenv("LLM_API_KEY") or None,
        )

        # 解析弱点
        weak_points = []
        if "弱点：" in summary or "弱点:" in summary:
            split_key = "弱点：" if "弱点：" in summary else "弱点:"
            weak_section = summary.split(split_key)[1].split("改进")[0]
            weak_points = [
                p.strip("- \n").strip()
                for p in weak_section.split("\n")
                if p.strip().startswith("-")
            ]

        return CompactSummaryResponse(
            ok=True,
            summary=summary,
            weak_points=weak_points,
        )

    except Exception as e:
        return CompactSummaryResponse(ok=False, error=str(e))


@router.post("/analyze")
async def analyze_interview(req: CompactSummaryRequest) -> dict:
    """完整分析：总结 + 弱点 + 生成闪卡草稿"""
    result = await summarize_interview(req)
    if not result.ok:
        raise HTTPException(status_code=500, detail=result.error)

    flashcards = [
        {
            "question": f"我在面试中发现: {wp}，应该如何改进？",
            "answer_draft": "改进建议：[待填充]",
            "collection": f"{req.interview_type}_面试复盘",
            "source": "interview_review",
        }
        for wp in result.weak_points[:3]
    ]

    return {
        "ok": True,
        "summary": result.summary,
        "weak_points": result.weak_points,
        "flashcard_drafts": flashcards,
        "next_step": "手动完善闪卡答案，然后调用 POST /api/flashcards/cards 创建",
    }


class SaveToKBRequest(BaseModel):
    """将转写/录音内容存入知识库"""
    text: str
    title: str | None = None
    interview_type: str = "tech"


@router.post("/save-to-kb")
async def save_transcript_to_kb(req: SaveToKBRequest) -> dict:
    """将面试录音转写存入知识库

    面试官的提问 = 当下面试重点信号，值得作为高优先级知识保留。
    """
    from datetime import datetime
    from app.routes.knowledge import KNOWLEDGE_DIR, get_memsearch

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    title = req.title or f"面试录音_{req.interview_type}_{timestamp}"
    safe_title = "".join(c if c.isalnum() or c in "_ -" else "_" for c in title)

    content = f"""# {title}

> 来源：面试录音
> 优先级：4
> 时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
> 面试类型：{req.interview_type}

---

{req.text}
"""
    filepath = KNOWLEDGE_DIR / f"{timestamp}_{safe_title}.md"
    filepath.write_text(content, encoding="utf-8")

    # 触发索引
    try:
        mem = get_memsearch()
        await mem.index()
    except Exception:
        pass

    return {
        "ok": True,
        "filename": filepath.name,
        "message": f"已存入知识库（优先级4），下次搜索即可召回",
    }
