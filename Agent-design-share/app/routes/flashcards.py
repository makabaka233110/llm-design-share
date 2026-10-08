"""闪卡系统 API

封装 memento_cards.py 的功能为 REST API。
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import BaseModel

router = APIRouter(prefix="/api/flashcards", tags=["flashcards"])

# memento_cards.py 脚本路径
SCRIPT_PATH = Path(__file__).parent.parent / "flashcards" / "memento_cards.py"


class CardCreate(BaseModel):
    """创建闪卡"""
    question: str
    answer: str
    collection: str = "General"


class CardRate(BaseModel):
    """评分闪卡"""
    card_id: str
    rating: Literal["easy", "good", "hard", "retire"]
    user_answer: str | None = None


def _run_script(*args) -> dict:
    """调用 memento_cards.py 脚本，返回 JSON 结果"""
    cmd = [sys.executable, str(SCRIPT_PATH)] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise HTTPException(
            status_code=500,
            detail=f"Script error: {result.stderr}",
        )

    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=500,
            detail=f"Invalid JSON output: {result.stdout}",
        )


@router.post("/cards")
async def create_card(card: CardCreate):
    """创建单张闪卡"""
    result = _run_script(
        "add",
        "--question", card.question,
        "--answer", card.answer,
        "--collection", card.collection,
    )
    return result


@router.get("/cards/due")
async def get_due_cards(collection: str | None = None):
    """获取到期的闪卡"""
    args = ["due"]
    if collection:
        args.extend(["--collection", collection])
    return _run_script(*args)


@router.post("/cards/{card_id}/rate")
async def rate_card(card_id: str, rating: CardRate):
    """评分闪卡"""
    args = [
        "rate",
        "--id", card_id,
        "--rating", rating.rating,
    ]
    if rating.user_answer:
        args.extend(["--user-answer", rating.user_answer])

    return _run_script(*args)


@router.get("/cards")
async def list_cards(
    collection: str | None = None,
    status: Literal["learning", "retired"] | None = None,
):
    """列出所有闪卡"""
    args = ["list"]
    if collection:
        args.extend(["--collection", collection])
    if status:
        args.extend(["--status", status])
    return _run_script(*args)


@router.get("/stats")
async def get_stats():
    """获取统计信息"""
    return _run_script("stats")


@router.post("/import")
async def import_cards(file: UploadFile, collection: str = "Imported"):
    """从 CSV 导入闪卡"""
    import tempfile

    # 保存上传文件到临时文件
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".csv", delete=False) as f:
        content = await file.read()
        f.write(content)
        temp_path = f.name

    try:
        result = _run_script(
            "import",
            "--file", temp_path,
            "--collection", collection,
        )
        return result
    finally:
        Path(temp_path).unlink(missing_ok=True)


@router.get("/export")
async def export_cards():
    """导出闪卡为 CSV"""
    import tempfile
    from fastapi.responses import FileResponse

    # 导出到临时文件
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        temp_path = f.name

    _run_script("export", "--output", temp_path)

    return FileResponse(
        temp_path,
        media_type="text/csv",
        filename="flashcards.csv",
    )


@router.delete("/cards/{card_id}")
async def delete_card(card_id: str):
    """删除单张闪卡"""
    return _run_script("delete", "--id", card_id)


@router.delete("/collections/{collection}")
async def delete_collection(collection: str):
    """删除整个集合"""
    return _run_script("delete-collection", "--collection", collection)


# ── AI 生成闪卡 ────────────────────────────────────────────────────────


class AIGenerateRequest(BaseModel):
    """AI 生成闪卡请求"""
    topic: str  # 主题，如 "Redis持久化" 或 "CAP定理"
    count: int = 5  # 生成数量
    collection: str = "AI生成"


@router.post("/ai-generate")
async def ai_generate_cards(req: AIGenerateRequest):
    """从知识库搜索相关内容 → LLM 生成闪卡

    流程：topic → 知识库语义搜索 → 拼接上下文 → LLM 生成 Q&A → 批量创建闪卡
    """
    import os

    # 1. 从知识库搜索相关内容
    from app.routes.knowledge import get_memsearch
    try:
        mem = get_memsearch()
        results = await mem.search(req.topic, top_k=5)
        context = "\n\n".join(
            f"【{r.get('heading', '未知')}】\n{r.get('content', '')[:500]}"
            for r in results
        )
    except Exception:
        context = ""

    if not context:
        raise HTTPException(status_code=404, detail=f"知识库中没有找到与「{req.topic}」相关的内容，请先粘贴相关面经")

    # 2. 调 LLM 生成闪卡（复用 interview 的统一 LLM 调用）
    from app.routes.interview import _get_llm_client, _llm_chat

    try:
        llm_client = _get_llm_client()
    except HTTPException:
        raise HTTPException(status_code=503, detail="LLM 未配置，请设置 LLM_API_KEY 环境变量")

    import re as _re
    prompt = f"""根据以下知识库内容，生成 {req.count} 个面试闪卡（问答对）。

知识库内容：
{context}

要求：
1. 问题应该是面试官会问的真实问题
2. 答案应该简洁准确，适合快速复习
3. 严格返回 JSON 数组格式：[{{"q":"问题","a":"答案"}}, ...]
4. 只返回 JSON 数组，不要其他文字，不要用 markdown 代码块包裹"""

    try:
        text = await _llm_chat(
            llm_client,
            system_prompt="你是面试闪卡生成助手。只返回JSON数组，不要markdown格式。",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=800,
        )
    except Exception as e:
        return {"ok": False, "error": f"LLM 调用失败: {e}"}

    if not text or not text.strip():
        return {"ok": False, "error": "LLM 返回了空内容", "raw": str(text)}

    # 3. 解析 JSON（兼容 markdown 代码块包裹的情况）
    text_clean = text.strip()
    text_clean = _re.sub(r"^```(?:json)?\s*", "", text_clean)
    text_clean = _re.sub(r"\s*```$", "", text_clean)

    try:
        cards_data = json.loads(text_clean)
        if isinstance(cards_data, dict) and "cards" in cards_data:
            cards_data = cards_data["cards"]
    except (json.JSONDecodeError, ValueError):
        try:
            start = text_clean.find("[")
            end = text_clean.rfind("]") + 1
            cards_data = json.loads(text_clean[start:end]) if start >= 0 else []
        except (json.JSONDecodeError, ValueError):
            cards_data = []

    if not cards_data or not isinstance(cards_data, list):
        return {"ok": False, "error": "LLM 返回格式异常", "raw": text[:500]}

    # 4. 批量创建闪卡
    created = []
    for item in cards_data[:req.count]:
        q = item.get("q", item.get("question", ""))
        a = item.get("a", item.get("answer", ""))
        if q and a:
            result = _run_script(
                "add", "--question", q, "--answer", a, "--collection", req.collection,
            )
            created.append({"question": q, "answer": a, "result": result})

    return {
        "ok": True,
        "topic": req.topic,
        "kb_sources": len(results),
        "generated": len(created),
        "cards": created,
    }
