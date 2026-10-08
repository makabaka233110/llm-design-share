"""知识库 API

基于 Memsearch 的语义搜索知识库。
"""

import re
import time
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

# 延迟导入 memsearch（需要先 pip install）
try:
    from memsearch import MemSearch
except ImportError:
    MemSearch = None

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

# 知识库目录
KNOWLEDGE_DIR = Path(__file__).parent.parent.parent / "知识库"
KNOWLEDGE_DIR.mkdir(exist_ok=True)

# MemSearch 实例（延迟初始化）
_memsearch: MemSearch | None = None


def get_memsearch() -> MemSearch:
    """获取 MemSearch 实例（单例）"""
    global _memsearch
    if _memsearch is None:
        if MemSearch is None:
            raise HTTPException(
                status_code=503,
                detail="Memsearch not installed. Run: pip install memsearch",
            )
        _memsearch = MemSearch(
            paths=[str(KNOWLEDGE_DIR)],
            embedding_provider="onnx",  # 本地免费，零 API key
        )
    return _memsearch


class ContentPaste(BaseModel):
    """粘贴内容"""
    content: str
    title: str | None = None
    source_tag: str = "用户粘贴"  # 小红书/脉脉/自己总结
    priority: int = 2  # 默认优先级


class SearchQuery(BaseModel):
    """搜索查询"""
    query: str
    top_k: int = 5
    source_prefix: str | None = None


class FeedbackData(BaseModel):
    """用户反馈"""
    chunk_hash: str
    helpful: bool  # True=有用, False=没用


QUESTION_HINTS = (
    "什么",
    "为什么",
    "怎么",
    "如何",
    "区别",
    "原理",
    "流程",
    "场景",
    "优缺点",
    "讲一下",
    "介绍一下",
    "说一下",
    "能不能",
    "是否",
    "吗",
    "呢",
)


def _clean_question_line(line: str) -> str:
    """把普通面经问题行清理成适合作为 Markdown 标题的文本。"""
    line = re.sub(r"^\s*(?:[-*+]\s+|(?:\d+|[一二三四五六七八九十]+)[、.)．]\s*)", "", line)
    line = re.sub(r"^\s*(?:Q|q|问|问题|面试官)\s*[:：]\s*", "", line)
    return line.strip()


def _looks_like_question(line: str) -> bool:
    """识别用户直接粘贴的面经问题行。"""
    stripped = _clean_question_line(line)
    if not stripped or stripped.startswith("#"):
        return False
    if len(stripped) > 120:
        return False
    if stripped.endswith(("?", "？")):
        return True
    return any(hint in stripped for hint in QUESTION_HINTS)


def _structure_interview_content(content: str) -> tuple[str, bool]:
    """把无标题面经自动整理成 Markdown 小节，提升 chunk 粒度。"""
    text = content.strip()
    if not text:
        return content, False
    if re.search(r"^#{1,6}\s+", text, flags=re.MULTILINE):
        return text, False

    structured: list[str] = []
    converted = 0
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if _looks_like_question(line):
            question = _clean_question_line(line)
            if structured and structured[-1] != "":
                structured.append("")
            structured.extend([f"## {question}", "", f"问题：{question}"])
            converted += 1
        else:
            structured.append(raw_line)

    if converted == 0:
        return text, False
    return "\n".join(structured).strip(), True


@router.post("/paste")
async def paste_content(data: ContentPaste):
    """粘贴内容 → 自动保存为 markdown → watcher 自动入库"""
    # 生成文件名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    title = data.title or f"粘贴_{timestamp}"
    safe_title = "".join(c if c.isalnum() or c in "_ -" else "_" for c in title)
    filename = f"{timestamp}_{safe_title}.md"
    filepath = KNOWLEDGE_DIR / filename

    structured_content, auto_structured = _structure_interview_content(data.content)

    # 添加元数据到 markdown
    content_with_meta = f"""# {title}

> 来源：{data.source_tag}
> 优先级：{data.priority}
> 时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
> 自动结构化：{"是" if auto_structured else "否"}

---

{structured_content}
"""

    # 保存文件
    filepath.write_text(content_with_meta, encoding="utf-8")

    # 触发索引（如果 watcher 未启动，手动索引）
    mem = get_memsearch()
    try:
        # 尝试索引该文件
        await mem.index()
    except Exception as e:
        # watcher 会自动处理，这里失败不影响
        pass

    return {
        "status": "saved",
        "filename": filename,
        "path": str(filepath),
        "auto_structured": auto_structured,
        "message": "内容已保存，正在索引...",
    }


@router.post("/search")
async def search_knowledge(query: SearchQuery):
    """语义搜索知识库"""
    mem = get_memsearch()

    t0 = time.perf_counter()
    results = await mem.search(
        query.query,
        top_k=query.top_k,
        source_prefix=query.source_prefix,
    )
    search_ms = round((time.perf_counter() - t0) * 1000, 1)

    # 从 chunk content 中解析 priority（写入时存为 "> 优先级：X"）
    query_terms = set(query.query)
    for r in results:
        match = re.search(r">\s*优先级[：:]\s*([\d.]+)", r.get("content", ""))
        priority = float(match.group(1)) if match else 2.0
        r["priority"] = priority
        # 混合分 = Memsearch 返回的 hybrid score（向量余弦 + BM25 经 RRF 融合）
        r["hybrid_score"] = round(r.get("score", 0), 4)
        # 最终分 = 混合分 × 优先级加权
        r["priority_boost"] = round(1 + priority * 0.1, 2)
        r["final_score"] = round(r["hybrid_score"] * r["priority_boost"], 4)
        # 关键词命中分析：模拟 MySQL LIKE '%查询%' 能否找到这条结果
        # 逻辑：如果用户输入的完整查询（或按空格切分的每个词）
        #       都不出现在结果的标题+内容中，则关键词搜索不可能命中
        heading = r.get("heading", "")
        content_text = r.get("content", "")
        full_text = heading + content_text
        q = query.query.strip()
        # 切分方式：空格分词 + 整体查询
        terms = [t for t in q.split() if len(t) >= 2]
        if not terms:
            terms = [q]  # 中文无空格时，整体作为一个查询词
        matched = [t for t in terms if t.lower() in full_text.lower()]
        r["keyword_match"] = len(matched) > 0
        r["keyword_detail"] = f"查询[{q}] vs 标题[{heading}]: {'命中'+str(matched) if matched else '无任何字面匹配'}"

    results.sort(key=lambda x: x["final_score"], reverse=True)

    return {
        "query": query.query,
        "results": results,
        "count": len(results),
        "search_ms": search_ms,
        "engine": "Memsearch (ONNX bge-m3 + Milvus Lite)",
        "method": "Dense Vector + BM25 Sparse + RRF Fusion",
    }


@router.post("/feedback")
async def give_feedback(feedback: FeedbackData):
    """用户反馈（有用/没用）→ 真正修改 markdown 文件里的优先级"""
    mem = get_memsearch()

    # 1. 通过 chunk_hash 精确找到源文件和内容
    try:
        from memsearch.store import _escape_filter_value

        escaped_hash = _escape_filter_value(feedback.chunk_hash)
        results = mem.store.query(filter_expr=f'chunk_hash == "{escaped_hash}"')
        chunk = results[0] if results else None
    except Exception:
        chunk = None

    if not chunk:
        raise HTTPException(status_code=404, detail=f"Chunk not found: {feedback.chunk_hash}")

    source_path = Path(chunk["source"])
    if not source_path.exists():
        raise HTTPException(status_code=404, detail=f"Source file not found: {source_path}")

    # 2. 读取文件，找到优先级行并修改
    text = source_path.read_text(encoding="utf-8")
    delta = 0.5 if feedback.helpful else -1.0

    match = re.search(r"(>\s*优先级[：:]\s*)(\d+(?:\.\d+)?)", text)
    if match:
        old_priority = float(match.group(2))
        new_priority = max(0, min(5, old_priority + delta))  # 限制在 0~5
        text = text[:match.start(2)] + f"{new_priority:.1f}" + text[match.end(2):]
    else:
        # 没有优先级行，在 metadata 区插入一行
        new_priority = max(0, min(5, 2 + delta))
        text = text.replace("---\n\n", f"---\n> 优先级：{new_priority:.1f}\n\n", 1)

    source_path.write_text(text, encoding="utf-8")

    # 3. 触发重新索引（文件改了，watcher 会自动处理，这里兜底）
    try:
        await mem.index()
    except Exception:
        pass

    return {
        "status": "updated",
        "chunk_hash": feedback.chunk_hash,
        "source": str(source_path),
        "old_priority": match and float(match.group(2)) or 2.0,
        "new_priority": new_priority,
        "delta": delta,
    }


class ContentUpdate(BaseModel):
    """编辑内容"""
    content: str | None = None
    title: str | None = None
    source_tag: str | None = None
    priority: float | None = None


@router.get("/list")
async def list_knowledge():
    """列出知识库所有文件"""
    md_files = sorted(KNOWLEDGE_DIR.glob("*.md"), key=lambda f: f.stat().st_mtime, reverse=True)
    items = []
    for f in md_files:
        text = f.read_text(encoding="utf-8")
        # 解析元数据
        title_match = re.search(r"^#\s+(.+)", text)
        source_match = re.search(r">\s*来源[：:]\s*(.+)", text)
        priority_match = re.search(r">\s*优先级[：:]\s*([\d.]+)", text)
        time_match = re.search(r">\s*时间[：:]\s*(.+)", text)
        items.append({
            "filename": f.name,
            "title": title_match.group(1).strip() if title_match else f.stem,
            "source_tag": source_match.group(1).strip() if source_match else "",
            "priority": float(priority_match.group(1)) if priority_match else 2.0,
            "created_at": time_match.group(1).strip() if time_match else "",
            "size": f.stat().st_size,
        })
    return {"items": items, "total": len(items)}


@router.get("/file/{filename}")
async def get_knowledge_file(filename: str):
    """获取单个知识文件内容"""
    filepath = KNOWLEDGE_DIR / filename
    if not filepath.exists() or not filepath.suffix == ".md":
        raise HTTPException(status_code=404, detail="File not found")
    return {
        "filename": filename,
        "content": filepath.read_text(encoding="utf-8"),
    }


@router.put("/file/{filename}")
async def update_knowledge_file(filename: str, data: ContentUpdate):
    """编辑知识文件"""
    filepath = KNOWLEDGE_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="File not found")

    text = filepath.read_text(encoding="utf-8")

    if data.title is not None:
        text = re.sub(r"^#\s+.+", f"# {data.title}", text, count=1)
    if data.source_tag is not None:
        text = re.sub(r"(>\s*来源[：:]\s*).+", rf"\g<1>{data.source_tag}", text)
    if data.priority is not None:
        p = max(0.0, min(5.0, data.priority))
        text = re.sub(r"(>\s*优先级[：:]\s*)[\d.]+", rf"\g<1>{p:.1f}", text)
    if data.content is not None:
        # 替换 --- 之后的正文部分
        parts = text.split("---\n\n", 1)
        if len(parts) == 2:
            text = parts[0] + "---\n\n" + data.content + "\n"
        else:
            text = text + "\n" + data.content + "\n"

    filepath.write_text(text, encoding="utf-8")

    # 触发重新索引
    try:
        mem = get_memsearch()
        await mem.index()
    except Exception:
        pass

    return {"status": "updated", "filename": filename}


@router.delete("/file/{filename}")
async def delete_knowledge_file(filename: str):
    """删除知识文件"""
    filepath = KNOWLEDGE_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="File not found")

    filepath.unlink()

    # 触发重新索引（清理已删除文件的 chunks）
    try:
        mem = get_memsearch()
        await mem.index()
    except Exception:
        pass

    return {"status": "deleted", "filename": filename}


@router.get("/stats")
async def get_stats():
    """知识库统计"""
    mem = get_memsearch()

    md_files = list(KNOWLEDGE_DIR.glob("*.md"))

    return {
        "total_files": len(md_files),
        "total_chunks": mem.store.count(),
        "knowledge_dir": str(KNOWLEDGE_DIR),
    }


@router.post("/index")
async def trigger_index(force: bool = False):
    """手动触发索引"""
    mem = get_memsearch()
    indexed_count = await mem.index(force=force)

    return {
        "status": "indexed",
        "chunks_processed": indexed_count,
    }


@router.post("/compact")
async def compact_knowledge(
    llm_provider: str = "anthropic",
    llm_model: str | None = None,
):
    """压缩总结知识库 → 生成精华到 memory/YYYY-MM-DD.md"""
    mem = get_memsearch()
    summary = await mem.compact(
        llm_provider=llm_provider,
        llm_model=llm_model,
    )
    if not summary:
        return {"status": "empty", "message": "没有可压缩的内容"}
    return {"status": "ok", "summary": summary}
