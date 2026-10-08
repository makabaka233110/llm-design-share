"""AI 面试模拟 API

基于 Memsearch 知识库和 LLM 的面试模拟。
"""

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.routes.knowledge import get_memsearch

router = APIRouter(prefix="/api/interview", tags=["interview"])

# LLM 配置（模块级读取，支持运行时环境变量）
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")  # openai / claude
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")  # MiniMax: https://api.minimax.io/v1
LLM_MODEL = os.getenv("LLM_MODEL", "MiniMax-M2.7")

# 面试记录持久化目录
SESSIONS_DIR = Path(__file__).parent.parent.parent / ".interview_sessions"
SESSIONS_DIR.mkdir(exist_ok=True)

# 尝试导入 LLM 库
try:
    from anthropic import Anthropic
    HAS_CLAUDE = True
except ImportError:
    HAS_CLAUDE = False

try:
    from openai import OpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False


class InterviewSession(BaseModel):
    """面试会话"""
    session_id: str
    interview_type: str  # tech / behavior / system_design
    job_title: Optional[str] = None
    company: Optional[str] = None
    created_at: datetime
    finished: bool = False
    messages: list[dict] = []  # 对话历史
    scores: list[dict] = []  # 评分记录
    summary: Optional[str] = None  # 面试总结


class StartInterviewRequest(BaseModel):
    """开始面试请求"""
    interview_type: str  # tech / behavior / system_design
    job_title: Optional[str] = None
    company: Optional[str] = None


class InterviewMessageRequest(BaseModel):
    """面试消息"""
    session_id: str
    user_answer: str


class InterviewResponse(BaseModel):
    """面试响应"""
    ok: bool
    question: Optional[str] = None
    evaluation: Optional[dict] = None  # {score, feedback, knowledge_base}
    error: Optional[str] = None


# 内存缓存 + 文件持久化
_sessions: dict[str, InterviewSession] = {}


def _save_session(session: InterviewSession):
    """持久化到文件"""
    path = SESSIONS_DIR / f"{session.session_id}.json"
    path.write_text(session.model_dump_json(indent=2), encoding="utf-8")


def _load_session(session_id: str) -> InterviewSession | None:
    """从文件加载"""
    path = SESSIONS_DIR / f"{session_id}.json"
    if path.exists():
        return InterviewSession.model_validate_json(path.read_text(encoding="utf-8"))
    return None


def _get_session(session_id: str) -> InterviewSession:
    """获取 session，先查内存再查文件"""
    if session_id in _sessions:
        return _sessions[session_id]
    session = _load_session(session_id)
    if session:
        _sessions[session_id] = session
        return session
    raise HTTPException(status_code=404, detail="Session not found")


def _get_llm_client():
    """获取 LLM 客户端"""
    if not LLM_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="LLM_API_KEY not set. Run: export LLM_API_KEY=sk-xxx",
        )
    if LLM_PROVIDER == "claude" and HAS_CLAUDE:
        return Anthropic(api_key=LLM_API_KEY)
    elif LLM_PROVIDER == "openai" and HAS_OPENAI:
        kwargs = {"api_key": LLM_API_KEY}
        if LLM_BASE_URL:
            kwargs["base_url"] = LLM_BASE_URL
        return OpenAI(**kwargs)
    else:
        raise HTTPException(
            status_code=503,
            detail=f"LLM provider '{LLM_PROVIDER}' not available. "
            f"Install: pip install {'anthropic' if LLM_PROVIDER == 'claude' else 'openai'}",
        )


async def _llm_chat(llm_client, system_prompt: str, messages: list[dict], max_tokens: int = 300) -> str:
    """统一的 LLM 调用，屏蔽 Claude/OpenAI 差异"""
    loop = asyncio.get_event_loop()

    def _sync_call():
        if LLM_PROVIDER == "claude":
            resp = llm_client.messages.create(
                model=LLM_MODEL,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=messages,
            )
            return resp.content[0].text or ""
        else:
            oai_messages = [{"role": "system", "content": system_prompt}] + messages
            resp = llm_client.chat.completions.create(
                model=LLM_MODEL,
                max_tokens=max_tokens,
                messages=oai_messages,
            )
            text = resp.choices[0].message.content or ""
            import re as _re
            return _re.sub(r" thinking[\s\S]*? response\s*", "", text).strip()

    return await loop.run_in_executor(None, _sync_call)




INTERVIEW_PROMPTS = {
    "tech": """你是一位资深技术面试官。
{job_line}
{company_line}

你的职责：
1. 根据候选人的回答进行追问，考察技术深度
2. 简洁而专业的沟通

面试流程：
- 每轮提出一个清晰的技术问题
- 根据候选人回答追问 1-2 次
- 如果回答充分，转到下一个问题

专注于：系统设计、算法、数据结构、分布式系统、性能优化、数据库
保持友好但专业的语气。每次只问一个问题。""",

    "behavior": """你是一位资深行为面试官。
{job_line}
{company_line}

用 STAR 方法（Situation → Task → Action → Result）引导候选人讲述经历。

面试流程：
- 提出一个行为问题（"请描述一次你..."）
- 追问细节：具体情境、你的角色、采取的行动、最终结果
- 如果候选人回答充分，转到下一个问题

专注于：团队合作、冲突解决、领导力、学习能力、抗压能力
每次只问一个问题。""",

    "system_design": """你是一位资深系统设计面试官。
{job_line}
{company_line}

使用 1-3-1 框架引导候选人：
1. 明确问题和约束（1 个问题定义）
2. 引导候选人提出 3 个可选方案并对比
3. 推荐 1 个最终方案并详细设计

面试流程：
- 提出一个系统设计题目（如"设计一个短链接服务"）
- 先确认需求和约束
- 引导候选人画出架构 → 讨论 trade-off → 深入关键组件
- 追问容量估算、存储选型、缓存策略、扩展方案

每次只问一个问题或追问一个方向。""",
}


def _get_interview_prompt(interview_type: str, job_title: str = "", company: str = "") -> str:
    """获取面试官 prompt"""
    template = INTERVIEW_PROMPTS.get(interview_type, INTERVIEW_PROMPTS["tech"])
    return template.format(
        job_line=f"岗位: {job_title}" if job_title else "",
        company_line=f"公司: {company}" if company else "",
    )


async def _evaluate_answer(
    user_answer: str, kb_knowledge: list[dict], llm_client, session: InterviewSession
) -> dict:
    """评估候选人的回答"""
    knowledge_text = "\n".join(
        [
            f"- {k.get('heading', '未知')}: {k.get('content', '')[:200]}"
            for k in kb_knowledge[:3]
        ]
    )

    evaluation_prompt = f"""根据候选人的回答，给出评分。

候选人回答：
{user_answer}

知识库最佳实践：
{knowledge_text if knowledge_text.strip() else "无相关知识库记录"}

请评估，严格返回 JSON：
{{"score": <1到5的整数>, "strengths": "<优点>", "gaps": "<不足>", "follow_up_suggestion": "<追问方向>"}}"""

    try:
        content = await _llm_chat(
            llm_client,
            system_prompt="你是一个面试评估助手。只返回 JSON，不要其他文字。",
            messages=[{"role": "user", "content": evaluation_prompt}],
            max_tokens=500,
        )

        # 解析 JSON（尝试提取 JSON 块）
        try:
            start = content.find("{")
            end = content.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(content[start:end])
        except (json.JSONDecodeError, ValueError):
            pass

        return {
            "score": 3,
            "strengths": "回答合理",
            "gaps": "暂无反馈",
            "follow_up_suggestion": content[:100],
        }
    except Exception as e:
        return {
            "score": 0,
            "error": str(e),
            "strengths": "",
            "gaps": "LLM 服务不可用",
        }


@router.post("/start")
async def start_interview(req: StartInterviewRequest) -> dict:
    """开始新的面试会话"""
    session_id = str(uuid4())
    session = InterviewSession(
        session_id=session_id,
        interview_type=req.interview_type,
        job_title=req.job_title,
        company=req.company,
        created_at=datetime.now(),
    )
    _sessions[session_id] = session

    try:
        llm_client = _get_llm_client()
        system_prompt = _get_interview_prompt(
            req.interview_type, req.job_title or "", req.company or ""
        )

        initial_question = await _llm_chat(
            llm_client,
            system_prompt=system_prompt,
            messages=[
                {"role": "user", "content": "请提出你的第一个问题（简明扼要，1-2 句）"}
            ],
        )

        session.messages.append({"role": "interviewer", "content": initial_question})
        _save_session(session)

        return {
            "ok": True,
            "session_id": session_id,
            "interview_type": req.interview_type,
            "question": initial_question,
        }
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "session_id": session_id,
        }


@router.post("/answer")
async def answer_question(req: InterviewMessageRequest) -> InterviewResponse:
    """提交答案并获得追问 + 评分"""
    session = _get_session(req.session_id)

    if session.finished:
        return InterviewResponse(ok=False, error="Interview already finished")

    try:
        llm_client = _get_llm_client()

        # 1. 从知识库召回相关答案
        kb_knowledge = []
        try:
            memsearch = get_memsearch()
            kb_knowledge = await memsearch.search(
                query=session.messages[-1]["content"],
                top_k=3,
            )
        except Exception:
            pass  # 知识库不可用时不影响面试

        # 2. 评估候选人的回答
        evaluation = await _evaluate_answer(
            req.user_answer, kb_knowledge, llm_client, session
        )
        session.messages.append({"role": "candidate", "content": req.user_answer})
        # 保存评分 + 知识库来源（复盘时可追溯）
        kb_refs = [
            {"heading": k.get("heading", ""), "source": k.get("source", "").split("/")[-1], "chunk_hash": k.get("chunk_hash", "")}
            for k in kb_knowledge[:3]
        ]
        session.scores.append({"question_idx": len(session.messages) - 2, "kb_refs": kb_refs, **evaluation})

        # 3. 生成追问或下一题（合并为单条 user message，避免连续 user role）
        system_prompt = _get_interview_prompt(
            session.interview_type, session.job_title or "", session.company or ""
        )

        recent_history = "\n".join(
            f"[{m['role']}]: {m['content'][:150]}"
            for m in session.messages[-4:]
        )
        combined_context = (
            f"对话历史:\n{recent_history}\n\n"
            f"候选人最新回答: {req.user_answer}\n"
            f"你的评价: {evaluation.get('follow_up_suggestion', '')}\n\n"
            f"请决定：是否追问（问题要更深入）、还是转到下一个新问题？直接输出你的问题。"
        )

        next_question = await _llm_chat(
            llm_client,
            system_prompt=system_prompt,
            messages=[{"role": "user", "content": combined_context}],
        )

        session.messages.append({"role": "interviewer", "content": next_question})
        _save_session(session)

        return InterviewResponse(
            ok=True,
            question=next_question,
            evaluation={
                "score": evaluation.get("score", 0),
                "feedback": f"{evaluation.get('strengths', '')} | {evaluation.get('gaps', '')}",
                "knowledge_base": [
                    {
                        "chunk_hash": k.get("chunk_hash", ""),
                        "source": k.get("source", ""),
                        "heading": k.get("heading", ""),
                        "snippet": k.get("content", "")[:100],
                    }
                    for k in kb_knowledge[:2]
                ],
            },
        )
    except Exception as e:
        return InterviewResponse(ok=False, error=str(e))


@router.post("/end/{session_id}")
async def end_interview(session_id: str) -> dict:
    """结束面试并生成总结"""
    session = _get_session(session_id)

    if session.finished:
        return {"ok": True, "summary": session.summary, "already_finished": True}

    avg_score = (
        sum(s.get("score", 0) for s in session.scores) / len(session.scores)
        if session.scores
        else 0
    )

    try:
        llm_client = _get_llm_client()
        history = "\n".join(
            f"[{m['role']}]: {m['content']}" for m in session.messages
        )
        summary_text = await _llm_chat(
            llm_client,
            system_prompt="你是面试总结助手。",
            messages=[
                {
                    "role": "user",
                    "content": f"""请总结这次{session.interview_type}面试：

{history}

平均评分：{avg_score:.1f}/5

请输出：
1. 整体表现（1-2 句）
2. 3 个优点
3. 3 个需要改进的地方
4. 建议的学习方向""",
                }
            ],
            max_tokens=600,
        )
        session.summary = summary_text
    except Exception:
        session.summary = f"面试结束。平均评分：{avg_score:.1f}/5，共 {len(session.scores)} 道题。"

    session.finished = True
    _save_session(session)

    # 提取面试官问题 → 存入知识库作为"面试信号"
    interviewer_questions = [
        m["content"] for m in session.messages if m["role"] == "interviewer"
    ]
    saved_signal = None
    if interviewer_questions:
        try:
            from app.routes.knowledge import KNOWLEDGE_DIR
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            signal_content = f"""# 面试信号：{session.interview_type} 面试官关注点

> 来源：面试复盘
> 优先级：4
> 时间：{datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
> 面试类型：{session.interview_type}
> 目标岗位：{session.job_title or '未指定'}

---

## 面试官提出的问题（代表当下面试重点）

{chr(10).join(f'{i+1}. {q}' for i, q in enumerate(interviewer_questions))}

## 面试总结

{session.summary or '无'}

## 薄弱点

{chr(10).join(f'- {s.get("gaps", "")}' for s in session.scores if s.get("gaps"))}
"""
            signal_file = KNOWLEDGE_DIR / f"{timestamp}_面试信号_{session.interview_type}.md"
            signal_file.write_text(signal_content, encoding="utf-8")
            saved_signal = signal_file.name
        except Exception:
            pass

    return {
        "ok": True,
        "summary": session.summary,
        "stats": {
            "questions": len(session.scores),
            "average_score": round(avg_score, 1),
            "type": session.interview_type,
        },
        "saved_to_kb": saved_signal,
    }


class InterviewFeedbackRequest(BaseModel):
    """面试中对知识库内容的反馈"""
    session_id: str
    chunk_hash: str
    helpful: bool  # True=这条知识有用, False=没用


@router.post("/feedback")
async def interview_feedback(req: InterviewFeedbackRequest) -> dict:
    """面试中标记知识库内容有用/没用 → 调整知识库优先级"""
    session = _get_session(req.session_id)

    # 调用知识库的 feedback 接口
    from app.routes.knowledge import give_feedback, FeedbackData
    result = await give_feedback(FeedbackData(
        chunk_hash=req.chunk_hash,
        helpful=req.helpful,
    ))

    return {
        "ok": True,
        "session_id": req.session_id,
        "chunk_hash": req.chunk_hash,
        "helpful": req.helpful,
        "priority_update": result,
    }


@router.get("/sessions")
async def list_sessions() -> dict:
    """列出所有面试会话"""
    # 从文件系统加载所有 session
    sessions = []
    for path in sorted(SESSIONS_DIR.glob("*.json"), reverse=True):
        try:
            s = InterviewSession.model_validate_json(path.read_text(encoding="utf-8"))
            avg = (
                sum(sc.get("score", 0) for sc in s.scores) / len(s.scores)
                if s.scores
                else 0
            )
            sessions.append({
                "session_id": s.session_id,
                "type": s.interview_type,
                "job_title": s.job_title,
                "company": s.company,
                "created_at": s.created_at,
                "finished": s.finished,
                "questions": len(s.scores),
                "average_score": round(avg, 1),
            })
        except Exception:
            continue

    return {"ok": True, "sessions": sessions, "total": len(sessions)}


@router.get("/session/{session_id}")
async def get_session(session_id: str) -> dict:
    """获取面试会话详情"""
    session = _get_session(session_id)
    avg_score = (
        sum(s.get("score", 0) for s in session.scores) / len(session.scores)
        if session.scores
        else 0
    )

    return {
        "ok": True,
        "session": {
            "session_id": session.session_id,
            "type": session.interview_type,
            "created_at": session.created_at,
            "finished": session.finished,
            "message_count": len(session.messages),
            "questions_asked": len([m for m in session.messages if m["role"] == "interviewer"]),
            "average_score": round(avg_score, 1),
            "scores": session.scores,
            "summary": session.summary,
        },
        "messages": session.messages,
    }
