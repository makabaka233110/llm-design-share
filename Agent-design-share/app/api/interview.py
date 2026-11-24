"""Mock interviews: each interviewer question is a bank question (origin=interview),
each candidate answer is an attempt scored by the shared evaluator."""

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import agent, db
from app.api import User, call

router = APIRouter(prefix="/api/interview", tags=["interview"])


class StartIn(BaseModel):
    kind: Literal["knowledge", "behavioral", "case"] = "knowledge"
    role: str = ""
    domain_id: int | None = None


class AnswerIn(BaseModel):
    answer: str


def _ask(user: str, s: dict, parent_qid: int | None, follow_ups: int, last_eval: dict | None) -> dict:
    t = agent.interviewer_turn(user, s, follow_ups, last_eval)
    qid = db.insert("questions", user_id=user, domain_id=s["domain_id"], text=t.question, concept=t.concept,
                    kind=s["kind"], origin="interview", session_id=s["id"],
                    parent_id=parent_qid if t.action == "follow_up" else None)
    db.insert("turns", session_id=s["id"], role="interviewer", content=t.question, question_id=qid)
    return {"action": t.action, "question": t.question, "question_id": qid}


@router.post("/start")
async def start(req: StartIn, user: User):
    sid = db.insert("sessions", user_id=user, **req.model_dump())
    s = db.owned("sessions", sid, user)
    try:
        first = await call(_ask, user, s, None, 0, None)
    except HTTPException:
        db.run("DELETE FROM sessions WHERE id=?", sid)
        raise
    return {"session_id": sid, **first}


@router.post("/{sid}/answer")
async def answer(sid: int, a: AnswerIn, user: User):
    s = db.owned("sessions", sid, user)
    if s["finished"]:
        raise HTTPException(400, "面试已结束")
    turns = db.rows("SELECT * FROM turns WHERE session_id=? AND role='interviewer' ORDER BY id", sid)
    q = db.row("SELECT * FROM questions WHERE id=?", turns[-1]["question_id"])
    att = agent.record_attempt(user, q["id"], a.answer, "interview")
    db.insert("turns", session_id=sid, role="candidate", content=a.answer, question_id=q["id"], attempt_id=att["id"])
    ev = await agent.evaluate(user, q, att, kind=s["kind"])

    follow_ups = 0  # consecutive follow-ups on the current question chain
    for t in reversed(turns):
        tq = db.row("SELECT parent_id FROM questions WHERE id=?", t["question_id"])
        if not tq["parent_id"]:
            break
        follow_ups += 1
    nxt = await call(_ask, user, s, q["id"], follow_ups, ev)
    return {"evaluation": ev, **nxt}


@router.post("/{sid}/end")
async def end(sid: int, user: User):
    s = db.owned("sessions", sid, user)
    if s["finished"]:
        return get_session(sid, user)
    try:
        summary = await call(agent.interview_summary, user, s)
    except HTTPException:
        summary = "（总结生成失败，可稍后重试）"
    # Gaps from this session's evaluations enter as unconfirmed candidates.
    evs = db.rows("""SELECT e.feedback, a.question_id FROM evaluations e JOIN attempts a ON a.id=e.attempt_id
                     JOIN questions q ON q.id=a.question_id WHERE q.session_id=? AND e.status='ok'""", sid)
    for e in evs:
        texts = [p["text"] for p in e["feedback"].get("misconceptions", []) + e["feedback"].get("omissions", [])]
        agent.add_gaps(user, texts, "interview", sid, s["domain_id"], e["question_id"])
    db.update("sessions", sid, finished=1, summary=summary)
    return get_session(sid, user)


@router.get("/sessions")
def sessions(user: User):
    return db.rows("""SELECT s.*, COUNT(a.id) answers,
                        (SELECT AVG((json_extract(e.scores,'$.correctness')+json_extract(e.scores,'$.coverage')
                          +json_extract(e.scores,'$.reasoning')+json_extract(e.scores,'$.clarity'))/4.0)
                         FROM evaluations e JOIN attempts a2 ON a2.id=e.attempt_id JOIN questions q2 ON q2.id=a2.question_id
                         WHERE q2.session_id=s.id AND e.status='ok') avg_score
                      FROM sessions s LEFT JOIN questions q ON q.session_id=s.id LEFT JOIN attempts a ON a.question_id=q.id
                      WHERE s.user_id=? GROUP BY s.id ORDER BY s.id DESC""", user)


@router.get("/{sid}")
def get_session(sid: int, user: User):
    s = db.owned("sessions", sid, user)
    s["turns"] = db.rows("SELECT * FROM turns WHERE session_id=? ORDER BY id", sid)
    for t in s["turns"]:
        if t["attempt_id"]:
            t["evaluation"] = db.row("SELECT * FROM evaluations WHERE attempt_id=? ORDER BY id DESC LIMIT 1",
                                     t["attempt_id"])
    s["gaps"] = db.rows("SELECT * FROM gaps WHERE origin='interview' AND origin_id=?", sid)
    return s

