"""Interview Assistant - FastAPI Backend

基于 Hermes + Memsearch 组装的面试准备工具后端。
"""

from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.routes import flashcards, knowledge, interview, speech

app = FastAPI(
    title="Interview Assistant API",
    description="AI-powered interview preparation platform",
    version="0.1.0",
)

# 注册路由
app.include_router(flashcards.router)
app.include_router(knowledge.router)
app.include_router(interview.router)
app.include_router(speech.router)

# CORS - 允许前端访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: 生产环境改为具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def root():
    """前端页面"""
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.on_event("startup")
async def startup_index():
    """启动时自动建立知识库向量索引（从 Markdown 文件重建）"""
    try:
        from app.routes.knowledge import get_memsearch
        mem = get_memsearch()
        count = await mem.index()
        print(f"[启动] 知识库索引完成，{count} 个 chunks")
    except Exception as e:
        print(f"[启动] 知识库索引跳过: {e}")




@app.get("/api/health")
async def health():
    """详细健康检查"""
    try:
        from app.routes.knowledge import get_memsearch
        mem = get_memsearch()
        ms_status = f"ok ({mem.store.count()} chunks)"
    except Exception:
        ms_status = "unavailable"

    return {
        "status": "healthy",
        "components": {
            "api": "ok",
            "memsearch": ms_status,
            "flashcards": "ok",
        },
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000, reload=True)
