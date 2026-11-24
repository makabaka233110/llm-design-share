"""Question bank + Feynman practice (Ext 2), hints & preferences (Ext 1), scenarios (Ext 3), gaps."""

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app import agent, db, retrieval
from app.api import User, call

router = APIRouter(prefix="/api", tags=["practice"])


class QuestionIn(BaseModel):
    text: str
    concept: str = ""
    kind: Literal["knowledge", "behavioral", "case"] = "knowledge"
    domain_id: int | None = None


class AttemptIn(BaseModel):
    answer: str
    history_aware: bool = True
    evidence_mode: Literal["weighted", "hybrid", "none"] = "weighted"


class HintIn(BaseModel):
    personalized: bool = True


class HintFeedbackIn(BaseModel):
    feedback: Literal["too_direct", "too_vague", "just_right"]
    comment: str = ""


class PrefsIn(BaseModel):
    summary: str


class ScenarioIn(BaseModel):
    difficulty: Literal["更简单", "相当", "更难"] = "相当"
    gap_ids: list[int] = []


class GapIn(BaseModel):
    text: str
    question_id: int | None = None
    domain_id: int | None = None


class GapPatch(BaseModel):
    confirmed: bool | None = None
    text: str | None = None


# ── questions & answer history ──────────────────────────────────────────

@router.get("/questions")
def list_questions(user: User, domain_id: int | None = None, origin: str | None = None):
    sql = """SELECT q.id, q.text, q.concept, q.origin, q.parent_id, q.session_id, q.domain_id, q.created_at,
               COUNT(a.id) attempts, MAX(a.created_at) last_attempt
             FROM questions q LEFT JOIN attempts a ON a.question_id=q.id WHERE q.user_id=?"""
    args = [user]
    for col, v in (("domain_id", domain_id), ("origin", origin)):
        if v:
            sql += f" AND q.{col}=?"
            args.append(v)
    return db.rows(sql + " GROUP BY q.id ORDER BY q.id DESC", *args)


@router.post("/questions")
def create_question(q: QuestionIn, user: User):
    return db.owned("questions", db.insert("questions", user_id=user, origin="manual", **q.model_dump()), user)


def _attempts(qid: int) -> list[dict]:
    out = db.rows("SELECT * FROM attempts WHERE question_id=? ORDER BY id", qid)
    for a in out:
        a["evaluations"] = db.rows("SELECT * FROM evaluations WHERE attempt_id=? ORDER BY id", a["id"])
    return out


@router.get("/questions/{qid}")
def get_question(qid: int, user: User):
    q = db.owned("questions", qid, user)
    q["attempts"] = _attempts(qid)
    if not q["attempts"]:
        q.pop("eval_points")  # internal scoring points stay hidden until the learner has answered
    q["parent"] = db.row("SELECT id, text FROM questions WHERE id=?", q["parent_id"]) if q["parent_id"] else None
    q["children"] = db.rows("SELECT id, text, origin FROM questions WHERE parent_id=? ORDER BY id", qid)
    q["hints"] = db.rows("SELECT * FROM hints WHERE question_id=? ORDER BY id", qid)
    return q


@router.delete("/questions/{qid}")
def delete_question(qid: int, user: User):
    db.owned("questions", qid, user)
    db.run("DELETE FROM evaluations WHERE attempt_id IN (SELECT id FROM attempts WHERE question_id=?)", qid)
    for t in ("attempts", "hints"):
        db.run(f"DELETE FROM {t} WHERE question_id=?", qid)
    db.run("UPDATE questions SET parent_id=NULL WHERE parent_id=?", qid)
    db.run("DELETE FROM questions WHERE id=?", qid)
    return {"ok": True}


@router.post("/questions/{qid}/attempts")
async def answer(qid: int, a: AttemptIn, user: User):
    """Feynman-style explanation (text, or an edited transcript): new version + evaluation."""
    q = db.owned("questions", qid, user)
    att = agent.record_attempt(user, qid, a.answer, "scenario" if q["origin"] == "scenario" else "feynman")
    ev = await agent.evaluate(user, q, att, kind=q["kind"], evidence_mode=a.evidence_mode,
                              history_aware=a.history_aware)
    return {"attempt": att, "evaluation": ev}


# ── Extension 1: hints with persistent preferences ─────────────────────

@router.post("/questions/{qid}/hint")
async def get_hint(qid: int, h: HintIn, user: User):
    q = db.owned("questions", qid, user)
    passages = await retrieval.evidence(user, f"{q['text']} {q['concept']}")
    return await call(agent.hint, user, q, h.personalized, passages)


@router.post("/hints/{hid}/feedback")
async def hint_feedback(hid: int, f: HintFeedbackIn, user: User):
    db.owned("hints", hid, user)
    db.update("hints", hid, rating=f.feedback, comment=f.comment, feedback_at=db.now())
    return {"prefs": await call(agent.update_prefs, user)}


@router.get("/prefs")
def get_prefs(user: User):
    return {"current": agent.current_prefs(user),
            "versions": db.rows("SELECT * FROM hint_prefs WHERE user_id=? ORDER BY version DESC", user),
            "feedback": db.rows("""SELECT h.*, q.text qtext FROM hints h JOIN questions q ON q.id=h.question_id
                                   WHERE h.user_id=? AND h.rating IS NOT NULL ORDER BY h.feedback_at DESC""", user)}


@router.put("/prefs")
def edit_prefs(p: PrefsIn, user: User):
    return agent.set_prefs(user, p.summary, "edit")


@router.post("/prefs/reset")
def reset_prefs(user: User):
    """Empty preferences; earlier feedback stays visible but no longer feeds generation."""
    return agent.set_prefs(user, "", "reset")


# ── Extension 3: linked scenario questions ─────────────────────────────

@router.post("/questions/{qid}/scenario")
async def make_scenario(qid: int, s: ScenarioIn, user: User):
    q = db.owned("questions", qid, user)
    gaps = [db.owned("gaps", g, user)["text"] for g in s.gap_ids] or \
        [g["text"] for g in db.rows("SELECT text FROM gaps WHERE question_id=? AND confirmed=1", qid)]
    passages = await retrieval.evidence(user, f"{q['text']} {q['concept']}")
    res = await call(agent.scenario, user, q, s.difficulty, gaps, passages)
    return {**res, "question": get_question(res["question_id"], user)}


# ── gaps (from interviews, reflections, or marked during practice) ─────

@router.get("/gaps")
def list_gaps(user: User, confirmed: bool | None = None):
    sql, args = "SELECT * FROM gaps WHERE user_id=?", [user]
    if confirmed is not None:
        sql += " AND confirmed=?"
        args.append(int(confirmed))
    return db.rows(sql + " ORDER BY id DESC", *args)


@router.post("/gaps")
def create_gap(g: GapIn, user: User):
    """A gap the learner marks directly (e.g. from an evaluation point) is confirmed by definition."""
    gid = db.insert("gaps", user_id=user, text=g.text, origin="manual", question_id=g.question_id,
                    domain_id=g.domain_id, confirmed=1)
    return db.owned("gaps", gid, user)


@router.put("/gaps/{gid}")
def update_gap(gid: int, g: GapPatch, user: User):
    db.owned("gaps", gid, user)
    fields = {k: int(v) if isinstance(v, bool) else v for k, v in g.model_dump(exclude_unset=True).items()}
    if fields:
        db.update("gaps", gid, **fields)
    return db.owned("gaps", gid, user)


@router.delete("/gaps/{gid}")
def delete_gap(gid: int, user: User):
    db.owned("gaps", gid, user)
    db.run("DELETE FROM gaps WHERE id=?", gid)
    return {"ok": True}


@router.post("/gaps/{gid}/card-draft")
async def gap_card_draft(gid: int, user: User):
    """Editable flashcard draft for a confirmed gap (not saved until the learner submits it)."""
    g = db.owned("gaps", gid, user)
    if not g["confirmed"]:
        raise HTTPException(400, "请先确认该薄弱点")
    passages = await retrieval.evidence(user, g["text"])
    cards = await call(agent.gen_cards, user, g["text"], 1, passages) if passages else []
    draft = cards[0] if cards else {"question": g["text"], "answer": "", "sources": []}
    return {**draft, "gap_id": gid, "question_id": g["question_id"], "domain_id": g["domain_id"]}
